
install: 
	poetry install 

install-lint:  ## Only install the linter dependencies
	poetry install --only lint

install-pre-commit: install  ## Install pre-commit hooks. Requires .pre-commit-config.yaml at the root
	poetry run pre-commit install

test: install  ## Run unit tests in verbose mode 
	poetry run pytest -vs 

# Adjust which paths we lint
LINT_PATHS="app test"

lint: install-lint  ## Run linter to check formatting and style
	./code-quality/lint ${LINT_PATHS}

format: install-lint  ## Run standard python formatting
	./code-quality/format ${LINT_PATHS}


# OpenSSL related commands
generate-tls-certs:
	mkdir -p certificates/ssl
	./certificates/generate_tls_cert.sh 
	sudo chmod 644 certificates/ssl/* 
