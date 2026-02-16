#!/bin/bash
# View live trading logs

echo "📊 LIVE TRADING LOGS"
echo "=========================================="
echo "Press Ctrl+C to exit"
echo ""

docker compose logs -f --tail=100 grid-live
