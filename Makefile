up:
	docker compose up --build

up-d:
	docker compose up --build -d

down:
	docker compose down

restart:
	docker compose down && docker compose up --build

logs:
	docker compose logs -f

ps:
	docker compose ps

api-shell:
	docker compose exec api sh

ai-shell:
	docker compose exec ai sh

runner-shell:
	docker compose exec runner sh

web-shell:
	docker compose exec web sh

db-shell:
	docker compose exec postgres psql -U postgres -d runbook_platform

migrate:
	docker compose exec api python manage.py migrate

makemigrations:
	docker compose exec api python manage.py makemigrations

bootstrap:
	docker compose up --build -d
	docker compose exec api python manage.py migrate

start-db:
	docker compose start postgres

stop-db:
	docker compose stop postgres

start-api:
	docker compose start api

stop-api:
	docker compose stop api

start-web:
	docker compose start web

stop-web:
	docker compose stop web

start-runner:
	docker compose start runner

stop-runner:
	docker compose stop runner

start-ai:
	docker compose start ai

stop-ai:
	docker compose stop ai