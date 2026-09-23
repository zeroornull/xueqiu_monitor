FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    STATE_FILE=/data/monitor_state.json \
    LOG_FILE=

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY xueqiu_monitor.py notifier.py ./
RUN pip install --no-cache-dir "requests==2.34.2" "python-dotenv==1.2.3" \
    && chown -R app:app /app

USER 1000
CMD ["python", "xueqiu_monitor.py"]
