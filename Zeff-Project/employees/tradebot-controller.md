# TradeBot Controller

## Live Trading vs Paper Trading

The bot supports both modes:
- **Paper Trading:** Simulated trades (no real money)
- **Live Trading:** Real trades via IC Markets API

## Current Status

### Paper Trading (Active Now)
Paper trading is ready and can start immediately. It simulates trades using:
- Real-time price data (fetched from demo feed)
- Realistic spread/commission
- Full risk management

### Live Trading (Pending API Fix)
The IC Markets API endpoint needs verification. Working on getting the correct URL.

## Quick Start - Paper Trading

```python
from icmarkets_connector import SimulatedTrader

# Initialize with $10,000 paper balance
trader = SimulatedTrader(initial_balance=10000)

# Example trade
trader.open_position(
    symbol='EURUSD',
    side='buy',
    volume=0.1,  # 0.1 lots
    entry_price=1.0850,
    stop_loss=1.0800,  # 50 pips stop
    take_profit=1.1000  # 150 pips target (3:1)
)

# Update with current prices
prices = {'EURUSD': 1.0860}
trader.update_prices(prices)

# Check stats
stats = trader.get_stats()
print(stats)
```

## Next Steps

1. Start paper trading immediately
2. Test strategies for 1-3 months
3. Verify live API connection
4. Go live with small capital

---

**Status:** 🟡 Paper Trading Ready | 🔴 Live Trading Pending API Fix
