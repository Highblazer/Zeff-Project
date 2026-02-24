# Risk Management Module

## Position Sizing Calculator

```python
class PositionSizer:
    """
    Calculate optimal position size based on risk parameters
    """
    
    def __init__(self, account_balance, risk_per_trade=0.01):
        self.account_balance = account_balance
        self.risk_per_trade = risk_per_trade  # 1-2% default
    
    def calculate_position_size(self, entry_price, stop_loss_price):
        """
        Position Size = (Account Balance × Risk%) ÷ Stop Loss Distance
        
        Example:
        - Account: $10,000
        - Risk: 1% = $100
        - Entry: 1.1000
        - Stop Loss: 1.0850 (150 pips)
        
        Position Size = $100 ÷ 150 = 0.66 lots
        """
        risk_amount = self.account_balance * self.risk_per_trade
        stop_loss_distance = abs(entry_price - stop_loss_price)
        
        # For forex, convert to lots
        # Assuming 100,000 units per standard lot
        position_size = risk_amount / stop_loss_distance
        
        return min(position_size, self.max_position_size())
    
    def max_position_size(self):
        """Never risk more than 5% of account"""
        return (self.account_balance * 0.05) / 100000
```

---

## Stop Loss Manager

```python
class StopLossManager:
    """
    Manage stop loss orders - both fixed and trailing
    """
    
    def __init__(self, initial_stop_pct=0.015, trailing_stop_pct=0.01):
        self.initial_stop_pct = initial_stop_pct  # 1.5% default
        self.trailing_stop_pct = trailing_stop_pct  # 1% trailing
    
    def set_initial_stop(self, entry_price, direction):
        """Set initial stop loss"""
        if direction == 'BUY':
            return entry_price * (1 - self.initial_stop_pct)
        else:
            return entry_price * (1 + self.initial_stop_pct)
    
    def update_trailing_stop(self, current_price, entry_price, current_stop, direction):
        """
        Update trailing stop as price moves in favorable direction
        
        Trail at break-even once price is 1% in profit
        """
        profit_pct = (current_price - entry_price) / entry_price
        
        if direction == 'BUY':
            if profit_pct >= self.trailing_stop_pct:
                # Move stop to break-even + small buffer
                new_stop = entry_price * 1.001
                return max(new_stop, current_stop)
        else:
            if profit_pct >= self.trailing_stop_pct:
                new_stop = entry_price * 0.999
                return min(new_stop, current_stop)
        
        return current_stop
```

---

## Take Profit Manager

```python
class TakeProfitManager:
    """
    Manage take profit levels with partial closes
    """
    
    def __init__(self, risk_reward_ratio=3.0):
        self.risk_reward_ratio = risk_reward_ratio  # 3:1 default
    
    def calculate_tp(self, entry_price, stop_loss, direction):
        """Calculate take profit level"""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.risk_reward_ratio
        
        if direction == 'BUY':
            return entry_price + reward
        else:
            return entry_price - reward
    
    def get_partial_close_levels(self, entry_price, tp_price, direction):
        """
        Return partial close levels:
        - Close 33% at 1:1.5
        - Close 33% at 1:2.5
        - Let 34% ride to full target
        """
        risk = abs(entry_price - tp_price) / self.risk_reward_ratio
        
        if direction == 'BUY':
            return [
                (entry_price + risk * 1.5, 0.33),
                (entry_price + risk * 2.5, 0.33),
                (tp_price, 0.34)
            ]
        else:
            return [
                (entry_price - risk * 1.5, 0.33),
                (entry_price - risk * 2.5, 0.33),
                (tp_price, 0.34)
            ]
```

---

## Daily Loss Limiter

```python
class DailyLossLimiter:
    """
    Stop trading when daily loss limit reached
    """
    
    def __init__(self, max_daily_loss_pct=0.05, max_trades_per_day=5):
        self.max_daily_loss_pct = max_daily_loss_pct  # 5% max daily loss
        self.max_trades_per_day = max_trades_per_day
        self.reset()
    
    def reset(self):
        """Reset daily counters"""
        self.daily_pnl = 0
        self.trades_today = 0
        self.trading_closed = False
    
    def check_limits(self, account_balance):
        """Check if any limit is reached"""
        
        # Check loss limit
        if abs(self.daily_pnl) / account_balance >= self.max_daily_loss_pct:
            self.trading_closed = True
            return False, "Daily loss limit reached"
        
        # Check trade limit
        if self.trades_today >= self.max_trades_per_day:
            self.trading_closed = True
            return False, "Max trades per day reached"
        
        return True, "OK"
    
    def update(self, pnl):
        """Update daily PnL"""
        self.daily_pnl += pnl
        self.trades_today += 1
```

---

## News Filter

```python
class NewsFilter:
    """
    Filter trades during high-impact news events
    """
    
    HIGH_IMPACT_EVENTS = [
        'NFP',           # Non-Farm Payrolls
        'FOMC',          # Fed interest rate decision
        'ECB',           # ECB rate decision
        'GDP',           # GDP releases
        'CPI',           # Inflation data
        'UNEMPLOYMENT',  # Unemployment claims
        'RETAIL',        # Retail sales
    ]
    
    def __init__(self, minutes_before=30, minutes_after=30):
        self.minutes_before = minutes_before
        self.minutes_after = minutes_after
    
    def can_trade(self, current_time, upcoming_news):
        """
        Check if trading is allowed based on news
        """
        for news in upcoming_news:
            time_diff = (news['datetime'] - current_time).total_seconds() / 60
            
            # Too close to news
            if -self.minutes_after < time_diff < self.minutes_before:
                return False, f"News event: {news['event']}"
        
        return True, "OK"
    
    def should_close_positions(self, current_time, open_positions, upcoming_news):
        """
        Check if positions should be closed before news
        """
        for news in upcoming_news:
            time_diff = (news['datetime'] - current_time).total_seconds() / 60
            
            if 0 < time_diff <= self.minutes_before:
                # Close all positions
                return True, f"Closing before: {news['event']}"
        
        return False, "OK"
```

---

## Complete Risk Manager

```python
class RiskManager:
    """
    Complete risk management system
    """
    
    def __init__(self, config):
        self.position_sizer = PositionSizer(
            config['account_balance'],
            config['risk_per_trade']
        )
        self.stop_loss = StopLossManager(
            config['initial_stop_pct'],
            config['trailing_stop_pct']
        )
        self.take_profit = TakeProfitManager(config['risk_reward_ratio'])
        self.daily_limits = DailyLossLimiter(
            config['max_daily_loss'],
            config['max_trades_per_day']
        )
        self.news_filter = NewsFilter(
            config['minutes_before_news'],
            config['minutes_after_news']
        )
    
    def before_trade(self, signal, account_balance, current_time, upcoming_news):
        """Pre-trade risk checks"""
        
        # Check daily limits
        can_trade, reason = self.daily_limits.check_limits(account_balance)
        if not can_trade:
            return False, reason
        
        # Check news filter
        can_trade, reason = self.news_filter.can_trade(current_time, upcoming_news)
        if not can_trade:
            return False, reason
        
        return True, "OK"
    
    def calculate_trade_parameters(self, entry_price, direction, account_balance):
        """Calculate all trade parameters"""
        
        # Calculate stop loss
        stop_loss = self.stop_loss.set_initial_stop(entry_price, direction)
        
        # Calculate position size
        position_size = self.position_sizer.calculate_position_size(
            entry_price,
            stop_loss
        )
        
        # Calculate take profit
        take_profit = self.take_profit.calculate_tp(entry_price, stop_loss, direction)
        
        return {
            'position_size': position_size,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_amount': account_balance * self.position_sizer.risk_per_trade
        }
```
