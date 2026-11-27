FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10002 document \
    && useradd --uid 10002 --gid document --no-create-home document \
    && mkdir -p /var/lib/lumi-document/files \
    && chmod 700 /var/lib/lumi-document /var/lib/lumi-document/files \
    && chown -R document:document /var/lib/lumi-document
COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index /tmp/wheels/* && rm -rf /tmp/wheels
WORKDIR /srv/document
COPY migrations ./migrations
COPY alembic.ini ./
USER document
CMD ["python", "-m", "uvicorn", "document_service.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1", "--no-proxy-headers"]
