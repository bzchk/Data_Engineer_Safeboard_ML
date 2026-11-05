FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
WORKDIR /app
COPY containers/requirements.downloader.txt /app/requirements.txt
COPY tools/verify_lock.py /app/verify_lock.py
RUN python /app/verify_lock.py /app/requirements.txt \
    && groupadd --gid 10001 inference \
    && useradd --uid 10001 --gid 10001 --create-home inference \
    && mkdir -p /models \
    && chown 10001:10001 /models
COPY tools/cache_model.py /app/cache_model.py
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["python", "/app/cache_model.py"]
