"""
Simple .env file loader for Binary Rogue.
Loads environment variables from .env files without requiring python-dotenv package.
"""

import os


def load_dotenv(dotenv_path: str = None):
    """Load environment variables from a .env file.

    Searches in order:
    1. Explicit path if provided
    2. /root/.openclaw/workspace/.env
    3. .env in current working directory
    """
    search_paths = []

    if dotenv_path:
        search_paths.append(dotenv_path)

    search_paths.extend([
        '/root/.openclaw/workspace/.env',
        os.path.join(os.getcwd(), '.env'),
    ])

    for path in search_paths:
        path = os.path.abspath(path)
        if os.path.isfile(path):
            _parse_dotenv(path)
            return True

    return False


def _parse_dotenv(filepath: str):
    """Parse a .env file and set environment variables."""
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue

            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()

            # Strip surrounding quotes if present
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]

            os.environ.setdefault(key, value)
