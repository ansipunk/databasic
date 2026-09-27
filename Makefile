.PHONY: help static format test clean

help:
	@echo "Available targets:"
	@echo "  help   - print this text"
	@echo "  static - run static code analysis"
	@echo "  format - auto format source code"
	@echo "  test   - run project tests"
	@echo "  clean  - remove cache, venv and artifacts"

static:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run ty check src

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests

test:
	uv run pytest

clean:
	rm -rf .venv .ruff_cache .pytest_cache .coverage htmlcov
	find . -type d -name '__pycache__' -exec rm -rf {} +
