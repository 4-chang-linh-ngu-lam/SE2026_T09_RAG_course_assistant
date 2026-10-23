FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CORE_LOAD_RUNTIME=image-linux-filesystem PYTHONPATH=/srv
WORKDIR /srv
COPY pyproject.toml ./
RUN python -c "import subprocess,tomllib; p=tomllib.load(open('pyproject.toml','rb'))['project']; subprocess.check_call(['python','-m','pip','install','--no-cache-dir',*p['dependencies'],*p['optional-dependencies']['dev']])"
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests/performance ./tests/performance
RUN groupadd --gid 10001 core && useradd --uid 10001 --gid core --no-create-home core
USER core
ENTRYPOINT ["python", "tests/performance/class_list_load.py"]
