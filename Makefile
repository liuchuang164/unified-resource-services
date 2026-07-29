DATA_CONTROL_DIR := services/data-control-service

.PHONY: data-control-lint data-control-test data-control-test-postgresql data-control-migrate data-control-migrate-control data-control-migrate-target data-control-migrate-current

data-control-lint:
	cd $(DATA_CONTROL_DIR) && ruff check . && ruff format --check . && mypy src

data-control-test:
	cd $(DATA_CONTROL_DIR) && pytest -q

data-control-test-postgresql:
	cd $(DATA_CONTROL_DIR) && pytest -m postgresql -q

data-control-migrate:
	cd $(DATA_CONTROL_DIR) && alembic -c alembic-control.ini upgrade head && alembic -c alembic-target.ini upgrade head

data-control-migrate-control:
	cd $(DATA_CONTROL_DIR) && alembic -c alembic-control.ini upgrade head

data-control-migrate-target:
	cd $(DATA_CONTROL_DIR) && alembic -c alembic-target.ini upgrade head

data-control-migrate-current:
	cd $(DATA_CONTROL_DIR) && alembic -c alembic-control.ini current && alembic -c alembic-target.ini current
