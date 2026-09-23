FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SWISS_EPHE_PATH=/opt/swiss-ephe

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

COPY pyproject.toml README.md LICENSE ./
COPY swiss_api ./swiss_api
COPY scripts ./scripts

RUN /opt/venv/bin/python -m pip install --no-compile . \
    && python scripts/fetch_ephemeris.py --destination "$SWISS_EPHE_PATH"

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    SWISS_EPHE_PATH=/opt/swiss-ephe

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/swiss-ephe /opt/swiss-ephe

RUN chown -R app:app /app /opt/venv "$SWISS_EPHE_PATH"

USER app
EXPOSE 8080

CMD ["python", "-m", "swiss_api"]
