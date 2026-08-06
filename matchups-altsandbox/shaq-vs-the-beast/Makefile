.PHONY: install test fixtures lint typecheck

install:
	uv pip install -e ".[dev,api]"

test:
	uv run pytest tests/ -v

fixtures:
	uv run python -m thebeast.data fetch-fixtures --seasons 2021 2022 2023 2024

lint:
	uv run ruff check thebeast/ tests/

typecheck:
	uv run mypy thebeast/
