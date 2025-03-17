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
	
validate-setup-helm:
	test/validate_setup_helm.sh

# Adjust which paths we lint
LINT_PATHS="app test"

lint: install-lint  ## Run linter to check formatting and style
	./code-quality/lint ${LINT_PATHS}

format: install-lint  ## Run standard python formatting
	./code-quality/format ${LINT_PATHS}

# You can add any args to your helm install by adding `HELM_ARGS="<your args>".
# For example, `make helm-install HELM_ARGS="--set groundlightApiToken=api_2hRQVo...."` to set your token.
HELM_ARGS =

# Note that the namespace we specify here is the namespace where we keep the helm history (always "default") not
# the namespace where the resources are deployed. The namespace where the resources are deployed is 
# specified in the values.yaml file (default is "edge").
helm-install:
	helm upgrade -i -n default ${HELM_ARGS} edge-endpoint deploy/helm/groundlight-edge-endpoint 

helm-package:
	helm package deploy/helm/groundlight-edge-endpoint

# TODO: update this with inference server support
helm-local:
	# We want k3s to error out if the :dev image hasn't been pushed to it already, so we set imagePullPolicy=Never
	helm upgrade -i ${HELM_ARGS} --set=edgeEndpointTag=dev --set=imagePullPolicy=Never edge-endpoint deploy/helm/groundlight-edge-endpoint 
	# Restart any deployments so that they pick up the new image
	kubectl rollout restart deployment -n $$(helm get values edge-endpoint --all -o json | jq -r '.namespace') edge-endpoint
