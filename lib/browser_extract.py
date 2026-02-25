#!/usr/bin/env python3
"""
Browser Content Extraction — full-page text extraction for Natalia's research.

Two strategies:
  1. Browser relay (CDP via ws://127.0.0.1:18792) — JS-rendered sites via Chrome extension
  2. HTTP + BeautifulSoup — reliable fallback, strips boilerplate, finds article body

Usage:
    from lib.browser_extract import extract_page_content, extract_multiple

    content = extract_page_content("https://example.com/article")
    results = extract_multiple(["https://a.com", "https://b.com"], max_urls=5, budget_seconds=60)
"""

import json
import logging
import re
import time
from urllib.parse import urlparse

import requests

try:
    import websocket as ws_client
except ImportError:
    ws_client = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

_log = logging.getLogger('browser_extract')

# ── Limits ──────────────────────────────────────────────────
MAX_CHARS_PER_PAGE = 10_000
HTTP_TIMEOUT = 5
RELAY_TIMEOUT = 8
RELAY_WS_URL = 'ws://127.0.0.1:18792'

# Domains where text extraction is useless (video, social feeds, etc.)
_SKIP_DOMAINS = {
    'youtube.com', 'www.youtube.com', 'm.youtube.com',
    'twitter.com', 'x.com',
    'reddit.com', 'www.reddit.com', 'old.reddit.com',
    'instagram.com', 'www.instagram.com',
    'tiktok.com', 'www.tiktok.com',
    'facebook.com', 'www.facebook.com', 'm.facebook.com',
    'linkedin.com', 'www.linkedin.com',
    'discord.com', 'discord.gg',
    'twitch.tv', 'www.twitch.tv',
    'spotify.com', 'open.spotify.com',
}

# HTML tags that are boilerplate / noise
_STRIP_TAGS = [
    'nav', 'footer', 'header', 'aside', 'script', 'style', 'noscript',
    'iframe', 'svg', 'form', 'button',
]

# CSS classes/ids that signal boilerplate
_BOILERPLATE_PATTERNS = re.compile(
    r'(sidebar|widget|advert|promo|popup|modal|cookie|consent|newsletter|'
    r'social-share|share-button|related-post|comment|disqus|signup|subscribe)',
    re.IGNORECASE,
)

_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


# ── Public API ──────────────────────────────────────────────

def extract_page_content(url: str) -> dict:
    """Extract full text from a single URL.

    Returns dict with keys:
        url, title, content, char_count, method, success, error
    """
    if _should_skip(url):
        return _result(url, success=False, error='skipped: domain blocklisted')

    # Strategy 1: try CDP relay
    result = _try_relay(url)
    if result['success']:
        return result

    # Strategy 2: HTTP + BeautifulSoup
    result = _try_http(url)
    return result


def extract_multiple(urls: list, max_urls: int = 5, budget_seconds: int = 60) -> list:
    """Extract content from multiple URLs within a time budget.

    Args:
        urls: List of URLs to extract.
        max_urls: Maximum number of URLs to attempt.
        budget_seconds: Total time budget in seconds.

    Returns:
        List of result dicts (same shape as extract_page_content).
    """
    results = []
    deadline = time.monotonic() + budget_seconds
    attempted = 0

    for url in urls:
        if attempted >= max_urls:
            break
        if time.monotonic() >= deadline:
            _log.info(f'Budget exhausted after {attempted} URLs')
            break

        remaining = deadline - time.monotonic()
        if remaining < 2:
            _log.info('Less than 2s remaining, stopping extraction')
            break

        attempted += 1
        try:
            result = extract_page_content(url)
            results.append(result)
        except Exception as e:
            _log.warning(f'Unexpected error extracting {url}: {e}')
            results.append(_result(url, success=False, error=str(e)))

    return results


# ── Relay Strategy (CDP) ───────────────────────────────────

def _check_relay_available() -> bool:
    """Quick check if the browser relay WebSocket is reachable."""
    if ws_client is None:
        return False
    try:
        sock = ws_client.create_connection(RELAY_WS_URL, timeout=2)
        sock.close()
        return True
    except Exception:
        return False


def _try_relay(url: str) -> dict:
    """Extract page content via CDP browser relay."""
    if ws_client is None:
        return _result(url, success=False, error='websocket-client not installed')

    try:
        sock = ws_client.create_connection(RELAY_WS_URL, timeout=2)
    except Exception:
        return _result(url, success=False, error='relay not available')

    try:
        # Navigate to URL
        nav_msg = json.dumps({
            'id': 1,
            'method': 'Page.navigate',
            'params': {'url': url}
        })
        sock.send(nav_msg)
        sock.settimeout(RELAY_TIMEOUT)

        # Wait for navigation response
        _recv_until_id(sock, 1)

        # Give page time to render
        time.sleep(1.5)

        # Extract body text via Runtime.evaluate
        eval_msg = json.dumps({
            'id': 2,
            'method': 'Runtime.evaluate',
            'params': {
                'expression': (
                    '(() => {'
                    '  const title = document.title || "";'
                    '  const body = document.body ? document.body.innerText : "";'
                    '  return JSON.stringify({title, body});'
                    '})()'
                ),
                'returnByValue': True,
            }
        })
        sock.send(eval_msg)
        resp = _recv_until_id(sock, 2)

        value = resp.get('result', {}).get('result', {}).get('value', '{}')
        data = json.loads(value)
        title = data.get('title', '')
        body = data.get('body', '').strip()

        if not body or len(body) < 100:
            return _result(url, success=False, error='relay: content too short')

        body = body[:MAX_CHARS_PER_PAGE]
        return _result(url, success=True, title=title, content=body, method='relay')

    except Exception as e:
        return _result(url, success=False, error=f'relay error: {e}')
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _recv_until_id(sock, target_id: int, max_msgs: int = 30) -> dict:
    """Read WebSocket messages until we get the one matching target_id."""
    for _ in range(max_msgs):
        raw = sock.recv()
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if msg.get('id') == target_id:
            return msg
    return {}


# ── HTTP + BeautifulSoup Strategy ──────────────────────────

def _try_http(url: str) -> dict:
    """Extract page content via direct HTTP fetch + HTML parsing."""
    try:
        resp = requests.get(
            url,
            headers={'User-Agent': _USER_AGENT},
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as e:
        return _result(url, success=False, error=f'http error: {e}')

    if resp.status_code != 200:
        return _result(url, success=False, error=f'http {resp.status_code}')

    # Check content type — skip non-HTML
    ctype = resp.headers.get('Content-Type', '')
    if 'text/html' not in ctype and 'application/xhtml' not in ctype:
        return _result(url, success=False, error=f'non-html content: {ctype}')

    if BeautifulSoup is None:
        # Fallback: regex-based extraction (like the existing browser tool)
        return _try_http_regex(url, resp.text)

    soup = BeautifulSoup(resp.text, 'html.parser')
    title = soup.title.string.strip() if soup.title and soup.title.string else ''
    content = _clean_html(soup)

    if not content or len(content) < 100:
        return _result(url, success=False, error='http: content too short after cleaning')

    content = content[:MAX_CHARS_PER_PAGE]
    return _result(url, success=True, title=title, content=content, method='http')


def _try_http_regex(url: str, html: str) -> dict:
    """Bare-bones extraction when BeautifulSoup is not available."""
    # Extract title
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ''

    # Strip script/style
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) < 100:
        return _result(url, success=False, error='regex: content too short')

    text = text[:MAX_CHARS_PER_PAGE]
    return _result(url, success=True, title=title, content=text, method='http-regex')


def _clean_html(soup) -> str:
    """Strip boilerplate from parsed HTML and extract article body text."""
    # Remove boilerplate tags
    for tag_name in _STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove elements with boilerplate class/id patterns
    for el in soup.find_all(True):
        classes = ' '.join(el.get('class', []))
        el_id = el.get('id', '')
        combined = f'{classes} {el_id}'
        if _BOILERPLATE_PATTERNS.search(combined):
            el.decompose()

    # Try to find the main content container
    content_el = (
        soup.find('article')
        or soup.find('main')
        or soup.find('div', role='main')
        or soup.find('div', class_=re.compile(r'(article|content|post|entry|story)', re.I))
        or soup.find('div', id=re.compile(r'(article|content|post|entry|story)', re.I))
    )

    if content_el and len(content_el.get_text(strip=True)) > 200:
        text = content_el.get_text(separator='\n', strip=True)
    else:
        # Fall back to body
        body = soup.find('body')
        text = body.get_text(separator='\n', strip=True) if body else soup.get_text(separator='\n', strip=True)

    # Collapse excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Helpers ────────────────────────────────────────────────

def _should_skip(url: str) -> bool:
    """Check if URL is on the domain blocklist."""
    try:
        host = urlparse(url).hostname or ''
        return host.lower() in _SKIP_DOMAINS
    except Exception:
        return False


def _result(url: str, success: bool, title: str = '', content: str = '',
            method: str = '', error: str = '') -> dict:
    """Build a standardized result dict."""
    return {
        'url': url,
        'title': title,
        'content': content,
        'char_count': len(content),
        'method': method,
        'success': success,
        'error': error,
    }
