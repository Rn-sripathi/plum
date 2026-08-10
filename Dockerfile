# One image, one service: FastAPI serves the API and the built console from the
# same origin, so a deployment has one URL, no CORS to configure and no API
# address baked into the bundle.

# --- stage 1: build the console -----------------------------------------------
FROM node:20-alpine AS console
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty means "same origin as this page". api.js reads it with ?? so the empty
# string survives; || would fall through to localhost and the deployed app would
# call the reviewer's own machine.
ENV VITE_API_URL=""
RUN npm run build

# --- stage 2: runtime ---------------------------------------------------------
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv

# Dependencies first, so a code change does not reinstall the environment.
# Every wheel here is manylinux (psycopg[binary], pillow, numpy, pypdfium2),
# so the image needs no compiler and no libpq.
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ /app/backend/
# The policy and the test cases are read at runtime; the docs are served by the
# Docs view and searched by the assistant. REPO_ROOT resolves to /app.
COPY data/policy_terms.json data/test_cases.json /app/data/
COPY docs/ /app/docs/
COPY --from=console /web/dist /app/frontend/dist

# Writable state goes to the mounted volume, never into the image: uploaded
# documents so a decision's files survive a restart, and the embedded vector
# index so it is not rebuilt (and re-read for ~40s) on every boot.
ENV PLUM_UPLOAD_DIR=/state/uploads \
    PLUM_QDRANT_LOCAL_DIR=/state/qdrant \
    PLUM_DATABASE_FILE=/state/claims.db \
    PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
