FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY . .
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--no-dev", "eventmm", "markets", "--status", "open"]
