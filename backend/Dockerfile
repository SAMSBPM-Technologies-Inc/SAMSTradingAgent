# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System deps for C extensions (pandas, numpy, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# NOTE: do NOT append `|| echo ...` here. Shell precedence (`A && B || C`) makes
# the whole RUN exit 0 when requirements.txt itself fails, which silently ships
# an image missing its dependencies. A broken build must fail the build.
RUN pip install --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --no-create-home appuser

# Copy only installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source, scripts, and model artefacts
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY model/ ./model/

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# --loop asyncio is REQUIRED, not a preference.
# uvicorn[standard] installs uvloop and selects it by default, but ib_async /
# ib_insync rely on nest_asyncio for their synchronous call paths and
# nest_asyncio cannot patch a uvloop event loop. Running under uvloop makes
# every broker call that touches a sync helper raise at runtime.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "asyncio", \
     "--log-level", "info"]
