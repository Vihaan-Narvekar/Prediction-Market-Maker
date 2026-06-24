install:
	uv sync

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest -q

markets:
	uv run eventmm markets --status open --limit 20

notebook:
	uv run jupyter lab

clean-data:
	rm -rf data/raw/* data/processed/* data/duckdb/*
