#!/bin/bash
# ============================================================
# RAG-Anything 云服务器一键部署脚本
# 在云服务器上以 root 身份执行此脚本
# ============================================================
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo "============================================"
echo "  RAG-Anything 生产环境部署"
echo "============================================"
echo ""

# ── 0. 检测操作系统 ──────────────────────────────────
log "检测操作系统..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "  系统: $NAME $VERSION"
else
    warn "无法检测操作系统，继续..."
fi

# ── 1. 安装 Docker ────────────────────────────────────
log "检查 Docker 安装状态..."
if ! command -v docker &>/dev/null; then
    warn "Docker 未安装，正在安装..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
    log "Docker 安装完成"
else
    log "Docker 已安装: $(docker --version)"
fi

# 检查 docker compose 子命令
if ! docker compose version &>/dev/null; then
    warn "docker compose 插件未安装，安装中..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin 2>/dev/null || \
    yum install -y docker-compose-plugin 2>/dev/null || \
    err "无法安装 docker compose 插件，请手动安装"
fi
log "Docker Compose: $(docker compose version)"

# ── 2. 检查/安装 git ──────────────────────────────────
if ! command -v git &>/dev/null; then
    warn "git 未安装，安装中..."
    apt-get update -qq && apt-get install -y -qq git 2>/dev/null || \
    yum install -y git 2>/dev/null
fi

# ── 3. 配置防火墙 ────────────────────────────────────
log "配置防火墙..."
if command -v ufw &>/dev/null; then
    ufw allow 80/tcp 2>/dev/null || true
    ufw allow 443/tcp 2>/dev/null || true
    log "ufw: 已放行端口 80, 443"
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent --add-port=80/tcp 2>/dev/null || true
    firewall-cmd --permanent --add-port=443/tcp 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
    log "firewalld: 已放行端口 80, 443"
else
    warn "未检测到防火墙工具，请手动在云服务商控制台放行 80/443 端口"
fi

# ── 4. 克隆/更新项目 ──────────────────────────────────
APP_DIR="/opt/raganything"
REPO_URL="${1:-}"

if [ -z "$REPO_URL" ]; then
    warn "未提供仓库地址，跳过 git clone"
    if [ ! -d "$APP_DIR" ]; then
        err "请提供仓库地址: $0 <git-repo-url>"
    fi
fi

if [ -n "$REPO_URL" ] && [ ! -d "$APP_DIR/.git" ]; then
    log "克隆仓库: $REPO_URL -> $APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
elif [ -n "$REPO_URL" ] && [ -d "$APP_DIR/.git" ]; then
    log "更新仓库..."
    cd "$APP_DIR"
    git pull
fi

cd "$APP_DIR"

# ── 5. 配置 .env ─────────────────────────────────────
log "配置环境变量..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        warn "已从 .env.example 创建 .env，请编辑填入真实配置："
        echo ""
        echo "  必填项："
        echo "    LLM_BINDING_API_KEY   — LLM API 密钥"
        echo "    LLM_BINDING_HOST      — LLM API 地址"
        echo "    JWT_SECRET            — JWT 签名密钥（openssl rand -hex 32）"
        echo "    DEFAULT_ADMIN_PASSWORD — 管理员密码"
        echo ""
        echo "  编辑命令: vim $APP_DIR/.env"
        echo ""
    else
        err "未找到 .env.example 文件"
    fi
else
    log ".env 文件已存在"
fi

# 自动生成 JWT 密钥（如果未设置）
if grep -q "^JWT_SECRET=$" .env 2>/dev/null || ! grep -q "^JWT_SECRET=" .env 2>/dev/null; then
    NEW_JWT=$(openssl rand -hex 32)
    if grep -q "^JWT_SECRET=" .env 2>/dev/null; then
        sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$NEW_JWT/" .env
    else
        echo "JWT_SECRET=$NEW_JWT" >> .env
    fi
    log "已自动生成 JWT_SECRET"
fi
if grep -q "^JWT_REFRESH_SECRET=$" .env 2>/dev/null || ! grep -q "^JWT_REFRESH_SECRET=" .env 2>/dev/null; then
    NEW_REFRESH=$(openssl rand -hex 32)
    if grep -q "^JWT_REFRESH_SECRET=" .env 2>/dev/null; then
        sed -i "s/^JWT_REFRESH_SECRET=.*/JWT_REFRESH_SECRET=$NEW_REFRESH/" .env
    else
        echo "JWT_REFRESH_SECRET=$NEW_REFRESH" >> .env
    fi
    log "已自动生成 JWT_REFRESH_SECRET"
fi

# ── 6. 创建持久化目录 ────────────────────────────────
log "创建数据目录..."
mkdir -p rag_storage uploads output
chmod 755 rag_storage uploads output

# ── 7. 构建并启动 ────────────────────────────────────
log "构建 Docker 镜像（首次可能需要 5-15 分钟）..."
docker compose build --pull

log "启动服务..."
docker compose up -d

# ── 8. 等待健康检查 ──────────────────────────────────
log "等待服务就绪..."
RETRIES=30
for i in $(seq 1 $RETRIES); do
    if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
        log "服务启动成功！(${i}s)"
        break
    fi
    if [ $i -eq $RETRIES ]; then
        warn "服务可能启动较慢，查看日志：docker compose logs app"
    fi
    sleep 2
done

# ── 9. 打印状态 ──────────────────────────────────────
echo ""
echo "============================================"
echo "  🎉 部署完成"
echo "============================================"
echo ""
echo "  访问地址:  http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP')"
echo ""
echo "  常用命令:"
echo "    docker compose ps          查看服务状态"
echo "    docker compose logs -f app 查看应用日志"
echo "    docker compose restart     重启服务"
echo "    docker compose down        停止服务"
echo "    docker compose up -d       启动服务"
echo "    docker compose pull        更新镜像"
echo ""
echo "  管理后台: http://YOUR_IP/admin"
echo "  API 文档: http://YOUR_IP/api/docs  (如果开启)"
echo ""
