"""
Browser Tool - Web browsing and automation
"""

from python.helpers.tools import Tool, Response
import requests
from urllib.parse import urlparse
import re


class Browser(Tool):
    """Browse websites and extract content"""
    
    name = "browser"
    description = "Browse websites and extract information"
    parameters = {
        "url": {
            "type": "string",
            "description": "URL to visit",
            "required": True
        },
        "action": {
            "type": "string",
            "description": "Action: visit, extract, or screenshot",
            "default": "visit"
        }
    }
    
    async def execute(self, **kwargs) -> Response:
        url = kwargs.get("url", "")
        
        if not url:
            return Response(message="Error: No URL provided", break_loop=False)
        
        # Validate URL
        try:
            result = urlparse(url)
            if not result.scheme:
                url = "https://" + url
                result = urlparse(url)

            if not result.netloc:
                return Response(message="Error: Invalid URL", break_loop=False)

            # SSRF protection: only allow http/https schemes
            allowed_schemes = {"http", "https"}
            if result.scheme.lower() not in allowed_schemes:
                return Response(
                    message=f"Error: Only HTTP/HTTPS URLs are allowed (got {result.scheme})",
                    break_loop=False
                )

            # Block localhost/internal IPs
            blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "[::1]"}
            if result.hostname and result.hostname.lower() in blocked_hosts:
                return Response(
                    message="Error: Access to internal/localhost URLs is not allowed",
                    break_loop=False
                )

        except Exception as e:
            return Response(message=f"URL error: {str(e)}", break_loop=False)
        
        action = kwargs.get("action", "visit")
        
        try:
            if action == "visit" or action == "extract":
                return await self._fetch_page(url)
            elif action == "screenshot":
                return Response(
                    message="Screenshot not implemented - using text extraction instead",
                    break_loop=False
                )
            else:
                return Response(
                    message=f"Unknown action: {action}",
                    break_loop=False
                )
                
        except Exception as e:
            return Response(
                message=f"Browser error: {str(e)}",
                break_loop=False
            )
    
    async def _fetch_page(self, url: str) -> Response:
        """Fetch and extract content from a page"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return Response(
                message=f"Error: HTTP {response.status_code}",
                break_loop=False
            )
        
        # Extract title
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', response.text, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "No title"
        
        # Extract main content (simple approach)
        # Remove script and style tags
        content = re.sub(r'<script[^>]*>.*?</script>', '', response.text, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
        
        # Get text content
        content = re.sub(r'<[^>]+>', ' ', content)
        content = re.sub(r'\s+', ' ', content)
        content = content.strip()
        
        # Limit length
        max_chars = 3000
        if len(content) > max_chars:
            content = content[:max_chars] + "..."
        
        return Response(
            message=f"📄 {title}\n\n{url}\n\n{content}",
            break_loop=False,
            data={"title": title, "url": url}
        )


__all__ = ["Browser"]
