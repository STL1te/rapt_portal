FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY *.py ./

# DB lives on a volume; secrets come from env_file at runtime
ENV DATABASE_URL=sqlite:////data/rapt.db
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
