FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev \
    && mkdir -p /data \
    && command -v setpriv

CMD ["sh", "-c", "chown 65532:65532 /data && exec setpriv --reuid=65532 --regid=65532 --clear-groups plane-mcp http"]
