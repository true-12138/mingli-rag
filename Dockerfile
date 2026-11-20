# 单镜像跑 FastAPI。BGE-M3 权重不打进镜像，首次查询时下载到挂载的 HF 缓存目录。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

# torch 必须先单独装 CPU 版：PyPI 上的 torch 会连带拖一长串 nvidia-* CUDA 包
# （cudnn 519MB、cublas 等，合计 3GB+），而推理机没有 GPU，纯属浪费镜像和在港带宽。
# download.pytorch.org/whl/cpu 只放 CPU wheel，装机实测 ~160MB/s。
# lunar_python 只有源码包，--no-build-isolation 让它复用镜像里的 setuptools，
# 否则 pip 会另开隔离环境再下一遍 setuptools，在这个网络下容易整段超时。
COPY requirements.txt .
RUN pip install --timeout 60 --retries 5 -U pip setuptools wheel \
    && pip install --index-url https://download.pytorch.org/whl/cpu \
         --extra-index-url https://pypi.org/simple "torch==2.2.2+cpu" \
    && pip install --timeout 120 --retries 10 --prefer-binary --no-build-isolation -r requirements.txt

COPY src ./src
COPY data ./data
COPY eval ./eval
# 业务库表结构由 Alembic 管理，容器启动时先跑迁移
COPY alembic.ini .
COPY migrations ./migrations

ENV MINGLI_HOST=0.0.0.0 \
    MINGLI_PORT=8000 \
    MINGLI_ANSWER_SLOTS=20

EXPOSE 8000

# 用标准库探活，避免为了 HEALTHCHECK 再装 curl。
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# 先建表再起服务；alembic upgrade 可重复执行，已有表时是空操作
CMD ["sh", "-c", "alembic upgrade head && python src/api.py"]
