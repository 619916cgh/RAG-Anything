#!/bin/bash
# RAG-Anything Docker 入口脚本
# 1. 将前端构建产物复制到共享卷供 nginx 使用
# 2. 启动 Python 服务器

set -e

FRONTEND_SRC="/app/frontend/dist"
FRONTEND_SHARED="/shared_frontend"

echo "[entrypoint] Copying frontend assets to shared volume..."
if [ -d "$FRONTEND_SRC" ] && [ -n "$(ls -A "$FRONTEND_SRC" 2>/dev/null)" ]; then
    mkdir -p "$FRONTEND_SHARED"
    cp -r "$FRONTEND_SRC"/* "$FRONTEND_SHARED"/
    echo "[entrypoint] Frontend assets copied: $(ls -1 "$FRONTEND_SHARED" | wc -l) files"
else
    echo "[entrypoint] WARNING: Frontend build not found at $FRONTEND_SRC"
    echo "[entrypoint] The API will work but the web UI may not be available."
fi

echo "[entrypoint] Starting RAG-Anything server..."
exec python server.py "$@"
