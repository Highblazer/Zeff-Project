#!/usr/bin/env python3
"""
Polymarket CLOB API Client

REST + WebSocket integration with https://clob.polymarket.com/
Handles: market discovery, order placement, position tracking.

Polymarket uses the Polygon blockchain + USDC for settlement.
The CLOB (Central Limit Order Book) API provides off-chain matching.

API Docs: https://docs.polymarket.com/
"""

import json
import time
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from urllib.parse import urlencode


CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


class PolymarketClient:
    """Client for Polymarket CLOB API."""

    def __init__(self, api_key=None, api_secret=None, passphrase=None, private_key=None):
        """Initialize client.

        Args:
            api_key: Polymarket API key (from account settings)
            api_secret: API secret for signing requests
            passphrase: API passphrase
            private_key: Polygon wallet private key (0x...) for deriving API creds
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.private_key = private_key
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    def _sign_request(self, method, path, body=''):
        """Sign API request with HMAC-SHA256."""
        if not self.api_key or not self.api_secret:
            return {}

        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        return {
            'POLY-API-KEY': self.api_key,
            'POLY-SIGNATURE': signature,
            'POLY-TIMESTAMP': timestamp,
            'POLY-PASSPHRASE': self.passphrase or '',
        }

    # ── Market Discovery ──

    def get_markets(self, limit=50, active=True, closed=False):
        """Fetch available markets from Gamma API.

        Returns list of markets with normalized token data.
        The Gamma API returns outcomes/prices/tokenIds as separate arrays,
        so we synthesize a `tokens` list for convenient downstream use.
        """
        try:
            params = {
                'limit': limit,
                'active': str(active).lower(),
                'closed': str(closed).lower(),
                'order': 'volume24hr',
                'ascending': 'false',
            }
            resp = self.session.get(f"{GAMMA_BASE}/markets", params=params, timeout=15)
            if resp.status_code == 200:
                markets = resp.json()
                for m in markets:
                    self._normalize_market(m)
                return markets
            return []
        except Exception as e:
            print(f"[Polymarket] Market fetch error: {e}")
            return []

    @staticmethod
    def _normalize_market(m):
        """Normalize Gamma API market data into a consistent structure.

        The API returns outcomes, outcomePrices, and clobTokenIds as
        separate parallel arrays. We merge them into a `tokens` list
        and normalize field names (conditionId -> condition_id).
        """
        # Normalize condition_id
        if not m.get('condition_id') and m.get('conditionId'):
            m['condition_id'] = m['conditionId']

        # Synthesize tokens array from parallel arrays if not already present
        if not m.get('tokens'):
            outcomes = m.get('outcomes', [])
            prices = m.get('outcomePrices', [])
            token_ids = m.get('clobTokenIds', [])

            # Parse outcomes/prices if they're JSON strings
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except Exception:
                    outcomes = []
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except Exception:
                    prices = []
            if isinstance(token_ids, str):
                try:
                    token_ids = json.loads(token_ids)
                except Exception:
                    token_ids = []

            tokens = []
            for i in range(len(outcomes)):
                token = {
                    'outcome': outcomes[i] if i < len(outcomes) else f'Outcome_{i}',
                    'price': float(prices[i]) if i < len(prices) else 0.5,
                    'token_id': token_ids[i] if i < len(token_ids) else '',
                }
                tokens.append(token)
            m['tokens'] = tokens

        # Normalize volume field
        if not m.get('volume24hr') and m.get('volume24hrClob'):
            m['volume24hr'] = m['volume24hrClob']

    def get_market(self, condition_id):
        """Get details for a specific market."""
        try:
            resp = self.session.get(f"{GAMMA_BASE}/markets/{condition_id}", timeout=10)
            if resp.status_code == 200:
                m = resp.json()
                self._normalize_market(m)
                return m
        except Exception:
            pass
        return None

    def get_prices(self, token_ids):
        """Get current prices for token IDs.

        Args:
            token_ids: list of token IDs (YES/NO outcome tokens)

        Returns: dict mapping token_id -> price (0-1)
        """
        try:
            resp = self.session.get(f"{CLOB_BASE}/prices", params={
                'token_ids': ','.join(token_ids)
            }, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def get_orderbook(self, token_id):
        """Get order book for a token.

        Returns: {'bids': [...], 'asks': [...], 'spread': float}
        """
        try:
            resp = self.session.get(f"{CLOB_BASE}/book", params={
                'token_id': token_id,
            }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                bids = data.get('bids', [])
                asks = data.get('asks', [])
                best_bid = float(bids[0]['price']) if bids else 0
                best_ask = float(asks[0]['price']) if asks else 1
                return {
                    'bids': bids[:10],
                    'asks': asks[:10],
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'spread': round(best_ask - best_bid, 4),
                    'mid': round((best_bid + best_ask) / 2, 4),
                }
        except Exception:
            pass
        return {}

    def get_midpoint(self, token_id):
        """Get midpoint price for a token."""
        try:
            resp = self.session.get(f"{CLOB_BASE}/midpoint", params={
                'token_id': token_id,
            }, timeout=10)
            if resp.status_code == 200:
                return float(resp.json().get('mid', 0))
        except Exception:
            pass
        return 0.0

    # ── Trading (requires auth) ──

    def place_order(self, token_id, side, price, size):
        """Place a limit order on the CLOB.

        Args:
            token_id: the outcome token to trade
            side: 'BUY' or 'SELL'
            price: limit price (0-1, e.g. 0.65 = 65 cents)
            size: number of shares (USDC amount at price)

        Returns: order response dict or None
        """
        if not self.api_key:
            print("[Polymarket] Cannot place order — no API key configured")
            return None

        path = '/order'
        body = json.dumps({
            'tokenID': token_id,
            'side': side.upper(),
            'price': str(price),
            'size': str(size),
            'type': 'GTC',  # Good Till Cancelled
        })

        headers = self._sign_request('POST', path, body)
        try:
            resp = self.session.post(
                f"{CLOB_BASE}{path}",
                data=body,
                headers=headers,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                return resp.json()
            else:
                print(f"[Polymarket] Order rejected: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[Polymarket] Order error: {e}")
        return None

    def cancel_order(self, order_id):
        """Cancel an open order."""
        if not self.api_key:
            return None

        path = f'/order/{order_id}'
        headers = self._sign_request('DELETE', path)
        try:
            resp = self.session.delete(
                f"{CLOB_BASE}{path}",
                headers=headers,
                timeout=10,
            )
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def get_open_orders(self):
        """Get all open orders for the authenticated user."""
        if not self.api_key:
            return []

        path = '/orders'
        headers = self._sign_request('GET', path)
        try:
            resp = self.session.get(
                f"{CLOB_BASE}{path}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    def get_trades(self, limit=50):
        """Get recent trades for the authenticated user."""
        if not self.api_key:
            return []

        path = '/trades'
        headers = self._sign_request('GET', path)
        try:
            resp = self.session.get(
                f"{CLOB_BASE}{path}",
                params={'limit': limit},
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    # ── Utility ──

    def search_markets(self, query, limit=20):
        """Search markets by keyword."""
        try:
            resp = self.session.get(f"{GAMMA_BASE}/markets", params={
                'tag': query,
                'limit': limit,
                'active': 'true',
            }, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

        # Fallback: fetch all and filter
        markets = self.get_markets(limit=100)
        query_lower = query.lower()
        return [m for m in markets if query_lower in m.get('question', '').lower()
                or query_lower in m.get('description', '').lower()][:limit]
