# Build arg lets the operator switch base-image registry — useful in regions
# where Docker Hub is throttled (e.g. mainland China). Examples:
#   --build-arg REGISTRY=docker.m.daocloud.io/
#   --build-arg REGISTRY=registry.cn-hangzhou.aliyuncs.com/
# Default empty = Docker Hub.
ARG REGISTRY=

# --- builder ---
FROM ${REGISTRY}python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Every wheel we need (numpy, pandas, scipy, scikit-learn, pyarrow, etc.)
# ships a prebuilt manylinux wheel — no C toolchain required.
COPY backend/requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt

# --- runtime ---
FROM ${REGISTRY}python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# Create non-root user for the API process. The sandbox subprocess still runs
# as this same user but with --network blocked at the container level + the
# AST whitelist enforced at the language level.
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

COPY --from=builder /install /usr/local

COPY backend/app ./app

RUN mkdir -p /data/db /data/uploads && chown -R app:app /app /data

# Entrypoint fixes /data ownership at runtime, then drops privileges. Needs
# to stay root-runnable, hence no `USER app` here.
COPY deploy/backend-entrypoint.sh /usr/local/bin/backend-entrypoint
RUN chmod +x /usr/local/bin/backend-entrypoint

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/backend-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
