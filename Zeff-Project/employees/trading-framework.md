# Trading Bot Framework

## Architecture

```
TradeBot (#003)
    │
    ├── Strategy Engine
    │   ├── Trend Following
    │   ├── Mean Reversion
    │   ├── Breakout
    │   └── Custom
    │
    ├── Risk Manager
    │   ├── Position Sizing
    │   ├── Stop Loss
    │   ├── Take Profit
    │   └── Daily Limits
    │
    ├── News Module
    │   ├── Economic Calendar
    │   ├── Sentiment Analysis
    │   └── Event Filters
    │
    ├── Backtester
    │   ├── Historical Data
    │   ├── Strategy Optimization
    │   └── Performance Metrics
    │
    └── Broker Adapter (IC Markets cTrader)
        ├── Execute Orders
        ├── Get Prices
        └── Account Info
```

## Implemented Strategies

### 1. Trend Following (EMA Crossover)

**Logic:**
- Buy when 50 EMA crosses above 200 EMA
- Sell when 50 EMA crosses below 200 EMA
- Confirmed by RSI (not overbought/oversold)

**Parameters:**
- Fast EMA: 50
- Slow EMA: 200
- RSI Period: 14
- RSI Oversold: 30
- RSI Overbought: 70

### 2. Mean Reversion (RSI)

**Logic:**
- Buy when RSI < 30 (oversold)
- Sell when RSI > 70 (overbought)
- Exit when RSI returns to 50

**Parameters:**
- RSI Period: 14
- Oversold Level: 30
- Overbought Level: 70

### 3. Breakout Strategy

**Logic:**
- Buy on new 20-day high
- Sell on new 20-day low
- Confirmation via volume

**Parameters:**
- Lookback Period: 20
- Volume Multiplier: 1.5

## Risk Management Rules

### Position Sizing

```
Position Size = (Account Balance × Risk%) ÷ Stop Loss Pips
```

- Risk per trade: 1-2% of account
- Default: 1%

### Stop Loss

- Hard stop: 1.5-2% from entry
- Trailing stop: Move to break-even after 1% profit

### Take Profit

- Minimum 2:1 risk:reward
- Default 3:1

### Daily Limits

- Max daily loss: 5% → Stop trading for day
- Max trades per day: 5
- Max open positions: 3

## News Impact

### High-Impact Events

- NFP (Non-Farm Payrolls)
- FOMC Meetings
- GDP Releases
- Interest Rate Decisions
- Central Bank Speeches

### Trade Rules During News

- Close all positions 30 min before major news
- No new entries 30 min before/after
- Optional: Trade breakout after volatility settles

## Backtesting

### Metrics Tracked

- Total Return
- Sharpe Ratio
- Max Drawdown
- Win Rate
- Profit Factor
- Average Trade Duration

### Testing Period

- Minimum: 6 months historical data
- Ideal: 2+ years
- Out-of-sample testing: 20% of data

## Execution Flow

```
1. Fetch current prices
2. Run strategy checks
3. Generate signals
4. Apply risk filters
5. Check news filter
6. Execute (if all pass)
7. Monitor positions
8. Apply exit rules
9. Log trade
10. Update metrics
```
