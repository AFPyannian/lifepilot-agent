FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

COPY requirements.txt ./
RUN python -m pip install \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch==2.13.0+cpu"
RUN python -m pip install --requirement requirements.txt

COPY alembic.ini pyproject.toml ./
COPY app ./app
COPY frontend ./frontend
COPY migrations ./migrations
COPY scripts ./scripts

RUN groupadd --system lifepilot \
    && useradd --system --gid lifepilot --home-dir /app lifepilot \
    && mkdir --parents /app/data /app/knowledge_base /app/logs /app/models \
    && chown --recursive lifepilot:lifepilot /app

USER lifepilot

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
