.PHONY: help static format clean

help:
	@echo "Available targets:"
	@echo "  help   - print this text"
	@echo "  static - run static code analysis"
	@echo "  format - auto format source code"
	@echo "  clean  - remove cache, venv and artifacts"

static:
	uv run ruff check src
	uv run ruff format --check src
	uv run ty check src

format:
	uv run ruff check --fix src
	uv run ruff format src

clean:
	rm -rf .venv .ruff_cache
	find . -type d -name '__pycache__' -exec rm -rf {} +
