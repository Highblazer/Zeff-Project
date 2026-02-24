# Trading Strategies Library

## Complete Strategy Implementations

---

## Strategy 1: EMA Trend Following

```python
class EMATrendStrategy:
    """
    Buy when 50 EMA crosses above 200 EMA (Golden Cross)
    Sell when 50 EMA crosses below 200 EMA (Death Cross)
    """
    
    parameters = {
        'fast_ema': 50,
        'slow_ema': 200,
        'rsi_period': 14,
        'rsi_oversold': 30,
        'rsi_overbought': 70,
        'stop_loss_pct': 1.5,
        'take_profit_ratio': 3.0
    }
    
    def check_entry(self, df):
        # Golden Cross
        if df['ema_50'] > df['ema_200'] and df['rsi'] < self.parameters['rsi_overbought']:
            return 'BUY'
        
        # Death Cross  
        if df['ema_50'] < df['ema_200'] and df['rsi'] > self.parameters['rsi_oversold']:
            return 'SELL'
        
        return 'HOLD'
```

---

## Strategy 2: RSI Mean Reversion

```python
class RSIMeanReversion:
    """
    Buy when RSI < 30 (oversold)
    Sell when RSI > 70 (overbought)
    """
    
    parameters = {
        'rsi_period': 14,
        'oversold': 30,
        'overbought': 70,
        'stop_loss_pct': 2.0,
        'take_profit_ratio': 2.0,
        'exit_at': 50  # Exit when RSI returns to neutral
    }
    
    def check_entry(self, df):
        if df['rsi'] < self.parameters['oversold']:
            return 'BUY'
        
        if df['rsi'] > self.parameters['overbought']:
            return 'SELL'
        
        return 'HOLD'
```

---

## Strategy 3: MACD Momentum

```python
class MACDMomentum:
    """
    Buy when MACD line crosses above signal line
    Sell when MACD line crosses below signal line
    """
    
    parameters = {
        'fast_period': 12,
        'slow_period': 26,
        'signal_period': 9,
        'stop_loss_pct': 1.5,
        'take_profit_ratio': 2.5
    }
    
    def check_entry(self, df):
        # MACD crosses above signal (bullish)
        if df['macd'] > df['macd_signal'] and df['macd_prev'] <= df['macd_signal_prev']:
            return 'BUY'
        
        # MACD crosses below signal (bearish)
        if df['macd'] < df['macd_signal'] and df['macd_prev'] >= df['macd_signal_prev']:
            return 'SELL'
        
        return 'HOLD'
```

---

## Strategy 4: Bollinger Band Breakout

```python
class BollingerBreakout:
    """
    Buy when price breaks above upper band
    Sell when price breaks below lower band
    """
    
    parameters = {
        'period': 20,
        'std_dev': 2,
        'stop_loss_pct': 2.0,
        'take_profit_ratio': 2.0
    }
    
    def check_entry(self, df):
        # Breakout above upper band
        if df['close'] > df['bb_upper']:
            return 'BUY'
        
        # Breakout below lower band
        if df['close'] < df['bb_lower']:
            return 'SELL'
        
        return 'HOLD'
```

---

## Strategy 5: Support/Resistance Breakout

```python
class SupportResistanceBreakout:
    """
    Buy on support breakout
    Sell on resistance breakdown
    """
    
    parameters = {
        'lookback': 20,
        'volume_threshold': 1.5,  # Volume must be 1.5x average
        'stop_loss_pct': 2.0,
        'take_profit_ratio': 3.0
    }
    
    def check_entry(self, df):
        # New high with volume confirmation
        if df['close'] > df['highest_20'] and df['volume'] > df['avg_volume'] * self.parameters['volume_threshold']:
            return 'BUY'
        
        # New low with volume confirmation
        if df['close'] < df['lowest_20'] and df['volume'] > df['avg_volume'] * self.parameters['volume_threshold']:
            return 'SELL'
        
        return 'HOLD'
```

---

## Strategy 6: Moving Average Ribbon

```python
class MARibbon:
    """
    Trade in direction of MA ribbon trend
    All MAs must be aligned for entry
    """
    
    parameters = {
        'mas': [10, 20, 50, 100, 200],
        'stop_loss_pct': 1.5,
        'take_profit_ratio': 2.5
    }
    
    def check_entry(self, df):
        # All MAs aligned upward (strong uptrend)
        if all(df[f'ema_{ma}'] > df[f'ema_{ma}'].shift(1) for ma in self.parameters['mas']):
            return 'BUY'
        
        # All MAs aligned downward (strong downtrend)
        if all(df[f'ema_{ma}'] < df[f'ema_{ma}'].shift(1) for ma in self.parameters['mas']):
            return 'SELL'
        
        return 'HOLD'
```

---

## Indicator Calculations

```python
def calculate_ema(prices, period):
    """Exponential Moving Average"""
    return prices.ewm(span=period, adjust=False).mean()

def calculate_rsi(prices, period=14):
    """Relative Strength Index"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """MACD Indicator"""
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    macd = ema_fast - ema_slow
    signal_line = calculate_ema(macd, signal)
    histogram = macd - signal_line
    return macd, signal_line, histogram

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """Bollinger Bands"""
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower

def calculate_atr(high, low, close, period=14):
    """Average True Range - Volatility indicator"""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()
```

---

## Combining Strategies (Multi-Strategy)

```python
class MultiStrategyBot:
    """
    Run multiple strategies and trade only when they agree
    """
    
    strategies = [
        EMATrendStrategy(),
        RSIMeanReversion(),
        MACDMomentum()
    ]
    
    # Require at least 2 out of 3 strategies to agree
    minimum_agreement = 2
    
    def get_signal(self, df):
        signals = []
        for strategy in self.strategies:
            signals.append(strategy.check_entry(df))
        
        buy_count = signals.count('BUY')
        sell_count = signals.count('SELL')
        
        if buy_count >= self.minimum_agreement:
            return 'BUY'
        elif sell_count >= self.minimum_agreement:
            return 'SELL'
        
        return 'HOLD'
```
