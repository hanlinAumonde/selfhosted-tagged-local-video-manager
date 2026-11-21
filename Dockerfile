# use official uv image with Python 3.12 and Debian Bookworm slim
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# install ffmpeg for thumbnail generation
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# setup non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app

# enable bytecode compilation (improve startup speed)
ENV UV_COMPILE_BYTECODE=1

# use copy mode instead of link (because of mounted volumes)
ENV UV_LINK_MODE=copy

# copy dependency files first (leverage Docker layer caching)
COPY pyproject.toml uv.lock ./

# install dependencies (without installing the project itself)
# --locked: install exactly what uv.lock records, the versions CI tested, and fail
# rather than re-resolve when it no longer matches pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY main.py .
COPY config.yaml .
COPY src/ ./src/

# add virtual environment's bin directory to PATH
ENV PATH="/app/.venv/bin:$PATH"

# reset entrypoint to not call uv
ENTRYPOINT []

# run as non-root user
USER nonroot

EXPOSE 12000

CMD ["uvicorn", "src.app:create_app", "--host", "0.0.0.0", "--port", "12000", "--factory"]