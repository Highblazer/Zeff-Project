# Paper Trading Simulator

## Complete Paper Trading System

```python
import json
from datetime import datetime
from collections import deque

class PaperTradingAccount:
    """
    Simulated trading account for testing strategies
    """
    
    def __init__(self, initial_balance=10000, leverage=100):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.leverage = leverage
        self.equity = initial_balance
        self.positions = {}
        self.closed_trades = []
        self.pending_orders = []
        self.transaction_history = []
        self.daily_pnl = 0
        self.last_reset_date = datetime.now().date()
    
    def get_balance(self):
        """Current account balance"""
        return self.balance
    
    def get_equity(self):
        """Account equity (balance + open PnL)"""
        open_pnl = sum(pos['unrealized_pnl'] for pos in self.positions.values())
        return self.balance + open_pnl
    
    def can_open_position(self, pair, lot_size, entry_price):
        """Check if can afford to open position"""
        required_margin = (lot_size * entry_price) / self.leverage
        return required_margin <= self.get_equity() * 0.1  # Max 10% margin
    
    def open_position(self, pair, direction, lot_size, entry_price, 
                     stop_loss=None, take_profit=None, strategy_name="unknown"):
        """
        Open a new position
        """
        if pair in self.positions:
            return False, "Position already exists"
        
        if not self.can_open_position(pair, lot_size, entry_price):
            return False, "Insufficient margin"
        
        # Calculate margin required
        margin_required = (lot_size * entry_price) / self.leverage
        
        position = {
            'pair': pair,
            'direction': direction,
            'lot_size': lot_size,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'strategy': strategy_name,
            'open_time': datetime.now(),
            'margin_used': margin_required,
            'unrealized_pnl': 0
        }
        
        self.positions[pair] = position
        
        self.transaction_history.append({
            'time': datetime.now(),
            'action': 'OPEN',
            'pair': pair,
            'direction': direction,
            'price': entry_price,
            'lots': lot_size
        })
        
        return True, f"Position opened: {direction} {lot_size} {pair} @ {entry_price}"
    
    def close_position(self, pair, exit_price, reason="manual"):
        """
        Close an existing position
        """
        if pair not in self.positions:
            return False, "No position found"
        
        position = self.positions[pair]
        
        # Calculate PnL
        if position['direction'] == 'BUY':
            pnl = (exit_price - position['entry_price']) * position['lot_size'] * 100000
        else:
            pnl = (position['entry_price'] - exit_price) * position['lot_size'] * 100000
        
        # Apply commission
        commission = position['lot_size'] * 7  # ~$7 round trip
        
        net_pnl = pnl - commission
        
        # Record closed trade
        closed_trade = {
            'pair': position['pair'],
            'direction': position['direction'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'lot_size': position['lot_size'],
            'pnl': net_pnl,
            'return_pct': (net_pnl / self.initial_balance) * 100,
            'open_time': position['open_time'],
            'close_time': datetime.now(),
            'duration_minutes': (datetime.now() - position['open_time']).total_seconds() / 60,
            'strategy': position['strategy'],
            'exit_reason': reason
        }
        
        self.closed_trades.append(closed_trade)
        
        # Update balance
        self.balance += net_pnl
        self.daily_pnl += net_pnl
        
        # Remove position
        del self.positions[pair]
        
        self.transaction_history.append({
            'time': datetime.now(),
            'action': 'CLOSE',
            'pair': pair,
            'price': exit_price,
            'pnl': net_pnl,
            'reason': reason
        })
        
        return True, f"Position closed: {pair} @ {exit_price}, PnL: ${net_pnl:.2f}"
    
    def update_positions(self, current_prices):
        """
        Update all positions with current prices
        Check stop loss / take profit
        """
        to_close = []
        
        for pair, position in self.positions.items():
            if pair not in current_prices:
                continue
            
            current_price = current_prices[pair]
            
            # Update unrealized PnL
            if position['direction'] == 'BUY':
                pnl = (current_price - position['entry_price']) * position['lot_size'] * 100000
            else:
                pnl = (position['entry_price'] - current_price) * position['lot_size'] * 100000
            
            position['unrealized_pnl'] = pnl
            
            # Check stop loss
            if position['stop_loss']:
                if position['direction'] == 'BUY' and current_price <= position['stop_loss']:
                    to_close.append((pair, current_price, 'STOP_LOSS'))
                elif position['direction'] == 'SELL' and current_price >= position['stop_loss']:
                    to_close.append((pair, current_price, 'STOP_LOSS'))
            
            # Check take profit
            if position['take_profit']:
                if position['direction'] == 'BUY' and current_price >= position['take_profit']:
                    to_close.append((pair, current_price, 'TAKE_PROFIT'))
                elif position['direction'] == 'SELL' and current_price <= position['take_profit']:
                    to_close.append((pair, current_price, 'TAKE_PROFIT'))
        
        # Close triggered positions
        for pair, price, reason in to_close:
            self.close_position(pair, price, reason)
        
        return to_close
    
    def get_open_positions(self):
        """Get all open positions"""
        return list(self.positions.values())
    
    def get_performance_stats(self):
        """
        Calculate performance statistics
        """
        if not self.closed_trades:
            return {'message': 'No closed trades yet'}
        
        trades = self.closed_trades
        
        winning = [t for t in trades if t['pnl'] > 0]
        losing = [t for t in trades if t['pnl'] <= 0]
        
        total_trades = len(trades)
        win_rate = len(winning) / total_trades * 100 if total_trades > 0 else 0
        
        avg_win = sum(t['pnl'] for t in winning) / len(winning) if winning else 0
        avg_loss = abs(sum(t['pnl'] for t in losing) / len(losing)) if losing else 0
        
        profit_factor = (avg_win * len(winning)) / (avg_loss * len(losing)) if losing and avg_loss > 0 else float('inf')
        
        return {
            'total_trades': total_trades,
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'total_pnl': round(sum(t['pnl'] for t in trades), 2),
            'current_balance': round(self.balance, 2),
            'total_return_pct': round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            'open_positions': len(self.positions)
        }
    
    def reset_daily(self):
        """Reset daily counters"""
        today = datetime.now().date()
        if today != self.last_reset_date:
            self.daily_pnl = 0
            self.last_reset_date = today
```

---

## Order Management

```python
class OrderManager:
    """
    Manage pending and executed orders
    """
    
    def __init__(self, account):
        self.account = account
        self.orders = deque(maxlen=100)
    
    def place_market_order(self, pair, direction, lot_size, strategy):
        """Place market order at current price"""
        # Get current price (simulated)
        current_price = self.get_current_price(pair)
        
        # Calculate stop loss and take profit
        sl_pct = strategy.parameters.get('stop_loss_pct', 0.015)
        tp_ratio = strategy.parameters.get('take_profit_ratio', 3.0)
        
        if direction == 'BUY':
            stop_loss = current_price * (1 - sl_pct)
            take_profit = current_price * (1 + sl_pct * tp_ratio)
        else:
            stop_loss = current_price * (1 + sl_pct)
            take_profit = current_price * (1 - sl_pct * tp_ratio)
        
        # Open position
        success, message = self.account.open_position(
            pair=pair,
            direction=direction,
            lot_size=lot_size,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy.__class__.__name__
        )
        
        return success, message
    
    def place_limit_order(self, pair, direction, lot_size, limit_price, strategy):
        """Place limit order"""
        order = {
            'type': 'LIMIT',
            'pair': pair,
            'direction': direction,
            'lot_size': lot_size,
            'limit_price': limit_price,
            'strategy': strategy.__class__.__name__,
            'created_at': datetime.now()
        }
        
        self.orders.append(order)
        return True, f"Limit order placed: {direction} {lot_size} {pair} @ {limit_price}"
    
    def place_stop_order(self, pair, direction, lot_size, stop_price, strategy):
        """Place stop order"""
        order = {
            'type': 'STOP',
            'pair': pair,
            'direction': direction,
            'lot_size': lot_size,
            'stop_price': stop_price,
            'strategy': strategy.__class__.__name__,
            'created_at': datetime.now()
        }
        
        self.orders.append(order)
        return True, f"Stop order placed: {direction} {lot_size} {pair} @ {stop_price}"
    
    def check_pending_orders(self, current_prices):
        """Check and execute pending orders"""
        executed = []
        
        for order in list(self.orders):
            pair = order['pair']
            if pair not in current_prices:
                continue
            
            current = current_prices[pair]
            
            if order['type'] == 'LIMIT':
                # Check if limit reached
                if (order['direction'] == 'BUY' and current <= order['limit_price']) or \
                   (order['direction'] == 'SELL' and current >= order['limit_price']):
                    # Execute order
                    success, msg = self.place_market_order(
                        pair, order['direction'], order['lot_size'],
                        order['strategy']
                    )
                    if success:
                        self.orders.remove(order)
                        executed.append(order)
            
            elif order['type'] == 'STOP':
                # Check if stop triggered
                if (order['direction'] == 'BUY' and current >= order['stop_price']) or \
                   (order['direction'] == 'SELL' and current <= order['stop_price']):
                    success, msg = self.place_market_order(
                        pair, order['direction'], order['lot_size'],
                        order['strategy']
                    )
                    if success:
                        self.orders.remove(order)
                        executed.append(order)
        
        return executed
    
    def get_current_price(self, pair):
        """Get current price (simulated)"""
        # In real implementation, fetch from broker API
        # For simulation, use last closed price or mock
        return 1.1000  # Placeholder
```

---

## Trading Session Manager

```python
class TradingSession:
    """
    Manage overall trading session
    """
    
    def __init__(self, config):
        self.config = config
        self.account = PaperTradingAccount(config['initial_balance'])
        self.order_manager = OrderManager(self.account)
        self.strategies = {}
        self.is_trading = True
        self.trading_session_start = datetime.now()
    
    def add_strategy(self, name, strategy):
        """Add trading strategy"""
        self.strategies[name] = strategy
    
    def run_trading_cycle(self, current_prices, upcoming_news):
        """
        Run one trading cycle
        
        1. Check daily limits
        2. Update positions (SL/TP)
        3. Check pending orders
        4. Generate new signals
        5. Execute new trades
        """
        
        # 1. Check daily limits
        can_trade, reason = self.account.daily_limits.check_limits(
            self.account.get_equity()
        )
        
        if not can_trade:
            return {'action': 'STOP', 'reason': reason}
        
        # 2. Check news
        can_trade, reason = self.account.news_filter.can_trade(
            datetime.now(), upcoming_news
        )
        
        if not can_trade:
            return {'action': 'NO_TRADE', 'reason': f'News: {reason}'}
        
        # 3. Update open positions
        closed = self.account.update_positions(current_prices)
        if closed:
            print(f"Closed positions: {closed}")
        
        # 4. Check pending orders
        self.order_manager.check_pending_orders(current_prices)
        
        # 5. Generate signals from strategies
        signals = []
        for name, strategy in self.strategies.items():
            signal = strategy.check_entry(current_prices)
            if signal != 'HOLD':
                signals.append({
                    'strategy': name,
                    'signal': signal,
                    'pair': strategy.pair
                })
        
        # 6. Execute signals
        executed = []
        for sig in signals:
            if len(self.account.positions) >= self.config.get('max_positions', 3):
                break
            
            strategy = self.strategies[sig['strategy']]
            success, msg = self.order_manager.place_market_order(
                sig['pair'], sig['signal'], 
                self.config['default_lot_size'],
                strategy
            )
            
            if success:
                executed.append(msg)
        
        return {
            'action': 'COMPLETE',
            'closed': closed,
            'executed': executed,
            'open_positions': len(self.account.positions),
            'equity': self.account.get_equity()
        }
    
    def get_status(self):
        """Get current trading status"""
        return {
            'is_trading': self.is_trading,
            'balance': self.account.get_balance(),
            'equity': self.account.get_equity(),
            'open_positions': len(self.account.positions),
            'performance': self.account.get_performance_stats(),
            'uptime': str(datetime.now() - self.trading_session_start)
        }
```
