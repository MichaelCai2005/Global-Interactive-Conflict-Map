# The whole site in one container: the frontend built to static files, served by the API
# process beside the API itself (backend/app/site.py). One origin keeps the sign-in cookie
# first-party and needs no CORS. backend/Dockerfile still builds the API on its own.

FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# CI type-checks; the image only needs the bundle.
RUN npx vite build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STATIC_DIR=/app/static
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend /frontend/dist ./static

EXPOSE 8000
# Hosts such as Render and Railway say which port to listen on in PORT. The proxy headers
# let the API see the visitor's address (for sign-in throttling) and that it's on HTTPS.
# Migrations run on start, which suits one instance; see backend/Dockerfile for more.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-true}\" = true ]; then alembic upgrade head; fi && uvicorn app.site:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
