FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000
# Hosts such as Render and Railway say which port to listen on in PORT. Migrations run on
# start, which suits one instance. Before running more, set RUN_MIGRATIONS=false and run
# `alembic upgrade head` as the host's release (pre-deploy) step, so instances don't race.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-true}\" = true ]; then alembic upgrade head; fi && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
