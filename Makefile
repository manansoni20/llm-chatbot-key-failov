.PHONY: up down build logs ps restart test-backend build-frontend

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

restart:
	docker compose restart

test-backend:
	cd backend && .venv/bin/pytest -v

build-frontend:
	cd frontend && npm run build
