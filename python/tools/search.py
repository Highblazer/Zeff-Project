"""
Web Search Tool - Search the web using Brave API
"""

from python.helpers.tools import Tool, Response
import asyncio
import requests
import os


class Search(Tool):
    """Web search using Brave Search API"""
    
    name = "search"
    description = "Search the web for information"
    parameters = {
        "query": {
            "type": "string",
            "description": "Search query",
            "required": True
        },
        "count": {
            "type": "integer",
            "description": "Number of results (1-10)",
            "default": 5
        }
    }
    
    def __init__(self, agent):
        super().__init__(agent)
        # Get API key from environment
        self.api_key = os.environ.get("BRAVE_API_KEY", "")
        self.base_url = "https://api.brave.com/res/v1/web/search"
    
    async def execute(self, **kwargs) -> Response:
        query = kwargs.get("query", "")
        count = kwargs.get("count", 5)
        
        if not query:
            return Response(message="Error: No query provided", break_loop=False)
        
        if not self.api_key:
            # Fall back to simple HTTP request
            return await self._search_simple(query, count)
        
        try:
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key
            }
            
            params = {
                "q": query,
                "count": min(count, 10)
            }
            
            response = await asyncio.to_thread(
                requests.get,
                self.base_url,
                headers=headers,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return self._format_results(data, query)
            else:
                return Response(
                    message=f"Search error: {response.status_code}",
                    break_loop=False
                )
                
        except Exception as e:
            return Response(
                message=f"Search failed: {str(e)}",
                break_loop=False
            )
    
    async def _search_simple(self, query: str, count: int) -> Response:
        """Simple search using DuckDuckGo or similar"""
        try:
            # Try using a simple search endpoint
            url = "https://html.duckduckgo.com/html/"
            data = {"q": query}
            
            response = await asyncio.to_thread(requests.post, url, data=data, timeout=10)
            
            if response.status_code == 200:
                # Parse results
                results = []
                import re
                
                # Simple regex to extract titles and links
                pattern = r'<a class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>'
                matches = re.findall(pattern, response.text)[:count]
                
                for url, title in matches:
                    results.append(f"• {title.strip()}\n  {url}")
                
                if results:
                    return Response(
                        message=f"Search results for '{query}':\n\n" + "\n\n".join(results),
                        break_loop=False
                    )
                else:
                    return Response(
                        message=f"No results found for '{query}'",
                        break_loop=False
                    )
            else:
                return Response(
                    message=f"Search failed: {response.status_code}",
                    break_loop=False
                )
                
        except Exception as e:
            return Response(
                message=f"Search error: {str(e)}",
                break_loop=False
            )
    
    def _format_results(self, data: dict, query: str) -> Response:
        """Format Brave API results"""
        try:
            results = data.get("web", {}).get("results", [])
            
            if not results:
                return Response(
                    message=f"No results found for '{query}'",
                    break_loop=False
                )
            
            formatted = []
            for r in results[:5]:
                title = r.get("title", "No title")
                url = r.get("url", "")
                desc = r.get("description", "")[:100]
                formatted.append(f"• {title}\n  {url}\n  {desc}...")
            
            return Response(
                message=f"Search results for '{query}':\n\n" + "\n\n".join(formatted),
                break_loop=False
            )
            
        except Exception as e:
            return Response(
                message=f"Error parsing results: {str(e)}",
                break_loop=False
            )


__all__ = ["Search"]
