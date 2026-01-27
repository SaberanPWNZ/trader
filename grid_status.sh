#!/bin/bash
# Quick Grid Status Check

cd /home/admin/projects/trader
source .venv/bin/activate

echo "🔄 Grid Process Status:"
if ps aux | grep "python main.py grid" | grep -v grep > /dev/null; then
    ps aux | grep "python main.py grid" | grep -v grep | awk '{print "  ✅ Running | PID: "$2" | Balance: $"$NF}'
else
    echo "  ❌ Not running"
fi

echo ""
python analyze_grid.py

echo ""
echo "💡 Commands:"
echo "  Full analysis: python analyze_grid.py"
echo "  Live monitor:  ./monitor_grid.sh"
echo "  Restart grid:  kill <PID> && nohup python main.py grid --initial-balance 100 > logs/grid_output.log 2>&1 &"
