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

notebooks-check:
	JUPYTER_CONFIG_DIR=/tmp/eventmm-jupyter uv run jupyter nbconvert --execute --to notebook --output-dir /tmp/eventmm-notebooks --ExecutePreprocessor.timeout=180 notebooks/*.ipynb

check: lint typecheck test notebooks-check

markets:
	uv run eventmm markets --status open --limit 20

notebook:
	uv run jupyter lab

clean-data:
	rm -rf data/raw/* data/processed/* data/duckdb/*
