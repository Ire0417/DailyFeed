.PHONY: help up down build logs test lint fmt clean migrate

help:
	@echo "DailyFeed - Makefile Commands"
	@echo ""
	@echo "  up        - Start all services (docker-compose up -d)"
	@echo "  down      - Stop all services (docker-compose down)"
	@echo "  restart   - Restart all services"
	@echo "  build     - Build all images"
	@echo "  logs      - Tail logs from all services"
	@echo "  api-logs  - Tail logs from API service"
	@echo ""
	@echo "  install   - Install backend + frontend dependencies"
	@echo "  test      - Run backend tests"
	@echo "  lint      - Run linting"
	@echo "  fmt       - Run code formatter"
	@echo ""
	@echo "  migrate   - Run alembic migrations"
	@echo "  clean     - Remove build artifacts and containers"

up:
	docker-compose up -d

down:
	docker-compose down

restart:
	docker-compose restart

build:
	docker-compose build

logs:
	docker-compose logs -f --tail=100

api-logs:
	docker-compose logs -f --tail=100 backend-api

install:
	cd backend && pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install

test:
	cd backend && pytest -v

lint:
	cd backend && flake8 .
	cd frontend && npm run lint

fmt:
	cd backend && black .
	cd frontend && npm run format

migrate:
	cd backend && alembic upgrade head

clean:
	docker-compose down -v
	rm -rf backend/__pycache__ backend/**/__pycache__
	rm -rf frontend/dist frontend/node_modules
