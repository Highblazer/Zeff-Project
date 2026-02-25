#!/usr/bin/env python3
"""
News Collection Engine — Brave News API + content extraction.

Collects trending news, categorizes by bot relevance, scores articles,
and stores them via news_store.

Standalone: python lib/news_collector.py
"""

import hashlib
import os
import re
import sys
import time
import requests
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.credentials import _load_dotenv
from lib.logging_config import get_logger
from lib.news_store import append_articles, update_memory_files

_load_dotenv()
log = get_logger('news_collector', 'news_collector.log')

BRAVE_API_KEY = os.environ.get('BRAVE_SEARCH_API_KEY', '') or os.environ.get('BRAVE_API_KEY', '')

# ── Topic definitions ──

TOPICS = {
    'tradebot': [
        'forex market news today',
        'economic calendar events this week',
        'central bank interest rate decisions',
        'FX currency pair analysis',
        'commodities gold oil prices',
        'market volatility VIX',
    ],
    'natalia': [
        'AI artificial intelligence news',
        'LLM large language model releases',
        'AI agent framework developments',
        'API developer tool changes 2026',
        'machine learning breakthroughs',
    ],
}

# ── Relevance keywords ──

TRADEBOT_KEYWORDS = [
    'forex', 'fx', 'currency', 'usd', 'eur', 'gbp', 'jpy', 'aud', 'cad', 'chf',
    'central bank', 'fed', 'ecb', 'boj', 'rba', 'interest rate', 'inflation',
    'gdp', 'nonfarm', 'payroll', 'employment', 'cpi', 'pmi', 'trade balance',
    'oil', 'gold', 'commodity', 'bond', 'yield', 'volatility', 'vix',
    'market', 'trading', 'rally', 'selloff', 'bearish', 'bullish',
]

NATALIA_KEYWORDS = [
    'ai', 'artificial intelligence', 'llm', 'gpt', 'claude', 'gemini', 'llama',
    'openai', 'anthropic', 'google', 'meta', 'mistral', 'agent', 'framework',
    'api', 'sdk', 'developer', 'tool', 'machine learning', 'ml', 'neural',
    'transformer', 'diffusion', 'model', 'benchmark', 'reasoning', 'rag',
    'langchain', 'autogen', 'crewai', 'embeddings', 'fine-tuning', 'open source',
]


def brave_news_search(query: str, count: int = 5) -> list:
    """Search via Brave News API. Returns list of article dicts."""
    if not BRAVE_API_KEY:
        log.warning('No Brave API key configured')
        return []
    try:
        resp = requests.get(
            'https://api.search.brave.com/res/v1/news/search',
            headers={'Accept': 'application/json', 'X-Subscription-Token': BRAVE_API_KEY},
            params={'q': query, 'count': min(count, 10)},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for r in data.get('results', []):
                results.append({
                    'title': r.get('title', ''),
                    'url': r.get('url', ''),
                    'description': r.get('description', ''),
                    'source': r.get('meta_url', {}).get('hostname', '') if isinstance(r.get('meta_url'), dict) else '',
                    'age': r.get('age', ''),
                })
            return results
        else:
            log.warning(f'Brave news search HTTP {resp.status_code} for "{query}"')
    except Exception as e:
        log.warning(f'Brave news search failed: {e}')
    return []


def _extract_content(url: str, timeout: int = 10) -> str:
    """Lightweight content extraction from a URL."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return ''
        html = resp.text
        # Strip scripts, styles, nav
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # Get text
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:3000]
    except Exception:
        return ''


def _score_relevance(article: dict, bot_target: str) -> float:
    """Keyword-based 0.0–1.0 relevance scoring."""
    text = (
        (article.get('title', '') + ' ' + article.get('description', '')).lower()
    )
    keywords = TRADEBOT_KEYWORDS if bot_target == 'tradebot' else NATALIA_KEYWORDS
    hits = sum(1 for kw in keywords if kw in text)
    # Normalize: 5+ keyword hits = 1.0
    score = min(hits / 5.0, 1.0)
    return round(score, 2)


def _categorize_article(article: dict) -> str:
    """Determine bot target: 'tradebot', 'natalia', or 'both'."""
    text = (article.get('title', '') + ' ' + article.get('description', '')).lower()
    trade_hits = sum(1 for kw in TRADEBOT_KEYWORDS if kw in text)
    natalia_hits = sum(1 for kw in NATALIA_KEYWORDS if kw in text)

    if trade_hits >= 2 and natalia_hits >= 2:
        return 'both'
    elif trade_hits > natalia_hits:
        return 'tradebot'
    else:
        return 'natalia'


def _make_article_id(url: str) -> str:
    """Generate a deterministic article ID from URL."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def collect_news() -> list:
    """Main orchestrator: query all topics, deduplicate, score, extract content.

    Returns list of structured article dicts.
    """
    log.info('Starting news collection...')
    all_articles = []
    seen_urls = set()
    extraction_budget = 120  # seconds
    extraction_start = time.time()

    # Fetch from all topic queries
    for bot_target, queries in TOPICS.items():
        for query in queries:
            results = brave_news_search(query, count=5)
            for r in results:
                url = r.get('url', '')
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                article = {
                    'id': _make_article_id(url),
                    'title': r.get('title', ''),
                    'url': url,
                    'source': r.get('source', '') or _extract_source(url),
                    'description': r.get('description', ''),
                    'age': r.get('age', ''),
                    'extracted_at': datetime.now(timezone.utc).isoformat(),
                    'extraction_method': 'brave_news',
                    'full_content': '',
                    'summary': '',
                }

                # Categorize and score
                article['bot_target'] = _categorize_article(article)
                article['category'] = bot_target  # original query category
                article['relevance_score'] = _score_relevance(article, article['bot_target'])

                all_articles.append(article)

    log.info(f'Collected {len(all_articles)} unique articles from Brave News')

    # Content extraction within budget
    # Prioritize high-relevance articles
    all_articles.sort(key=lambda a: a.get('relevance_score', 0), reverse=True)
    extracted = 0
    for article in all_articles:
        elapsed = time.time() - extraction_start
        if elapsed > extraction_budget:
            log.info(f'Extraction budget exhausted ({elapsed:.0f}s), extracted {extracted} articles')
            break
        content = _extract_content(article['url'], timeout=8)
        if content:
            article['full_content'] = content
            article['summary'] = content[:500]
            article['extraction_method'] = 'full_extract'
            extracted += 1

    log.info(f'Content extracted for {extracted}/{len(all_articles)} articles')
    return all_articles


def _extract_source(url: str) -> str:
    """Extract hostname from URL as source name."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ''
    except Exception:
        return ''


def run_collection():
    """Run a full collection cycle: collect, store, update memory files."""
    log.info('=== News collection cycle starting ===')
    articles = collect_news()
    if articles:
        added = append_articles(articles)
        log.info(f'Stored {added} new articles')
    else:
        log.warning('No articles collected')

    update_memory_files()
    log.info('=== News collection cycle complete ===')
    return articles


if __name__ == '__main__':
    run_collection()
