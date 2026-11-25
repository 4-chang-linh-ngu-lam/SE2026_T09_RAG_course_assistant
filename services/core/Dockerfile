FROM python:3.12-slim AS builder
WORKDIR /build
COPY packages/service-auth ./packages/service-auth
COPY services/core/pyproject.toml ./services/core/pyproject.toml
COPY services/core/app ./services/core/app
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./packages/service-auth ./services/core

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 core && useradd --uid 10001 --gid core --no-create-home core
COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index /tmp/wheels/* && rm -rf /tmp/wheels
WORKDIR /srv
COPY services/core/migrations ./migrations
COPY services/core/alembic.ini ./
USER core
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
