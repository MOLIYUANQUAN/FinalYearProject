# Friday — cloud image (secrets via env, never baked in)
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8080

# TZ=Europe/London 需要系统时区数据（slim 镜像一般自带，没有就装上）
RUN test -e /usr/share/zoneinfo/Europe/London \
    || (apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*)

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY src ./src
COPY static ./static
COPY data ./data
COPY scripts ./scripts

# data/memory 等可写；secrets 启动时从环境变量落下
RUN mkdir -p secrets data/memory data/usage data/logs \
    && chmod -R a+rwX data secrets

EXPOSE 8080

CMD ["python", "-m", "src.main"]
