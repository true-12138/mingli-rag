# 单镜像跑 FastAPI。BGE-M3 权重不打进镜像，首次查询时下载到挂载的 HF 缓存目录。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

# 运行时数据目录：业务库 / 评测库 / 额度计数。部署时由 compose 挂卷覆盖，
# 这里先建好，避免直接 `docker run` 时 SQLite 找不到父目录。
RUN mkdir -p /var/lib/mingli

# sentence-transformers / torch 的 wheel 已经覆盖常用平台，不需要 build-essential。
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY data ./data
COPY eval ./eval
# 业务库表结构由 Alembic 管理，容器启动时先跑迁移
COPY alembic.ini .
COPY migrations ./migrations

ENV MINGLI_HOST=0.0.0.0 \
    MINGLI_PORT=8000 \
    MINGLI_MAX_CONCURRENCY=4

EXPOSE 8000

# 用标准库探活，避免为了 HEALTHCHECK 再装 curl。
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# 先建表再起服务；alembic upgrade 可重复执行，已有表时是空操作
CMD ["sh", "-c", "alembic upgrade head && python src/api.py"]
