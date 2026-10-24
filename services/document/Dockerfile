FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10002 document && useradd --uid 10002 --gid document --no-create-home document \
    && mkdir -p /data/documents && chown document:document /data/documents
COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index /tmp/wheels/* && rm -rf /tmp/wheels
WORKDIR /srv
COPY migrations ./migrations
COPY alembic.ini ./
USER document
EXPOSE 8200
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200", "--no-proxy-headers"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir 'pytest>=8,<10' 'httpx>=0.27,<1' 'httpx2>=2,<3'
COPY tests ./tests
USER document
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM runtime AS production
