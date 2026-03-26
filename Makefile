.PHONY: up down logs test test-fast test-e2e test-api test-unit

PYTEST_WORKERS ?= 4
PYTEST_PARALLEL = -n $(PYTEST_WORKERS)

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f app

test:
	docker compose exec app pytest $(PYTEST_PARALLEL) -vv

test-fast:
	docker compose exec app pytest $(PYTEST_PARALLEL) -vv -m "not e2e"

test-e2e:
	docker compose exec app pytest $(PYTEST_PARALLEL) -vv -s -m e2e

test-api:
	docker compose exec app pytest $(PYTEST_PARALLEL) -vv tests/test_api.py

test-unit:
	docker compose exec app pytest $(PYTEST_PARALLEL) -vv tests/test_unit_rules.py
