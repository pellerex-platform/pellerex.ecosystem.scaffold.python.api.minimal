# Multi-stage build (P6 / PY-D15). Base is python:3.12-slim (Debian/glibc), NOT alpine —
# musl has no prebuilt wheels for pydantic-core/etc, so alpine would compile from source
# (slow, fragile, bloated). slim gets prebuilt wheels.

# ---- Builder: resolve pinned deps into an isolated venv ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt ./
RUN python -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir -r requirements.txt

# ---- Runtime: clean slim image, copy only the venv + app (no build toolchain) ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production

# Non-root user (UID/GID 1001 — matches the Helm securityContext).
RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser --no-create-home appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY config.*.json ./

USER appuser

# uvicorn binds the <port-number> token (PY-D5), provisioned to the platform port.
EXPOSE <port-number>

# HEALTHCHECK hits the root startup path (no /api), using only the stdlib (no extra dep).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:<port-number>/health/startup', timeout=3).status==200 else 1)"]

# One uvicorn process per pod; scale via K8s replicas (P13 / PY-D14). uvicorn[standard]
# pulls uvloop + httptools for throughput, and drains in-flight requests on SIGTERM (P10).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "<port-number>"]
