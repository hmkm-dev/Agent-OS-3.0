"""Optional Crawl4AI adapter.

Uses Crawl4AI's official AsyncWebCrawler when installed. It never fabricates
results: missing dependency/configuration is returned as a tool error.
"""
from __future__ import annotations
import os

async def crawl(url: str, *, timeout_ms: int = 60000, word_count_threshold: int = 0) -> dict:
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must use http:// or https://")
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    except ImportError as exc:
        raise RuntimeError("Crawl4AI is not installed; install the MCP crawl dependencies") from exc
    browser=BrowserConfig(headless=True)
    config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=timeout_ms, word_count_threshold=word_count_threshold)
    async with AsyncWebCrawler(config=browser) as crawler:
        result=await crawler.arun(url=url, config=config)
    if not getattr(result, "success", False):
        raise RuntimeError(getattr(result, "error_message", None) or "Crawl4AI crawl failed")
    markdown=getattr(result, "markdown", "") or ""
    if hasattr(markdown, "raw_markdown"):
        markdown=markdown.raw_markdown
    return {"url":url,"success":True,"markdown":markdown,"title":getattr(result,"title",None),"status_code":getattr(result,"status_code",None)}
