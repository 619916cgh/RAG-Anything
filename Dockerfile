FROM node:20-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS base

LABEL org.opencontainers.image.title="RAG-Anything"
LABEL org.opencontainers.image.description="All-in-One Multimodal RAG System"

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY . .

# 前端构建
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

WORKDIR /app

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

EXPOSE 8000

# 启动命令
CMD ["python", "server.py"]

# Opt-in OpenDataLoader runtime. Build explicitly with:
# docker build --target opendataloader -t raganything:opendataloader .
FROM base AS opendataloader
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir ".[opendataloader]" \
    && java -version 2>&1 | grep -Eq 'version "17\\.|openjdk 17\\.' \
    && python -c "from importlib.metadata import version; assert version('opendataloader-pdf') == '2.5.0'"

# Keep the default final target free of OpenDataLoader and Java.
FROM base AS default
