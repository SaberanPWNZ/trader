#!/bin/bash
# Live Trading Startup Script

echo "=========================================="
echo "🚀 STARTING LIVE TRADING ON MAINNET"
echo "⚠️  REAL MONEY - BE CAREFUL!"
echo "=========================================="
echo ""

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker compose down

# Rebuild containers
echo "🔨 Rebuilding containers..."
docker compose build

# Start live trading
echo "🚀 Starting live trading..."
docker compose up -d grid-live telegram-bot

# Show logs
echo ""
echo "📊 Showing live logs (Ctrl+C to exit)..."
echo "=========================================="
docker compose logs -f grid-live
