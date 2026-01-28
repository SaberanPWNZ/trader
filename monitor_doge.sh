#!/bin/bash
# Monitor DOGE Grid Trading - Aggressive Strategy

echo "🚀 АГРЕСИВНА СТРАТЕГІЯ - DOGE GRID"
echo "════════════════════════════════════"
echo "Параметри:"
echo "  • 10 грідів × 1 символ (DOGE/USDT)"
echo "  • $50 на позицію"
echo "  • ~3% спред між грідами"
echo "  • Цільовий прибуток: $45/день"
echo ""

if [ -f data/grid_trades.csv ]; then
    trades=$(wc -l < data/grid_trades.csv)
    trades=$((trades - 1))
    echo "📊 Всього трейдів: $trades"
    
    if [ $trades -gt 0 ]; then
        echo ""
        echo "📈 Останні 5 трейдів:"
        tail -5 data/grid_trades.csv | column -t -s,
        
        echo ""
        echo "💰 Детальний аналіз:"
        python3 analyze_grid.py
    else
        echo "⏳ Чекаємо на перші трейди..."
    fi
else
    echo "❌ Файл даних не знайдено"
fi

echo ""
echo "📝 Логи: tail -f logs/grid_aggressive.log"
echo "🔄 Оновити: ./monitor_doge.sh"
