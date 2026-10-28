"""
Web tools: open_website, search_web, get_weather.

SAFE-permission tools that query real-time web knowledge, weather, or open URLs.
"""

from __future__ import annotations

import re
import urllib.parse
import webbrowser
import httpx

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.web")


@register(
    name="open_website",
    description="Open a website URL in the default browser (e.g. youtube.com, github.com)",
    permission=PermissionLevel.SAFE,
    category="web",
    parameters=[
        ToolParameter(
            name="url",
            type="string",
            description="The URL or website domain to open (e.g., 'youtube.com', 'https://github.com')",
        ),
    ],
)
def open_website(url: str) -> ToolResult:
    """Open a URL in the default web browser."""
    url = url.strip()

    # Add protocol if missing
    if not url.startswith(("http://", "https://")):
        if "." not in url:
            url = f"{url}.com"
        url = f"https://{url}"

    try:
        webbrowser.open(url)
        return ToolResult(
            success=True,
            message=f"Opening {url}...",
            data={"url": url},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"{type(e).__name__}: {e}",
            message=f"Failed to open '{url}'.",
        )


@register(
    name="get_weather",
    description="Get real-time weather and temperature for any city or location",
    permission=PermissionLevel.SAFE,
    category="web",
    parameters=[
        ToolParameter(
            name="location",
            type="string",
            description="City or region name (e.g., 'Tokyo', 'London', 'New York', 'Mumbai').",
        ),
    ],
)
def get_weather(location: str) -> ToolResult:
    """Fetch live weather from wttr.in format API without external keys."""
    loc_clean = location.strip()
    if not loc_clean:
        loc_clean = ""

    url = f"https://wttr.in/{urllib.parse.quote_plus(loc_clean)}?format=%l:+%C,+%t+(feels+like+%f)"
    try:
        resp = httpx.get(url, timeout=5.0, headers={"User-Agent": "curl/7.68.0"})
        if resp.status_code == 200 and resp.text.strip():
            raw = resp.text.strip()
            # Clean weird characters
            clean_weather = re.sub(r"\s+", " ", raw)
            return ToolResult(
                success=True,
                message=f"Current weather: {clean_weather}.",
                data={"weather": clean_weather, "location": loc_clean},
            )
    except Exception as e:
        logger.warning(f"Live weather fetch failed: {e}")

    return ToolResult(
        success=False,
        error="Weather service temporarily unavailable",
        message=f"Could not retrieve weather for '{loc_clean}'.",
    )


@register(
    name="search_web",
    description="Search the web for real-time information, facts, news, or answers and return summaries",
    permission=PermissionLevel.SAFE,
    category="web",
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="The search query (e.g., 'who won the match yesterday', 'latest Python version', 'population of Tokyo')",
        ),
    ],
)
def search_web(query: str) -> ToolResult:
    """
    Search the web directly and return factual snippets.
    Falls back to opening Google search in browser tab if no results found.
    """
    query = query.strip()

    if not query:
        return ToolResult(
            success=False,
            error="Empty search query",
            message="Please provide something to search for.",
        )

    # 1. Try DuckDuckGo live search via ddgs
    try:
        from ddgs import DDGS

        ddgs_client = DDGS(timeout=5)
        # Try lite backend first for reliability
        results = list(ddgs_client.text(query, backend="lite", max_results=3))
        if not results:
            results = list(ddgs_client.text(query, max_results=3))

        if results:
            snippets = []
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "").strip()
                if body:
                    snippets.append(f"{title}: {body}")

            summary = " ".join(snippets[:2])
            # Truncate summary if too long for TTS
            if len(summary) > 400:
                summary = summary[:397] + "..."

            return ToolResult(
                success=True,
                message=f"According to search results: {summary}",
                data={"query": query, "results": results, "summary": summary},
            )
    except Exception as e:
        logger.info(f"Direct search retrieval failed ({e}), falling back to browser tab.")

    # 2. Fallback: open browser search tab
    search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
    try:
        webbrowser.open(search_url)
        return ToolResult(
            success=True,
            message=f"I couldn't fetch the summary directly, so I opened the search results for '{query}' in your browser.",
            data={"query": query, "url": search_url},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"{type(e).__name__}: {e}",
            message=f"Failed to search for '{query}'.",
        )
