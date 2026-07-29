DATA_CONTROL_DIR := services/data-control-service

.PHONY: data-control-lint data-control-test data-control-test-postgresql data-control-migrate

data-control-lint:
	cd $(DATA_CONTROL_DIR) && ruff check . && ruff format --check . && mypy src

data-control-test:
	cd $(DATA_CONTROL_DIR) && pytest -q

data-control-test-postgresql:
	cd $(DATA_CONTROL_DIR) && pytest -m postgresql -q

data-control-migrate:
	cd $(DATA_CONTROL_DIR) && alembic upgrade head && alembic current
