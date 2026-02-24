# News & Economic Calendar Module

## Economic Calendar

```python
import requests
from datetime import datetime, timedelta

class EconomicCalendar:
    """
    Track economic events and news that impact markets
    """
    
    # High impact events that affect trading
    HIGH_IMPACT_EVENTS = {
        'US Non-Farm Payrolls': {'impact': 'HIGH', 'pairs': ['EUR/USD', 'GBP/USD', 'USD/JPY']},
        'US Unemployment Rate': {'impact': 'HIGH', 'pairs': ['EUR/USD', 'GBP/USD']},
        'US CPI (Inflation)': {'impact': 'HIGH', 'pairs': ['EUR/USD', 'GBP/USD', 'USD/JPY']},
        'US GDP Growth Rate': {'impact': 'HIGH', 'pairs': ['EUR/USD', 'GBP/USD', 'USD/JPY']},
        'FOMC Meeting Minutes': {'impact': 'HIGH', 'pairs': ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF']},
        'FOMC Interest Rate': {'impact': 'VERY_HIGH', 'pairs': ['ALL']},
        'ECB Interest Rate': {'impact': 'HIGH', 'pairs': ['EUR/USD', 'EUR/GBP']},
        'BOE Interest Rate': {'impact': 'HIGH', 'pairs': ['EUR/GBP', 'GBP/USD']},
        'BOJ Interest Rate': {'impact': 'HIGH', 'pairs': ['USD/JPY']},
        'US Retail Sales': {'impact': 'HIGH', 'pairs': ['EUR/USD', 'GBP/USD']},
        'German GDP': {'impact': 'MEDIUM', 'pairs': ['EUR/USD', 'EUR/GBP']},
        'UK GDP': {'impact': 'MEDIUM', 'pairs': ['EUR/GBP', 'GBP/USD']},
        'US Consumer Confidence': {'impact': 'MEDIUM', 'pairs': ['EUR/USD', 'GBP/USD']},
        'US Factory Orders': {'impact': 'MEDIUM', 'pairs': ['EUR/USD']},
    }
    
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.events = []
        self.cache = []
        self.cache_timeout = 3600  # 1 hour
    
    def fetch_upcoming_events(self, days=7):
        """
        Fetch upcoming economic events
        
        In production, use:
        - forexfactory.com (scraper)
        - investing.com (API)
        - alphavantage.co (API)
        """
        
        # For now, return sample events
        # Replace with actual API call in production
        
        today = datetime.now()
        
        sample_events = [
            {
                'date': today + timedelta(days=1),
                'time': '13:30 GMT',
                'event': 'US Non-Farm Payrolls',
                'impact': 'HIGH',
                'forecast': '180K',
                'previous': '256K',
                'pairs': ['EUR/USD', 'GBP/USD', 'USD/JPY']
            },
            {
                'date': today + timedelta(days=3),
                'time': '14:00 GMT',
                'event': 'US CPI (Inflation)',
                'impact': 'HIGH',
                'forecast': '3.2%',
                'previous': '3.4%',
                'pairs': ['EUR/USD', 'GBP/USD', 'USD/JPY']
            },
            {
                'date': today + timedelta(days=5),
                'time': '19:00 GMT',
                'event': 'FOMC Meeting Minutes',
                'impact': 'HIGH',
                'forecast': '',
                'previous': '',
                'pairs': ['ALL']
            },
            {
                'date': today + timedelta(days=7),
                'time': '12:00 GMT',
                'event': 'ECB Interest Rate',
                'impact': 'HIGH',
                'forecast': '4.50%',
                'previous': '4.50%',
                'pairs': ['EUR/USD', 'EUR/GBP']
            },
        ]
        
        return sample_events
    
    def get_events_for_pair(self, pair, days=7):
        """Get events that affect a specific pair"""
        events = self.fetch_upcoming_events(days)
        
        relevant = []
        for event in events:
            if 'ALL' in event['pairs'] or pair in event['pairs']:
                relevant.append(event)
        
        return relevant
    
    def is_high_impact_event_near(self, pair, hours=2):
        """Check if high impact event within X hours"""
        events = self.fetch_upcoming_events(days=1)
        
        now = datetime.now()
        
        for event in events:
            event_time = self.parse_event_time(event['date'], event['time'])
            
            if event_time is None:
                continue
            
            hours_until = (event_time - now).total_seconds() / 3600
            
            if 0 <= hours_until <= hours:
                if event['impact'] in ['HIGH', 'VERY_HIGH']:
                    return True, event
        
        return False, None
    
    def parse_event_time(self, date, time_str):
        """Parse event datetime"""
        try:
            return datetime.combine(date.date(), datetime.strptime(time_str, '%H:%M GMT').time())
        except:
            return None
```

---

## News Sentiment Analyzer

```python
class NewsSentimentAnalyzer:
    """
    Analyze news sentiment and its impact on markets
    """
    
    # Keywords that indicate positive/negative sentiment
    POSITIVE_KEYWORDS = [
        'growth', 'surge', 'rally', 'gain', 'profit', 'beat', 'exceed',
        'bullish', 'optimistic', 'rise', 'increase', 'improve', 'strong'
    ]
    
    NEGATIVE_KEYWORDS = [
        'fall', 'drop', 'decline', 'loss', 'miss', 'below', 'bearish',
        'pessimistic', 'shrink', 'decrease', 'weak', 'concern', 'risk'
    ]
    
    def __init__(self):
        self.sentiment_history = []
    
    def analyze_headline(self, headline):
        """
        Analyze headline sentiment
        
        Returns: sentiment score (-1 to 1), sentiment label
        """
        headline = headline.lower()
        
        positive_count = sum(1 for word in self.POSITIVE_KEYWORDS if word in headline)
        negative_count = sum(1 for word in self.NEGATIVE_KEYWORDS if word in headline)
        
        total = positive_count + negative_count
        
        if total == 0:
            return 0, 'NEUTRAL'
        
        score = (positive_count - negative_count) / total
        
        if score > 0.2:
            label = 'POSITIVE'
        elif score < -0.2:
            label = 'NEGATIVE'
        else:
            label = 'NEUTRAL'
        
        return score, label
    
    def get_market_sentiment(self, headlines):
        """
        Get overall market sentiment from multiple headlines
        
        Returns: overall sentiment, affected pairs
        """
        scores = []
        affected_pairs = set()
        
        for headline in headlines:
            score, label = self.analyze_headline(headline)
            scores.append(score)
            
            # Determine affected pairs from keywords
            if any(word in headline.lower() for word in ['us', 'dollar', 'fed']):
                affected_pairs.update(['EUR/USD', 'GBP/USD', 'USD/JPY'])
            if any(word in headline.lower() for word in ['europe', 'ecb', 'euro']):
                affected_pairs.update(['EUR/USD', 'EUR/GBP'])
            if any(word in headline.lower() for word in ['uk', 'britain', 'boe', 'pound']):
                affected_pairs.update(['GBP/USD', 'EUR/GBP'])
            if any(word in headline.lower() for word in ['japan', 'boj', 'yen']):
                affected_pairs.update(['USD/JPY'])
        
        avg_score = sum(scores) / len(scores) if scores else 0
        
        if avg_score > 0.2:
            sentiment = 'BULLISH'
        elif avg_score < -0.2:
            sentiment = 'BEARISH'
        else:
            sentiment = 'NEUTRAL'
        
        return sentiment, list(affected_pairs)
    
    def should_filter_trade(self, pair, news_headlines):
        """
        Determine if news suggests filtering a trade
        
        Returns: (should_filter, reason)
        """
        sentiment, affected_pairs = self.get_market_sentiment(news_headlines)
        
        # If pair is affected by strong sentiment
        if pair in affected_pairs:
            # If very bullish/bearish, may want to avoid counter-trend trades
            # But this is optional - traders can use this as additional filter
            pass
        
        return False, "No filter needed"
```

---

## News-Aware Trade Manager

```python
class NewsAwareTradeManager:
    """
    Integrate news analysis with trade management
    """
    
    def __init__(self, config):
        self.calendar = EconomicCalendar()
        self.sentiment = NewsSentimentAnalyzer()
        self.minutes_before_news = config.get('minutes_before_news', 30)
        self.minutes_after_news = config.get('minutes_after_news', 30)
        self.close_before_high_impact = config.get('close_before_high_impact', True)
        self.pairs_to_monitor = config.get('pairs_to_monitor', ['EUR/USD', 'GBP/USD', 'USD/JPY'])
    
    def should_open_trade(self, pair, signal, current_time):
        """
        Check if should open trade considering news
        """
        
        # Check for nearby high impact events
        is_near, event = self.calendar.is_high_impact_event_near(
            pair, 
            hours=self.minutes_before_news/60
        )
        
        if is_near and event['impact'] == 'VERY_HIGH':
            return False, f"VERY_HIGH impact event within {self.minutes_before_news}min: {event['event']}"
        
        if is_near and event['impact'] == 'HIGH':
            # Optional: allow but warn
            return True, f"Warning: HIGH impact event within {self.minutes_before_news}min: {event['event']}"
        
        return True, "OK"
    
    def should_close_positions(self, open_positions, current_time):
        """
        Check if should close positions before news
        """
        
        positions_to_close = []
        
        for position in open_positions:
            pair = position['pair']
            
            is_near, event = self.calendar.is_high_impact_event_near(
                pair,
                hours=self.minutes_before_news/60
            )
            
            if is_near and self.close_before_high_impact:
                if event['impact'] in ['HIGH', 'VERY_HIGH']:
                    positions_to_close.append({
                        'position': position,
                        'reason': f"Closing before {event['event']}"
                    })
        
        return positions_to_close
    
    def get_trading_recommendations(self, pair):
        """
        Get current trading recommendations based on news
        """
        
        events = self.calendar.get_events_for_pair(pair, days=1)
        
        recommendations = {
            'pair': pair,
            'should_trade': True,
            'reason': 'No major news events',
            'upcoming_events': [],
            'sentiment': 'NEUTRAL'
        }
        
        # Check for today's events
        today_events = [e for e in events if e['date'].date() == datetime.now().date()]
        
        if today_events:
            recommendations['upcoming_events'] = today_events
            
            # Check for high impact
            high_impact = [e for e in today_events if e['impact'] == 'HIGH']
            
            if high_impact:
                recommendations['should_trade'] = False
                recommendations['reason'] = f"High impact events today: {[e['event'] for e in high_impact]}"
        
        return recommendations
    
    def create_calendar_entry(self, date, time, event, impact='MEDIUM'):
        """Manually add an event to the calendar"""
        self.calendar.events.append({
            'date': date,
            'time': time,
            'event': event,
            'impact': impact,
            'pairs': self.pairs_to_monitor
        })
```

---

## Usage Example

```python
# Initialize
config = {
    'minutes_before_news': 30,
    'minutes_after_news': 30,
    'close_before_high_impact': True,
    'pairs_to_monitor': ['EUR/USD', 'GBP/USD', 'USD/JPY']
}

news_manager = NewsAwareTradeManager(config)

# Check if should open trade
can_trade, reason = news_manager.should_open_trade('EUR/USD', 'BUY', datetime.now())
print(f"Can trade: {can_trade}, Reason: {reason}")

# Get recommendations
recs = news_manager.get_trading_recommendations('EUR/USD')
print(f"Recommendations: {recs}")

# Check if should close positions before news
positions = [
    {'pair': 'EUR/USD', 'direction': 'BUY', 'entry_price': 1.1000}
]
to_close = news_manager.should_close_positions(positions, datetime.now())
print(f"Positions to close: {to_close}")
```
