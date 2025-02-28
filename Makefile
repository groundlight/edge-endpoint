.PHONY: install install-lint install-pre-commit test test-with-docker test-all lint format
SHELL := /bin/bash

install:
	poetry install --no-root

install-lint:  ## Only install the linter dependencies
	poetry install --only lint

install-pre-commit: install  ## Install pre-commit hooks. Requires .pre-commit-config.yaml at the root
	poetry run pre-commit install

test: install  ## Run unit tests in verbose mode
	. test/setup_plain_test_env.sh && poetry run pytest --cov=app --cov-report=lcov -vs -k "not _live"

test-with-docker: install  ## Run tests that require a live edge-endpoint server and valid GL API token
	. test/setup_plain_test_env.sh && poetry run pytest -vs -k "_live"

test-all: test test-with-docker  ## Run all tests in one make command
	@echo "All tests completed."

test-with-k3s:
	. test/integration/setup_and_run_tests.sh

validate-setup-ee:
	test/validate_setup_ee.sh
	
# Adjust which paths we lint
LINT_PATHS="app test"

lint: install-lint  ## Run linter to check formatting and style
	./code-quality/lint ${LINT_PATHS}

format: install-lint  ## Run standard python formatting
	./code-quality/format ${LINT_PATHS}
