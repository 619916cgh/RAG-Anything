# Network source overrides for restricted networks. Defaults keep the
# canonical upstreams; pass --build-arg to switch to a reachable mirror
# (e.g. DEBIAN_MIRROR_HOST=mirrors.aliyun.com, PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple).
ARG DEBIAN_MIRROR_HOST=deb.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PYTORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu
# Slow or proxied package sources can take longer than the default read window.
# These are transport controls only; lock contents and hash verification remain fixed.
ARG PIP_NETWORK_TIMEOUT=600
ARG PIP_NETWORK_RETRIES=12

FROM node:20-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Bookworm still provides OpenJDK 17, which is required by the
# OpenDataLoader runtime. The floating slim tag moved to trixie, where that
# package is no longer available.
FROM python:3.11-slim-bookworm AS app-runtime

LABEL org.opencontainers.image.title="RAG-Anything"
LABEL org.opencontainers.image.description="All-in-One Multimodal RAG System"

ARG DEBIAN_MIRROR_HOST
ARG PIP_INDEX_URL
ARG PYTORCH_CPU_INDEX_URL
ARG PIP_NETWORK_TIMEOUT
ARG PIP_NETWORK_RETRIES

# Native dependencies include ffmpeg/ffprobe for video indexing. Debian's
# mirrors can drop an individual package fetch during a long LibreOffice
# install, so use HTTPS plus bounded APT and install-level retries.
RUN set -eux; \
    sed -i "s|http://deb.debian.org|https://${DEBIAN_MIRROR_HOST}|g" /etc/apt/sources.list.d/debian.sources; \
    printf 'Acquire::Retries "5";\nAcquire::http::Timeout "120";\nAcquire::https::Timeout "120";\n' > /etc/apt/apt.conf.d/80-network-retries; \
    for attempt in 1 2 3; do \
        if apt-get update && apt-get install -y --no-install-recommends \
            libreoffice \
            ffmpeg \
            libpq-dev \
            postgresql-client \
            gcc \
            libgl1 \
            libglib2.0-0 \
            libgomp1 \
            openjdk-17-jre-headless; then \
            break; \
        fi; \
        if [ "$attempt" = 3 ]; then exit 1; fi; \
        rm -rf /var/lib/apt/lists/*; \
        sleep "$((attempt * 5))"; \
    done; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 婵炴挻纰嶇换鍡欑矉?
COPY requirements.cpu-linux-py311-x86_64.lock .
COPY requirements.cpu-pytorch-linux-py311-x86_64.lock .
COPY scripts/verify_cpu_runtime.py /usr/local/bin/verify_cpu_runtime.py
# Keep PyTorch's index isolated. As an extra index it can supply generic
# dependencies that redirect to public PyPI and bypass the selected mirror.
RUN python -m pip --isolated install --no-cache-dir --timeout ${PIP_NETWORK_TIMEOUT} --retries ${PIP_NETWORK_RETRIES} \
    --index-url ${PYTORCH_CPU_INDEX_URL} \
    --require-hashes \
    --no-deps \
    -r requirements.cpu-pytorch-linux-py311-x86_64.lock \
    && python -m pip --isolated install --no-cache-dir --timeout ${PIP_NETWORK_TIMEOUT} --retries ${PIP_NETWORK_RETRIES} \
    --index-url ${PIP_INDEX_URL} \
    --require-hashes \
    -r requirements.cpu-linux-py311-x86_64.lock \
    && python /usr/local/bin/verify_cpu_runtime.py --runtime app

# 闁圭厧鐡ㄥ濠氬极閵堝棛顩烽柨婵嗘川閸?
FROM app-runtime AS app-source
COPY . .

# 闂佸憡鎸哥粔鍫曨敂椤掑嫬鍑犻柛鏇ㄥ亞缁?
COPY --from=frontend-build /frontend/dist /app/frontend/dist

WORKDIR /app

# 闂佺顑冮崕閬嶅箖瀹ュ憘娑㈠焵椤掑嫬钃?
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

EXPOSE 8000

# 闂佸憡鍑归崹鐗堟叏閳哄懎宸濋柟瀛樺笚婵?
CMD ["python", "server.py"]

# Compatibility verification target for the OpenDataLoader runtime bundled in
# the default image. Build explicitly with:
# docker build --target opendataloader -t raganything:opendataloader .
FROM app-source AS default

FROM nginx:alpine AS frontend
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /frontend/dist /usr/share/nginx/html

FROM default AS opendataloader
RUN java -version 2>&1 | grep -Eq 'version "17\.|openjdk 17\.' \
    && python -c "from importlib.metadata import version; assert version('opendataloader-pdf') == '2.5.0'"

# Marker is intentionally isolated: marker-pdf requires Pillow<11 while the
# MinerU runtime in `base` requires Pillow>=11. Build and deploy this target
# as a separate parser worker image; never install marker-pdf into `base`.
FROM python:3.11-slim-bookworm AS marker-runtime
ARG DEBIAN_MIRROR_HOST
ARG PIP_INDEX_URL
ARG PYTORCH_CPU_INDEX_URL
ARG PIP_NETWORK_TIMEOUT
ARG PIP_NETWORK_RETRIES
RUN sed -i "s|http://deb.debian.org|https://${DEBIAN_MIRROR_HOST}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libreoffice \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /marker
COPY requirements.marker.cpu-linux-py311-x86_64.lock .
COPY requirements.cpu-pytorch-linux-py311-x86_64.lock .
COPY scripts/verify_cpu_runtime.py /usr/local/bin/verify_cpu_runtime.py
RUN python -m pip --isolated install --no-cache-dir --timeout ${PIP_NETWORK_TIMEOUT} --retries ${PIP_NETWORK_RETRIES} \
    --index-url ${PYTORCH_CPU_INDEX_URL} \
    --require-hashes \
    --no-deps \
    -r requirements.cpu-pytorch-linux-py311-x86_64.lock \
    && python -m pip --isolated install --no-cache-dir --timeout ${PIP_NETWORK_TIMEOUT} --retries ${PIP_NETWORK_RETRIES} \
    --index-url ${PIP_INDEX_URL} \
    --require-hashes \
    -r requirements.marker.cpu-linux-py311-x86_64.lock \
    && python /usr/local/bin/verify_cpu_runtime.py --runtime marker

FROM marker-runtime AS marker
WORKDIR /marker
COPY raganything/parser/marker_worker.py /marker/marker_worker.py
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/healthz', timeout=5)"
EXPOSE 8765
CMD ["python", "/marker/marker_worker.py"]
