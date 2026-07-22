# Debate-GPT — top-level Makefile
#
# Common developer entry points. All targets run on Windows (Git Bash)
# and POSIX shells; `make` must be installed (on Windows: via Git for
# Windows or `choco install make`).

PYTHON ?= python
SRC := src/debate_gpt

.PHONY: test test-unit test-integration cov lint clean help

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

test:  ## Run the full test suite with coverage (Day 5 default).
	$(PYTHON) -m pytest \
		--cov=$(SRC) \
		--cov-report=term-missing \
		tests/

test-unit:  ## Run unit tests only (skip integration).
	$(PYTHON) -m pytest tests/unit/ -m "not integration"

test-integration:  ## Run integration tests only.
	$(PYTHON) -m pytest tests/integration/

cov: test  ## Alias for `make test` — coverage report.

lint:  ## Reserved for Day 7 (ruff/mypy); no-op for now.
	@echo "lint: not yet configured (Day 7)"

clean:  ## Remove pytest + coverage artifacts.
	rm -rf .pytest_cache .coverage htmlcov tests/__pycache__ \
		tests/*/__pycache__
