#!/bin/bash
# TradeBot Launcher
# Run this from your local machine

echo "🤖 Starting TradeBot..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 required"
    exit 1
fi

# Install dependencies
pip install requests pandas numpy --quiet 2>/dev/null

echo "📡 Connecting to IC Markets..."
python3 paper-trading-runner.py
