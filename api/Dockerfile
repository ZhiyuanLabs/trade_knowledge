FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/appuser/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/appuser/.cache/huggingface

WORKDIR /app

ARG TORCH_VERSION=2.6.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}" && \
    pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/data "$HF_HOME" && \
    chown -R appuser:appuser /app /home/appuser

RUN chmod +x /app/docker-entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
