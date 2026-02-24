# Backtesting Framework

## Complete Backtester

```python
import pandas as pd
import numpy as np
from datetime import datetime

class Backtester:
    """
    Complete backtesting engine for strategy validation
    """
    
    def __init__(self, initial_capital=10000, commission=0.00007):
        self.initial_capital = initial_capital
        self.commission = commission  # ~$7 per lot round trip
        self.trades = []
        self.equity_curve = [initial_capital]
    
    def run(self, df, strategy, start_date=None, end_date=None):
        """
        Run backtest on historical data
        
        Args:
            df: DataFrame with OHLCV data
            strategy: Strategy instance
            start_date: Start date for backtest
            end_date: End date for backtest
        """
        
        # Filter date range
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]
        
        # Initialize
        position = None
        capital = self.initial_capital
        equity = [capital]
        
        # Run backtest
        for i in range(200, len(df)):  # Need history for indicators
            current_bar = df.iloc[i]
            historical = df.iloc[:i]
            
            # Get signal
            signal = strategy.check_entry(historical)
            
            # Execute trades
            if position is None and signal in ['BUY', 'SELL']:
                # Open position
                position = {
                    'direction': signal,
                    'entry_price': current_bar['close'],
                    'entry_date': current_bar.name,
                    'stop_loss': strategy.parameters.get('stop_loss_pct', 0.015),
                    'take_profit': strategy.parameters.get('take_profit_ratio', 3.0)
                }
            
            elif position:
                # Check exit conditions
                exit_signal = self.check_exit(position, current_bar, historical)
                
                if exit_signal:
                    # Close position
                    pnl = self.calculate_pnl(position, current_bar['close'])
                    capital += pnl
                    
                    self.trades.append({
                        'entry_date': position['entry_date'],
                        'exit_date': current_bar.name,
                        'direction': position['direction'],
                        'entry_price': position['entry_price'],
                        'exit_price': current_bar['close'],
                        'pnl': pnl,
                        'return_pct': (pnl / self.initial_capital) * 100,
                        'exit_reason': exit_signal
                    })
                    
                    position = None
            
            equity.append(capital)
        
        self.equity_curve = equity
        return self.generate_report()
    
    def check_exit(self, position, current_bar, historical):
        """Check if should exit position"""
        
        direction = position['direction']
        entry = position['entry_price']
        current = current_bar['close']
        sl_pct = position['stop_loss']
        tp_ratio = position['take_profit']
        
        if direction == 'BUY':
            # Stop loss hit
            if current <= entry * (1 - sl_pct):
                return 'STOP_LOSS'
            
            # Take profit hit
            if current >= entry * (1 + sl_pct * tp_ratio):
                return 'TAKE_PROFIT'
        
        else:  # SELL
            if current >= entry * (1 + sl_pct):
                return 'STOP_LOSS'
            
            if current <= entry * (1 - sl_pct * tp_ratio):
                return 'TAKE_PROFIT'
        
        return None
    
    def calculate_pnl(self, position, exit_price):
        """Calculate PnL for trade"""
        
        direction = position['direction']
        entry = position['entry_price']
        
        if direction == 'BUY':
            pnl = (exit_price - entry) / entry * self.initial_capital
        else:
            pnl = (entry - exit_price) / entry * self.initial_capital
        
        # Subtract commission
        pnl -= self.commission * self.initial_capital
        
        return pnl
    
    def generate_report(self):
        """Generate performance report"""
        
        if not self.trades:
            return {'error': 'No trades executed'}
        
        df = pd.DataFrame(self.trades)
        
        # Calculate metrics
        total_trades = len(df)
        winning_trades = len(df[df['pnl'] > 0])
        losing_trades = len(df[df['pnl'] <= 0])
        
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
        
        avg_win = df[df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = abs(df[df['pnl'] <= 0]['pnl'].mean()) if losing_trades > 0 else 0
        
        profit_factor = (avg_win * winning_trades) / (avg_loss * losing_trades) if losing_trades > 0 else float('inf')
        
        # Calculate returns
        total_return = (self.equity_curve[-1] - self.initial_capital) / self.initial_capital * 100
        annual_return = total_return  # Simplified
        
        # Max drawdown
        equity = pd.Series(self.equity_curve)
        running_max = equity.expanding().max()
        drawdown = (equity - running_max) / running_max * 100
        max_drawdown = drawdown.min()
        
        # Sharpe Ratio (simplified)
        returns = df['return_pct']
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'total_return_pct': round(total_return, 2),
            'annual_return_pct': round(annual_return, 2),
            'max_drawdown_pct': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe, 2),
            'final_capital': round(self.equity_curve[-1], 2),
            'trades': df.to_dict('records')
        }
```

---

## Usage Example

```python
# Load historical data
df = pd.read_csv('eurusd_h1.csv', parse_dates=True, index_col='date')

# Create strategy
strategy = EMATrendStrategy()

# Run backtest
backtester = Backtester(initial_capital=10000)
results = backtester.run(df, strategy, start_date='2023-01-01', end_date='2024-12-31')

# Print results
print(f"Total Trades: {results['total_trades']}")
print(f"Win Rate: {results['win_rate']}%")
print(f"Total Return: {results['total_return_pct']}%")
print(f"Max Drawdown: {results['max_drawdown_pct']}%")
print(f"Sharpe Ratio: {results['sharpe_ratio']}")
print(f"Profit Factor: {results['profit_factor']}")
```

---

## Performance Metrics Explained

| Metric | Good | Bad | Description |
|--------|------|-----|-------------|
| **Win Rate** | >50% | <40% | Percentage of profitable trades |
| **Profit Factor** | >1.5 | <1.0 | Ratio of gross profit to gross loss |
| **Sharpe Ratio** | >1.0 | <0.5 | Risk-adjusted return |
| **Max Drawdown** | <15% | >30% | Largest peak-to-trough decline |
| **Total Return** | Varies | Negative | Overall return on investment |

---

## Validation Checklist

Before going live, strategy must pass:

- [ ] Win rate > 45%
- [ ] Profit factor > 1.5
- [ ] Max drawdown < 20%
- [ ] Sharpe ratio > 0.8
- [ ] Minimum 100 trades in backtest
- [ ] Tested on out-of-sample data
- [ ] Passed forward testing (paper trading)

---

## Optimization

```python
def optimize_parameters(df, strategy_class, param_grid):
    """
    Grid search for optimal parameters
    """
    
    best_params = None
    best_score = -float('inf')
    results = []
    
    # Generate all parameter combinations
    for params in generate_param_combinations(param_grid):
        strategy = strategy_class(**params)
        backtester = Backtester()
        result = backtester.run(df, strategy)
        
        score = result['sharpe_ratio'] * result['win_rate'] / 100
        
        results.append({
            'params': params,
            'score': score,
            'result': result
        })
        
        if score > best_score:
            best_score = score
            best_params = params
    
    return best_params, sorted(results, key=lambda x: x['score'], reverse=True)[:10]
```
