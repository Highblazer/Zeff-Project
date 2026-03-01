# IC Markets cTrader API Connector

import requests
import json
import time
from datetime import datetime

class ICTraderAPI:
    """
    IC Markets cTrader API Connector
    """
    
    # API Endpoints
    BASE_URL = "https://api.icmarkets.com"
    AUTH_URL = "https://api.icmarkets.com/connect"
    
    def __init__(self, api_token):
        self.api_token = api_token
        self.access_token = None
        self.account_id = None
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        })
    
    def authenticate(self):
        """
        Authenticate with cTrader API
        """
        try:
            # Get access token
            response = self.session.get(
                f"{self.AUTH_URL}/token",
                params={'access_token': self.api_token}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('access_token')
                self.session.headers.update({
                    'Authorization': f'Bearer {self.access_token}'
                })
                return True, "Authenticated successfully"
            else:
                return False, f"Auth failed: {response.text}"
        
        except Exception as e:
            return False, f"Auth error: {str(e)}"
    
    def get_account_info(self):
        """
        Get account details
        """
        try:
            response = self.session.get(f"{self.BASE_URL}/accounts/me")
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Error: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def get_positions(self):
        """
        Get open positions
        """
        try:
            response = self.session.get(f"{self.BASE_URL}/positions")
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Error: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def get_pending_orders(self):
        """
        Get pending orders
        """
        try:
            response = self.session.get(f"{self.BASE_URL}/orders")
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Error: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def place_order(self, symbol, order_type, volume, side, price=None, stop_loss=None, take_profit=None):
        """
        Place a trade order
        
        Args:
            symbol: Trading symbol (e.g., EURUSD)
            order_type: 'market' or 'limit'
            volume: Trade volume in lots
            side: 'buy' or 'sell'
            price: Limit price (for limit orders)
            stop_loss: Stop loss price
            take_profit: Take profit price
        """
        order_data = {
            'symbol': symbol,
            'volume': volume,
            'side': side.upper(),
            'type': order_type,
        }
        
        if price:
            order_data['price'] = price
        
        if stop_loss:
            order_data['stopLoss'] = stop_loss
        
        if take_profit:
            order_data['takeProfit'] = take_profit
        
        try:
            response = self.session.post(
                f"{self.BASE_URL}/orders",
                json=order_data
            )
            
            if response.status_code in [200, 201]:
                return True, response.json()
            else:
                return False, f"Order failed: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def close_position(self, position_id):
        """
        Close an open position
        """
        try:
            response = self.session.delete(
                f"{self.BASE_URL}/positions/{position_id}"
            )
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Close failed: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def get_symbols(self):
        """
        Get available trading symbols
        """
        try:
            response = self.session.get(f"{self.BASE_URL}/symbols")
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Error: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def get_prices(self, symbols):
        """
        Get current prices for symbols
        """
        try:
            response = self.session.get(
                f"{self.BASE_URL}/prices",
                params={'symbols': ','.join(symbols)}
            )
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Error: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def get_historical_candles(self, symbol, timeframe='H1', count=100):
        """
        Get historical candlestick data
        
        Args:
            symbol: Trading symbol
            timeframe: M1, M5, M15, M30, H1, H4, D1
            count: Number of candles
        """
        try:
            response = self.session.get(
                f"{self.BASE_URL}/history",
                params={
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'count': count
                }
            )
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Error: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def get_account_balance(self):
        """
        Get account balance
        """
        try:
            response = self.session.get(f"{self.BASE_URL}/accounts/me/balance")
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Error: {response.text}"
        
        except Exception as e:
            return False, f"Error: {str(e)}"


# Demo mode (simulated trading)
class SimulatedTrader:
    """
    Simulated trading for paper trading
    """
    
    def __init__(self, initial_balance=10000):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = {}
        self.closed_trades = []
        self.trade_history = []
    
    def get_balance(self):
        return self.balance
    
    def get_equity(self):
        equity = self.balance
        for pos in self.positions.values():
            equity += pos['pnl']
        return equity
    
    def open_position(self, symbol, side, volume, entry_price, stop_loss=None, take_profit=None):
        """
        Open a simulated position
        """
        position_id = f"{symbol}_{len(self.closed_trades) + 1}"
        
        self.positions[position_id] = {
            'symbol': symbol,
            'side': side,
            'volume': volume,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'pnl': 0,
            'open_time': datetime.now()
        }
        
        return True, {'position_id': position_id, 'message': f'{side.upper()} {volume} {symbol} @ {entry_price}'}
    
    def close_position(self, position_id, exit_price):
        """
        Close a simulated position
        """
        if position_id not in self.positions:
            return False, "Position not found"
        
        pos = self.positions[position_id]
        
        # Calculate PnL
        if pos['side'] == 'buy':
            pnl = (exit_price - pos['entry_price']) * pos['volume'] * 100000
        else:
            pnl = (pos['entry_price'] - exit_price) * pos['volume'] * 100000
        
        # Apply commission (~$7 per lot)
        commission = pos['volume'] * 7
        net_pnl = pnl - commission
        
        # Record trade
        self.closed_trades.append({
            'position_id': position_id,
            'symbol': pos['symbol'],
            'side': pos['side'],
            'volume': pos['volume'],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'pnl': net_pnl,
            'open_time': pos['open_time'],
            'close_time': datetime.now()
        })
        
        self.balance += net_pnl
        del self.positions[position_id]
        
        return True, {'pnl': net_pnl, 'new_balance': self.balance}
    
    def update_prices(self, prices):
        """
        Update positions with current prices
        """
        for pos_id, pos in list(self.positions.items()):
            symbol = pos['symbol']
            if symbol in prices:
                current_price = prices[symbol]
                
                if pos['side'] == 'buy':
                    pnl = (current_price - pos['entry_price']) * pos['volume'] * 100000
                else:
                    pnl = (pos['entry_price'] - current_price) * pos['volume'] * 100000
                
                pos['pnl'] = pnl
                
                # Check SL/TP
                should_close = None
                reason = None
                
                if pos['side'] == 'buy':
                    if pos['stop_loss'] and current_price <= pos['stop_loss']:
                        should_close = True
                        reason = 'STOP_LOSS'
                    elif pos['take_profit'] and current_price >= pos['take_profit']:
                        should_close = True
                        reason = 'TAKE_PROFIT'
                else:
                    if pos['stop_loss'] and current_price >= pos['stop_loss']:
                        should_close = True
                        reason = 'STOP_LOSS'
                    elif pos['take_profit'] and current_price <= pos['take_profit']:
                        should_close = True
                        reason = 'TAKE_PROFIT'
                
                if should_close:
                    self.close_position(pos_id, current_price)
    
    def get_stats(self):
        """
        Get trading statistics
        """
        if not self.closed_trades:
            return {'message': 'No trades yet'}
        
        wins = [t for t in self.closed_trades if t['pnl'] > 0]
        losses = [t for t in self.closed_trades if t['pnl'] <= 0]
        
        total_trades = len(self.closed_trades)
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
        
        return {
            'total_trades': total_trades,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(win_rate, 2),
            'total_pnl': round(sum(t['pnl'] for t in self.closed_trades), 2),
            'current_balance': round(self.balance, 2),
            'return_pct': round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            'open_positions': len(self.positions)
        }
