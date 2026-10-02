.PHONY: help static format test tox clean

help:
	@echo "Available targets:"
	@echo "  help   - print this text"
	@echo "  static - run static code analysis"
	@echo "  format - auto format source code"
	@echo "  test   - run project tests"
	@echo "  tox    - run tests across supported versions"
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

tox:
	uvx --with tox-uv tox

clean:
	rm -rf .venv .ruff_cache .pytest_cache .coverage .tox htmlcov
	find . -type d -name '__pycache__' -exec rm -rf {} +
