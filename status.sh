#!/bin/bash
# Quick status check

echo "📊 TRADING BOT STATUS"
echo "=========================================="
docker compose ps
echo ""
echo "📈 Recent Activity:"
docker compose logs --tail=20 grid-live 2>/dev/null || echo "Container not running"
