#!/bin/bash

set -e

PROJECT_NAME="crypto-trading-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🤖 $PROJECT_NAME - Self-Learning Trading System"
echo "=================================================="
echo ""

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "⚠️  .env file not found. Creating template..."
    cat > "$SCRIPT_DIR/.env.example" << 'EOF'
# Binance API
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
EOF
    echo "✅ Created .env.example. Please fill in your credentials:"
    echo ""
    echo "  export BINANCE_API_KEY=your_key"
    echo "  export BINANCE_API_SECRET=your_secret"
    echo "  export TELEGRAM_BOT_TOKEN=your_token"
    echo "  export TELEGRAM_CHAT_ID=your_chat_id"
    echo ""
    echo "Then run: $0"
    exit 1
fi

echo "📋 Environment variables:"
echo "  - BINANCE_API_KEY: ${BINANCE_API_KEY:0:10}***"
echo "  - TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:0:10}***"
echo ""

echo "🏗️  Building Docker image..."
docker compose build

echo ""
echo "🚀 Starting services:"
echo "  - trading-bot (main service)"
echo "  - scheduler (self-learning)"
echo "  - telegram-bot (interactive control)"
echo ""

docker compose up -d

echo ""
echo "✅ All services started!"
echo ""
echo "📊 Service URLs and logs:"
echo "  - Trading Bot logs:     docker compose logs trading-bot -f"
echo "  - Scheduler logs:       docker compose logs scheduler -f"
echo "  - Telegram Bot logs:    docker compose logs telegram-bot -f"
echo "  - All logs:             docker compose logs -f"
echo ""
echo "🛑 To stop services:      docker compose down"
echo "🔄 To restart services:   docker compose restart"
echo ""
echo "🤖 Available commands:"
echo "  docker compose run --rm trading-bot python main.py force-train BTC/USDT"
echo "  docker compose run --rm trading-bot python main.py backtest --symbol BTC/USDT"
echo ""
