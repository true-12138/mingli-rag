# 单镜像跑 FastAPI。BGE-M3 权重不打进镜像，首次查询时下载到挂载的 HF 缓存目录。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

# sentence-transformers / torch 的 wheel 已经覆盖常用平台，不需要 build-essential。
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY data ./data
COPY eval ./eval

ENV MINGLI_HOST=0.0.0.0 \
    MINGLI_PORT=8000 \
    MINGLI_MAX_CONCURRENCY=4

EXPOSE 8000

# 用标准库探活，避免为了 HEALTHCHECK 再装 curl。
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["python", "src/api.py"]
