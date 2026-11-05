# CPU-образ и полный набор его пакетов закреплены по digest и lock-файлу.
FROM vllm/vllm-openai-cpu:v0.27.0-x86_64@sha256:ad2d073b2ff1b755e0d0b9e33a581bfcbadde22c13a073af1dfff1d553119d38
USER root
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY tools/verify_lock.py /app/verify_lock.py
RUN python /app/verify_lock.py /app/requirements.txt \
    && python -m pip check \
    && useradd --uid 10001 --create-home inference \
    && mkdir -p /models \
    && chown 10001:10001 /models /app
COPY --chown=10001:10001 inference /app/inference
ENV HOME=/tmp \
    HF_HOME=/tmp/huggingface \
    XDG_CACHE_HOME=/tmp/cache \
    VLLM_CACHE_ROOT=/tmp/vllm \
    TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VLLM_TARGET_DEVICE=cpu
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["python", "-m", "inference.server"]
