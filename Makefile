.PHONY: up down logs test test-rebuild test-fast test-e2e test-api test-unit

PYTEST_WORKERS ?= 4
PYTEST_PARALLEL = -n $(PYTEST_WORKERS)
PYTEST_DURATIONS ?= 20
PYTEST_DURATIONS_MIN ?= 1.0
PYTEST_BASE = -q --durations=$(PYTEST_DURATIONS) --durations-min=$(PYTEST_DURATIONS_MIN)

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f app

test:
	docker compose exec app pytest $(PYTEST_PARALLEL) $(PYTEST_BASE)

test-rebuild:
	docker compose down --remove-orphans
	docker compose up --build -d --force-recreate --wait
	docker compose run --rm app pytest $(PYTEST_PARALLEL) $(PYTEST_BASE)

test-fast:
	docker compose exec app pytest $(PYTEST_PARALLEL) $(PYTEST_BASE) -m "not e2e"

test-e2e:
	docker compose exec app pytest $(PYTEST_PARALLEL) $(PYTEST_BASE) -s -m e2e

test-api:
	docker compose exec app pytest $(PYTEST_PARALLEL) $(PYTEST_BASE) tests/test_api.py

test-unit:
	docker compose exec app pytest $(PYTEST_PARALLEL) $(PYTEST_BASE) tests/test_unit_rules.py
