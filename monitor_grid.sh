#!/bin/bash
echo "=== GRID TRADING MONITOR ==="
echo ""

cd /home/admin/projects/trader

while true; do
    clear
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║              GRID TRADING MONITOR - \$100                   ║"
    echo "╠════════════════════════════════════════════════════════════╣"
    echo "║ Time: $(date '+%Y-%m-%d %H:%M:%S')                              ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    
    echo "📊 RECENT GRID TRADES:"
    grep -E "Grid.*filled|Grid (BUY|SELL)" logs/trading_2026-01-26.log 2>/dev/null | tail -10
    echo ""
    
    echo "💰 PROFIT SUMMARY (Today):"
    TODAY_PROFIT=$(grep "Grid.*PnL" logs/trading_2026-01-26.log 2>/dev/null | grep -oP 'PnL: \$[\d.]+' | grep -oP '[\d.]+' | awk '{sum+=$1} END {printf "%.2f", sum}')
    TRADE_COUNT=$(grep -c "Grid.*PnL" logs/trading_2026-01-26.log 2>/dev/null || echo "0")
    echo "  Total PnL: \$${TODAY_PROFIT:-0.00}"
    echo "  Trades: ${TRADE_COUNT}"
    echo ""
    
    echo "🔄 PROCESS STATUS:"
    ps aux | grep "python main.py grid" | grep -v grep | awk '{print "  PID: "$2" | Balance: "$NF}'
    echo ""
    
    echo "📈 CURRENT PRICES:"
    curl -s "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT" 2>/dev/null | grep -oP '"price":"[^"]+' | cut -d'"' -f4 | xargs -I{} echo "  BTC/USDT: \${}"
    curl -s "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT" 2>/dev/null | grep -oP '"price":"[^"]+' | cut -d'"' -f4 | xargs -I{} echo "  ETH/USDT: \${}"
    echo ""
    
    echo "Press Ctrl+C to exit | Refreshing every 30s..."
    sleep 30
done
