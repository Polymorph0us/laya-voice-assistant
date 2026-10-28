"""
Browser Automation & Web Perception Tools — Laya Assistant.

Provides Laya with the capability to act as an alternative of the user in the browser:
- `read_webpage`: Fetch, scrape, and extract structured text from any live webpage or URL.
- `browser_interact`: Full Playwright browser automation (navigate, click, fill forms, extract text, screenshot).
- `search_and_read`: Deep search that searches DuckDuckGo and reads the top webpage content for factual answers.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.browser")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _clean_html_text(html: str, max_chars: int = 4000) -> str:
    """Extract clean readable text and tables from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for element in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        element.decompose()

    # Extract tables into readable format
    for table in soup.find_all("table"):
        table_rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                table_rows.append(" | ".join(cells))
        if table_rows:
            table_text = "\n" + "\n".join(table_rows) + "\n"
            table.replace_with(table_text)

    # Get lines
    lines = [line.strip() for line in soup.get_text().splitlines() if line.strip()]
    text = "\n".join(lines)
    # Compress multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


@register(
    name="read_webpage",
    description="Read and extract the clean text, schedule, or table content from any webpage URL",
    permission=PermissionLevel.SAFE,
    category="web",
    parameters=[
        ToolParameter(
            name="url",
            type="string",
            description="The full URL of the webpage to read (e.g. 'https://atcoder.jp/contests/')",
        ),
        ToolParameter(
            name="max_chars",
            type="integer",
            description="Maximum characters of text to return (default 4000)",
            required=False,
            default=4000,
        ),
    ],
)
async def read_webpage(url: str, max_chars: int = 4000) -> ToolResult:
    """Fetch and extract text content from a web page."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    logger.info(f"Reading webpage: {url}")
    # 1. Fast HTTP fetch
    try:
        async with httpx.AsyncClient(headers=_DEFAULT_HEADERS, follow_redirects=True, timeout=12.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                text = _clean_html_text(resp.text, max_chars=max_chars)
                if len(text) > 100:
                    return ToolResult(
                        success=True,
                        message=f"Page content from {url}:\n\n{text}",
                        data={"url": url, "char_count": len(text)},
                    )
    except Exception as e:
        logger.debug(f"HTTP fetch failed for {url} ({e}), falling back to Playwright...")

    # 2. Playwright headless browser fallback (for JavaScript-heavy dynamic websites)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            await asyncio.sleep(1.0)
            html = await page.content()
            await browser.close()

            text = _clean_html_text(html, max_chars=max_chars)
            return ToolResult(
                success=True,
                message=f"Page content from {url} (rendered via browser):\n\n{text}",
                data={"url": url, "char_count": len(text)},
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message=f"Could not read webpage at '{url}': {e}",
        )


@register(
    name="browser_interact",
    description="Automate browser interactions on a webpage: navigate, click buttons, fill text boxes, extract text, or take screenshots",
    permission=PermissionLevel.SAFE,
    category="web",
    parameters=[
        ToolParameter(
            name="url",
            type="string",
            description="The URL to navigate to",
        ),
        ToolParameter(
            name="click_selector",
            type="string",
            description="Optional CSS or text selector to click (e.g. 'button#submit', 'text=Upcoming Contests')",
            required=False,
            default="",
        ),
        ToolParameter(
            name="fill_selector",
            type="string",
            description="Optional input selector to fill text into (e.g. 'input[name=\"search\"]')",
            required=False,
            default="",
        ),
        ToolParameter(
            name="fill_text",
            type="string",
            description="Text to fill into the input selector",
            required=False,
            default="",
        ),
        ToolParameter(
            name="take_screenshot",
            type="boolean",
            description="Whether to capture a screenshot of the resulting page",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="visible",
            type="boolean",
            description="Set to true to show the actual browser window on screen to the user",
            required=False,
            default=False,
        ),
    ],
)
async def browser_interact(
    url: str,
    click_selector: str = "",
    fill_selector: str = "",
    fill_text: str = "",
    take_screenshot: bool = False,
    visible: bool = False,
) -> ToolResult:
    """Drive Playwright browser to interact with a website."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            # Use native Windows MS Edge
            browser = await p.chromium.launch(channel="msedge", headless=not visible)
            page = await browser.new_page()
            await page.goto(url, timeout=25000, wait_until="domcontentloaded")
            await asyncio.sleep(1.0)

            # Perform input fill
            if fill_selector and fill_text:
                await page.fill(fill_selector, fill_text)
                await asyncio.sleep(0.5)

            # Perform click
            if click_selector:
                await page.click(click_selector)
                await asyncio.sleep(1.5)

            # Screenshot if requested
            screenshot_path = ""
            if take_screenshot:
                sc_dir = Path("logs/screenshots")
                sc_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = str(sc_dir / f"browser_{int(asyncio.get_running_loop().time())}.png")
                await page.screenshot(path=screenshot_path)

            html = await page.content()
            page_title = await page.title()
            await browser.close()

            text = _clean_html_text(html, max_chars=2500)
            sc_msg = f" Screenshot saved to {screenshot_path}." if screenshot_path else ""
            return ToolResult(
                success=True,
                message=f"Browser action completed on '{page_title}'.{sc_msg}\n\n{text[:1500]}",
                data={"url": url, "title": page_title, "screenshot": screenshot_path},
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message=f"Browser interaction error on '{url}': {e}",
        )


@register(
    name="search_and_read",
    description="Search the web and automatically read the top matching webpage to retrieve factual schedules, times, or information",
    permission=PermissionLevel.SAFE,
    category="web",
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="Search query (e.g. 'AtCoder beginner contest October 2026 schedule', 'premier league fixtures')",
        ),
    ],
)
async def search_and_read(query: str) -> ToolResult:
    """Deep search: searches web and extracts full text from the most relevant page."""
    from ddgs import DDGS

    logger.info(f"search_and_read query: '{query}'")
    try:
        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=3))

        results = await asyncio.to_thread(_search)
        if not results:
            return ToolResult(
                success=False,
                error="No results found",
                message=f"I couldn't find any web results for '{query}'.",
            )

        top_hit = results[0]
        top_url = top_hit.get("href", "")
        top_title = top_hit.get("title", "")
        top_snippet = top_hit.get("body", "")

        # Read the top webpage directly
        if top_url:
            read_res = await read_webpage(top_url, max_chars=3000)
            if read_res.success:
                return ToolResult(
                    success=True,
                    message=(
                        f"Search results for '{query}':\n"
                        f"Top Source: {top_title} ({top_url})\n\n"
                        f"{read_res.message[:2500]}"
                    ),
                    data={"top_url": top_url, "snippet": top_snippet},
                )

        # Fallback to snippets if read fails
        snippets = "\n".join(f"- {r.get('title')}: {r.get('body')}" for r in results)
        return ToolResult(
            success=True,
            message=f"Search snippets for '{query}':\n{snippets}",
            data={"results": results},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message=f"Failed to search and read for '{query}': {e}",
        )
