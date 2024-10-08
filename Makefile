.PHONY: install install-lint install-pre-commit test test-with-docker lint format

install:
	poetry install --no-root

install-lint:  ## Only install the linter dependencies
	poetry install --only lint

install-pre-commit: install  ## Install pre-commit hooks. Requires .pre-commit-config.yaml at the root
	poetry run pre-commit install

test: install  ## Run unit tests in verbose mode
	. test/setup_plain_test_env.sh && poetry run pytest --cov=app --cov-report=lcov -vs -k "not test_motdet and not _live"

test-with-docker: install  # Run tests that require a live edge-endpoint server and valid GL API token
	. test/setup_plain_test_env.sh && poetry run pytest -vs -k "_live"
	# TODO: Refactor so the config is loaded by the test
	. test/setup_motion_detection_test_env.sh && poetry run pytest -vs test/api/test_motdet.py

# Adjust which paths we lint
LINT_PATHS="app test"

lint: install-lint  ## Run linter to check formatting and style
	./code-quality/lint ${LINT_PATHS}

format: install-lint  ## Run standard python formatting
	./code-quality/format ${LINT_PATHS}
