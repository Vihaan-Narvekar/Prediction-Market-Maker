FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN pip install uv && uv sync --frozen || uv sync

COPY . .

CMD ["uv", "run", "eventmm", "markets", "--status", "open"]
