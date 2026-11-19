# R8 PRE-UAT H1-DIRECT (Owner source approval Gate A, 2026-11-19, path #101): ONE short-lived Cloud Run
# Mock/TEST image serving the built frontend and the API on the same origin.
#
# Build from the repository root (or a verified export of the approved snapshot) with BuildKit:
#   docker build -f deploy/uat-r8/Dockerfile -t r8-uat-test:FINGERPRINT .
# The build context is filtered by deploy/uat-r8/Dockerfile.dockerignore (path #102), which only BuildKit
# reads (default in Docker 23+ and Cloud Build's docker builder with DOCKER_BUILDKIT=1); the guard steps below
# fail the build if a local .env / .venv / uploads directory slipped into the context anyway.
#
# The image carries NO configuration, secret, credential, Sheets id or tester email: every runtime
# variable (TEST_IDENTITY_PROXY, TEST_IAP_AUDIENCE, TEST_IDENTITY_MAP, ...) comes from the deployment.
# Without them the process starts in the ordinary default mode (no SPA, no hosted identity).
# Base images come from Google's Docker Hub mirror (Docker Hub rate-limits anonymous pulls).

FROM mirror.gcr.io/library/node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Fails the build if the context leaked a local environment file (needs BuildKit's Dockerfile.dockerignore).
RUN test ! -e .env && test ! -e .env.local
RUN npm run build

FROM mirror.gcr.io/library/python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=frontend /src/frontend/dist /app/static
# Build-time proof: no local venv / env file / uploads were copied, and the pinned repair catalogue
# (gitignored `data/`, so absent from git exports) is present and passes its in-code hash pins.
RUN test ! -e /app/backend/.venv && test ! -e /app/backend/.env && test ! -e /app/backend/data \
    && test -f /app/static/index.html \
    && python -c "from app.domain.repair_catalogue import load_catalogue; c = load_catalogue(); print('catalogue', c.source_sha256)"
# The only writable path: the local attachment store of the in-memory TEST session (lost on restart).
RUN mkdir -p /app/backend/data/uploads && chown -R app:app /app/backend/data
USER 10001:10001
EXPOSE 8080
# Exactly ONE worker process: the Mock data lives in that process's memory (Cloud Run max-instances=1).
# Shell form inside exec form so Cloud Run's $PORT is expanded; `exec` keeps uvicorn as PID 1 for signals.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-server-header"]
