.PHONY: help build run stop restart logs logs-scheduler logs-bot logs-grid logs-health logs-all train backtest clean postgres-setup postgres-logs migrate-db health-check grid-start grid-stop grid-logs grid-restart

help:
	@echo "🤖 Crypto AI Trading Bot - Commands"
	@echo "===================================="
	@echo ""
	@echo "📦 Docker Services:"
	@echo "  make run              - Start all services"
	@echo "  make build            - Build Docker image"
	@echo "  make stop             - Stop all services"
	@echo "  make restart          - Restart all services"
	@echo ""
	@echo "📊 Logs:"
	@echo "  make logs             - Follow trading bot logs"
	@echo "  make logs-scheduler   - Follow scheduler logs"
	@echo "  make logs-bot         - Follow Telegram bot logs"
	@echo "  make logs-grid        - Follow grid trading logs"
	@echo "  make logs-health      - Follow health API logs"
	@echo "  make logs-all         - Follow all logs"
	@echo ""
	@echo "🗄️  PostgreSQL:"
	@echo "  make postgres-setup   - Start PostgreSQL only"
	@echo "  make postgres-logs    - Follow PostgreSQL logs"
	@echo "  make migrate-db       - Migrate SQLite to PostgreSQL"
	@echo ""
	@echo "🏥 Health Checks:"
	@echo "  make health-check     - Check service health"
	@echo ""
	@echo "📊 Grid Trading:"
	@echo "  make grid-start       - Start grid trading"
	@echo "  make grid-stop        - Stop grid trading"
	@echo "  make grid-logs        - Follow grid trading logs"
	@echo "  make grid-restart     - Restart grid trading"
	@echo ""
	@echo "🤖 Training & Backtesting:"
	@echo "  make train SYMBOL=BTC - Force train model"
	@echo "  make backtest SYMBOL=BTC - Run backtest"
	@echo ""
	@echo "🗑️  Cleanup:"
	@echo "  make clean            - Remove all containers and data"
	@echo ""

build:
	@echo "🏗️  Building Docker image..."
	docker compose build

run: build
	@echo "🚀 Starting all services..."
	docker compose up -d
	@echo ""
	@echo "✅ Services started!"
	@echo ""
	@echo "📊 Logs:              make logs-all"
	@echo "🛑 Stop services:     make stop"

stop:
	@echo "🛑 Stopping services..."
	docker compose down

restart:
	@echo "🔄 Restarting services..."
	docker compose restart

logs:
	docker compose logs -f trading-bot

logs-scheduler:
	docker compose logs -f scheduler

logs-bot:
	docker compose logs -f telegram-bot

logs-grid:
	docker compose logs -f grid-trading

logs-health:
	docker compose logs -f health-api

logs-all:
	docker compose logs -f

postgres-setup:
	@echo "🐘 Starting PostgreSQL..."
	docker compose up -d postgres
	@echo "✅ PostgreSQL started"
	@echo "📊 Logs: make postgres-logs"

postgres-logs:
	docker compose logs -f postgres

migrate-db:
	@echo "📦 Migrating SQLite to PostgreSQL..."
	@if [ ! -f "data/learning.db" ]; then \
		echo "❌ Error: SQLite database not found at data/learning.db"; \
		exit 1; \
	fi
	docker compose up -d postgres
	@echo "⏳ Waiting for PostgreSQL to be ready..."
	@sleep 5
	docker compose run --rm trading-bot python scripts/migrate_to_postgres.py
	@echo "✅ Migration complete!"

health-check:
	@echo "🏥 Checking service health..."
	@curl -s http://localhost:8000/health | python -m json.tool || echo "❌ Health API not responding"
	@echo ""
	@curl -s http://localhost:8000/health/db | python -m json.tool || echo "❌ Database health check failed"

grid-start:
	@echo "📊 Starting grid trading..."
	docker compose up -d grid-trading
	@echo "✅ Grid trading started"
	@echo "📊 Logs: make grid-logs"

grid-stop:
	@echo "🛑 Stopping grid trading..."
	docker compose stop grid-trading

grid-logs:
	docker compose logs -f grid-trading

grid-restart:
	@echo "🔄 Restarting grid trading..."
	docker compose restart grid-trading

train:
	@SYMBOL=$${SYMBOL:-BTC/USDT}; \
	echo "🤖 Training model for $$SYMBOL..."; \
	docker compose run --rm trading-bot python main.py force-train $$SYMBOL

backtest:
	@SYMBOL=$${SYMBOL:-BTC/USDT}; \
	echo "📊 Running backtest for $$SYMBOL..."; \
	docker compose run --rm trading-bot python main.py backtest --symbol $$SYMBOL

clean:
	@echo "🗑️  Cleaning up..."
	docker compose down -v
	rm -rf data/learning.db logs/* models/*
	@echo "✅ Cleanup complete"
