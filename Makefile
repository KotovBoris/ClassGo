# ClassGo — частые команды. Запуск: make <цель>
.PHONY: help up down reset logs test test-fast doctor lint up-postgres down-postgres

help:
	@echo "ClassGo — доступные команды:"
	@echo "  make up              — поднять всё на SQLite (дефолт)"
	@echo "  make up-postgres     — поднять всё на PostgreSQL (тот же код)"
	@echo "  make down            — остановить"
	@echo "  make down-postgres   — остановить и удалить данные Postgres"
	@echo "  make reset         — сбросить демо-выезд к исходному состоянию"
	@echo "  make logs          — логи backend (поток)"
	@echo "  make test          — полный прогон (pytest+vitest+E2E+docker+UI)"
	@echo "  make test-fast     — быстрый прогон (без docker и UI)"
	@echo "  make doctor        — диагностика интеграции с MAX"

up:
	docker compose up -d --build
	@echo "БД: SQLite (файл в томе classgo-data)"
	@echo "mini-app: http://localhost:8080   Swagger: http://localhost:8080/docs"

up-postgres:
	DATABASE_URL="postgresql+psycopg2://classgo:classgo@db:5432/classgo" docker compose --profile postgres up -d --build
	@echo "БД: PostgreSQL (контейнер db, том classgo-pg)"

down:
	docker compose down

down-postgres:
	docker compose --profile postgres down

reset:
	curl -s -X POST http://localhost:8080/api/v1/admin/reset-demo | python3 -m json.tool || true

logs:
	docker compose logs -f backend

test:
	./scripts/run_all_tests.sh

test-fast:
	./scripts/run_all_tests.sh --fast

doctor:
	python3 scripts/doctor.py
