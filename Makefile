.PHONY: help build run stop restart logs logs-scheduler logs-bot logs-all train backtest clean

help:
	@echo "🤖 Crypto AI Trading Bot - Commands"
	@echo "===================================="
	@echo ""
	@echo "make run              - Start all services (scheduler, bot, trading)"
	@echo "make build            - Build Docker image"
	@echo "make stop             - Stop all services"
	@echo "make restart          - Restart all services"
	@echo "make logs             - Follow main trading bot logs"
	@echo "make logs-scheduler   - Follow scheduler logs"
	@echo "make logs-bot         - Follow Telegram bot logs"
	@echo "make logs-all         - Follow all logs"
	@echo "make train SYMBOL=BTC - Force train model for symbol (default: BTC)"
	@echo "make backtest SYMBOL=BTC - Run backtest"
	@echo "make clean            - Remove all containers and data"
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

logs-all:
	docker compose logs -f

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
