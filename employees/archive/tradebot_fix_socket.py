#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader FIX API
Using direct socket connection with FIX protocol
"""

import json
import socket
import ssl
import time
import signal
import sys
from datetime import datetime
import threading

CONFIG_FILE = '/root/.openclaw/workspace/conf/icmarkets.json'

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']

# FIX API Configuration
HOST = "demo-uk-eqx-01.p.c-trader.com"
TRADE_PORT = 5212
QUOTE_PORT = 5211

# Credentials
ACCOUNT_ID = IC['ctid_trader_account_id']  # No fallback — must be configured
ACCOUNT_LOGIN = IC.get('account_id', '9877716')
PASSWORD = IC.get('trading_password', '')
CLIENT_ID = IC.get('client_id', '')
CLIENT_SECRET = IC.get('api_secret', '')

# Symbol IDs
SYMBOLS = {
    'EURUSD': 1, 'GBPUSD': 2, 'USDJPY': 3, 'AUDUSD': 4,
    'USDCAD': 5, 'USDCHF': 6, 'NZDUSD': 7, 'XAUUSD': 10, 'XAGUSD': 11
}

class FIXClient:
    def __init__(self):
        self.socket = None
        self.connected = False
        self.running = True
        self.msg_seq = 1
        
    def connect(self):
        """Connect to FIX API"""
        print(f"Connecting to {HOST}:{TRADE_PORT}...")
        
        # Create SSL socket with proper certificate verification
        context = ssl.create_default_context()
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket = context.wrap_socket(sock, server_hostname=HOST)
        
        self.socket.connect((HOST, TRADE_PORT))
        self.connected = True
        print("Connected!")
        
        # Send logon
        self.send_logon()
        
        # Start receiving
        self.receive_loop()
    
    def create_fix_msg(self, msg_type, fields):
        """Create FIX message"""
        # Simplified FIX-like message format for cTrader
        msg = f"8=FIX.4.4|9={len(fields)}|"
        for k, v in fields.items():
            msg += f"{k}={v}|"
        msg += f"10={self.calculate_checksum(msg)}|"
        return msg
    
    def calculate_checksum(self, msg):
        """Calculate FIX checksum"""
        # Simplified - just return placeholder
        return "000"
    
    def send_logon(self):
        """Send FIX logon message"""
        fields = {
            '35': 'A',  # Logon
            '49': f'demo.icmarkets.{ACCOUNT_LOGIN}',  # SenderCompID
            '56': 'cServer',  # TargetCompID
            '50': 'TRADE',  # SenderSubID
            '96': PASSWORD,  # Password
            '553': ACCOUNT_LOGIN,  # Username
            '554': PASSWORD,  # Password
            '108': '30',  # Heartbeat interval (seconds)
            '141': 'Y',  # ResetSeqNumFlag
        }
        
        msg = self.create_fix_msg('A', fields)
        self.socket.send(msg.encode())
        print("Logon sent")
    
    def receive_loop(self):
        """Receive and process messages"""
        buffer = ""
        while self.running:
            try:
                data = self.socket.recv(4096)
                if not data:
                    break
                buffer += data.decode('utf-8', errors='ignore')
                
                # Process complete messages
                while '|' in buffer:
                    msg_end = buffer.index('|')
                    msg = buffer[:msg_end]
                    buffer = buffer[msg_end+1:]
                    
                    if msg:
                        print(f"Received: {msg[:100]}...")
            except Exception as e:
                print(f"Receive error: {e}")
                break
        
        self.connected = False
        print("Disconnected")

def main():
    print("=" * 50)
    print("TradeBot - IC Markets FIX Protocol")
    print("=" * 50)
    print(f"Account: {ACCOUNT_LOGIN}")
    print(f"Host: {HOST}:{TRADE_PORT}")
    print("-" * 50)
    
    client = FIXClient()
    
    try:
        client.connect()
    except KeyboardInterrupt:
        print("\nShutting down...")
        client.running = False

if __name__ == '__main__':
    main()
