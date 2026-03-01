#!/usr/bin/env python3
"""
News Intelligence Store — JSON feed storage + bot memory file writer.

Feed location: /root/.openclaw/workspace/news/feed.json
Memory files:  /root/.openclaw/workspace/memory/tradebot-intel.md
               /root/.openclaw/workspace/memory/natalia-intel.md
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.atomic_write import atomic_json_write, atomic_text_write
from lib.logging_config import get_logger

log = get_logger('news_store', 'news_store.log')

FEED_PATH = '/root/.openclaw/workspace/news/feed.json'
MEMORY_DIR = '/root/.openclaw/workspace/memory'
MAX_ARTICLE_AGE_HOURS = 48
MAX_FEED_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def _empty_feed() -> dict:
    """Return an empty feed structure."""
    return {
        'version': 1,
        'last_updated': '',
        'last_collection_at': '',
        'article_count': 0,
        'articles': [],
    }


def _load_feed() -> dict:
    """Load feed.json or return empty structure."""
    try:
        if os.path.isfile(FEED_PATH):
            with open(FEED_PATH, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict) and 'articles' in data:
                return data
    except Exception as e:
        log.warning(f'Failed to load feed: {e}')
    return _empty_feed()


def _save_feed(feed: dict):
    """Atomic write with updated metadata."""
    feed['last_updated'] = datetime.now(timezone.utc).isoformat()
    feed['article_count'] = len(feed.get('articles', []))
    atomic_json_write(FEED_PATH, feed)


def _prune_old_articles(feed: dict) -> dict:
    """Remove articles >48h old, enforce 5MB cap."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_ARTICLE_AGE_HOURS)
    cutoff_str = cutoff.isoformat()

    articles = feed.get('articles', [])
    # Remove old articles
    articles = [a for a in articles if a.get('extracted_at', '') > cutoff_str]

    # Enforce size cap — remove oldest first
    articles.sort(key=lambda a: a.get('relevance_score', 0), reverse=True)
    while len(json.dumps(articles)) > MAX_FEED_SIZE_BYTES and articles:
        articles.pop()

    feed['articles'] = articles
    return feed


def append_articles(new_articles: list) -> int:
    """Merge new articles, deduplicate by URL, prune, save. Returns count added."""
    feed = _load_feed()
    existing_urls = {a.get('url') for a in feed.get('articles', [])}

    added = 0
    for article in new_articles:
        url = article.get('url', '')
        if url and url not in existing_urls:
            feed['articles'].append(article)
            existing_urls.add(url)
            added += 1

    feed['last_collection_at'] = datetime.now(timezone.utc).isoformat()
    feed = _prune_old_articles(feed)
    _save_feed(feed)

    log.info(f'Appended {added} articles (total: {feed["article_count"]})')
    return added


def get_feed(bot: str = None, hours: int = 24) -> list:
    """Query feed filtered by bot_target and time range."""
    feed = _load_feed()
    articles = feed.get('articles', [])

    # Filter by time range
    if hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()
        articles = [a for a in articles if a.get('extracted_at', '') > cutoff_str]

    # Filter by bot target
    if bot:
        articles = [
            a for a in articles
            if a.get('bot_target') == bot or a.get('bot_target') == 'both'
        ]

    # Sort by relevance score descending
    articles.sort(key=lambda a: a.get('relevance_score', 0), reverse=True)
    return articles


def get_feed_metadata() -> dict:
    """Lightweight metadata query (no article bodies)."""
    feed = _load_feed()
    tradebot_count = sum(
        1 for a in feed.get('articles', [])
        if a.get('bot_target') in ('tradebot', 'both')
    )
    natalia_count = sum(
        1 for a in feed.get('articles', [])
        if a.get('bot_target') in ('natalia', 'both')
    )
    return {
        'article_count': feed.get('article_count', 0),
        'last_updated': feed.get('last_updated', ''),
        'last_collection_at': feed.get('last_collection_at', ''),
        'tradebot_count': tradebot_count,
        'natalia_count': natalia_count,
    }


def is_stale(max_age_seconds: int = 3600) -> bool:
    """Check if collection is needed (feed older than max_age_seconds)."""
    feed = _load_feed()
    last = feed.get('last_collection_at', '')
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return age > max_age_seconds
    except Exception:
        return True


def update_memory_files():
    """Write bot intelligence briefs to memory files.

    - memory/tradebot-intel.md — top 15 market/economic headlines
    - memory/natalia-intel.md — top 15 AI/LLM/tool headlines
    """
    os.makedirs(MEMORY_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    for bot, filename in [('tradebot', 'tradebot-intel.md'), ('natalia', 'natalia-intel.md')]:
        articles = get_feed(bot=bot, hours=24)[:15]
        lines = [
            f'# {bot.upper()} Intelligence Brief',
            f'> Auto-generated {now} | {len(articles)} articles',
            '',
        ]

        if not articles:
            lines.append('No recent intelligence available.')
        else:
            for i, a in enumerate(articles, 1):
                title = a.get('title', 'Untitled')
                source = a.get('source', 'unknown')
                score = a.get('relevance_score', 0)
                desc = a.get('description', '') or a.get('summary', '')
                # Truncate excerpt to 200 chars
                excerpt = desc[:200].rstrip() + ('...' if len(desc) > 200 else '')
                age = a.get('age', '')
                age_str = f' | {age}' if age else ''

                lines.append(f'### {i}. {title}')
                lines.append(f'**Source:** {source}{age_str} | **Relevance:** {score:.1f}')
                if excerpt:
                    lines.append(f'> {excerpt}')
                lines.append('')

        filepath = os.path.join(MEMORY_DIR, filename)
        atomic_text_write(filepath, '\n'.join(lines) + '\n')
        log.info(f'Wrote {filepath} ({len(articles)} articles)')


def get_natalia_intel(hours: int = 24) -> list:
    """Read Natalia's analyzed intelligence from memory/tradebot-intel-natalia.md.

    Returns a list of dicts with keys: title, impact, action, timestamp.
    Trading bots can call this to get Natalia's curated market intelligence
    separate from the auto-generated headline feed.
    """
    filepath = os.path.join(MEMORY_DIR, 'tradebot-intel-natalia.md')
    if not os.path.isfile(filepath):
        return []

    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except OSError as e:
        log.warning(f'Failed to read natalia intel: {e}')
        return []

    entries = []
    current_ts = ''
    current_entry = None

    for line in content.split('\n'):
        line = line.strip()

        # Parse timestamp headers: ### 2026-02-26 14:30 UTC
        if line.startswith('### ') and 'UTC' in line:
            current_ts = line[4:].strip()
            continue

        # Parse finding lines: - **Title** (impact: 0.7)
        if line.startswith('- **') and '(impact:' in line:
            # Save previous entry
            if current_entry:
                entries.append(current_entry)

            # Extract title and impact
            try:
                title_end = line.index('** (impact:')
                title = line[4:title_end]
                impact_str = line[title_end + 11:].rstrip(')')
                impact = float(impact_str)
            except (ValueError, IndexError):
                title = line[4:].split('**')[0]
                impact = 0.0

            current_entry = {
                'title': title,
                'impact': impact,
                'action': '',
                'description': '',
                'timestamp': current_ts,
            }
            continue

        # Parse description: > Some description text
        if line.startswith('> ') and current_entry:
            current_entry['description'] = line[2:]
            continue

        # Parse action: Action: ALERT trading bots...
        if line.startswith('Action:') and current_entry:
            current_entry['action'] = line[7:].strip()
            continue

    # Don't forget the last entry
    if current_entry:
        entries.append(current_entry)

    # Filter by recency if hours specified
    if hours and entries:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M')
            entries = [e for e in entries
                       if e.get('timestamp', '') >= cutoff_str or not e.get('timestamp')]
        except Exception:
            pass  # Return all entries if filtering fails

    return entries
