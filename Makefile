.PHONY: up down logs test test-fast test-e2e test-api test-unit

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f app

test:
	docker compose exec app pytest -vv

test-fast:
	docker compose exec app pytest -vv -m "not e2e"

test-e2e:
	docker compose exec app pytest -vv -s -m e2e

test-api:
	docker compose exec app pytest -vv tests/test_api.py

test-unit:
	docker compose exec app pytest -vv tests/test_unit_rules.py
