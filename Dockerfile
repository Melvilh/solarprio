FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[runtime]" \
    && useradd --system --no-create-home solarprio

USER solarprio
VOLUME ["/config"]
ENTRYPOINT ["python", "-m", "solarprio"]
CMD ["--config", "/config/config.toml"]
