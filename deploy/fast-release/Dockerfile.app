ARG RUNTIME_IMAGE
FROM ${RUNTIME_IMAGE}

LABEL org.opencontainers.image.title="RAG-Anything fast release"

COPY payload/ /app/
WORKDIR /app

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)"

EXPOSE 8000
CMD ["python", "server.py"]
