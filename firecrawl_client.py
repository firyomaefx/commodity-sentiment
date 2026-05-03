"""Firecrawl client: news search + deep article scraping.
Provides full markdown content for high-quality sentiment analysis.
"""
import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FIRECRAWL_AVAILABLE = False
try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    logger.warning("firecrawl-py not installed; search+scrape disabled")


class FireCrawlClient:
    """
    Firecrawl wrapper: search news + scrape full article markdown.
    Uses ThreadPoolExecutor for parallel URL scraping.
    """

    MAX_BATCH = 20       # URLs scraped per commodity per refresh
    TIMEOUT = 10         # seconds per scrape request
    MAX_WORKERS = 5      # parallel scrape threads

    def __init__(self, api_key=None):
        self.available = False
        self.app = None
        if not FIRECRAWL_AVAILABLE:
            return
        key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
        if not key:
            logger.warning("FIRECRAWL_API_KEY not set")
            return
        try:
            self.app = FirecrawlApp(api_key=key)
            self.available = True
            logger.info("Firecrawl client initialized")
        except Exception as e:
            logger.error(f"Firecrawl init failed: {e}")

    # ------------------------------------------------------------------
    #  Search
    # ------------------------------------------------------------------
    def search_news(self, query, num_results=10):
        """
        Firecrawl search: returns list of {title,url,description,source}.
        Falls back to empty list if unavailable.
        """
        if not self.available:
            return []
        try:
            resp = self.app.search(
                query=query,
                num=num_results,
                scraperOptions={"formats": ["markdown"]},
            )

            raw = resp if isinstance(resp, list) else resp.get("data", []) if isinstance(resp, dict) else []
            results = []
            for item in raw:
                if isinstance(item, dict):
                    results.append({
                        "title": item.get("title", item.get("metadata", {}).get("title", "")).strip(),
                        "url": item.get("url", item.get("link", "")).strip(),
                        "description": item.get("description", item.get("metadata", {}).get("description", "")).strip(),
                        "source": item.get("source", item.get("metadata", {}).get("source", "firecrawl")),
                        "published": item.get("publishedDate", item.get("metadata", {}).get("publishedDate", "")),
                        "markdown": item.get("markdown", item.get("content", "")),
                    })
            logger.info(f"Firecrawl search '{query[:40]}...' returned {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"Firecrawl search failed: {e}")
            return []

    # ------------------------------------------------------------------
    #  Scrape
    # ------------------------------------------------------------------
    def _scrape_single(self, url):
        """Scrape one URL, return dict or None."""
        if not self.app:
            return None
        try:
            resp = self.app.scrape_url(url, params={"formats": ["markdown"], "timeout": self.TIMEOUT})
            if not resp or not isinstance(resp, dict):
                return None
            md = resp.get("markdown", resp.get("content", "")).strip()
            meta = resp.get("metadata", {}) or {}
            if not md or len(md) < 200:
                return None  # too thin
            return {
                "markdown": md,
                "title": meta.get("title", "").strip() or resp.get("title", "").strip(),
                "url": url,
                "source": meta.get("source", meta.get("ogSiteName", "web")),
                "published": meta.get("publishedDate", "") or meta.get("date", ""),
                "author": meta.get("author", ""),
            }
        except Exception as e:
            logger.error(f"Firecrawl scrape failed for {url}: {e}")
            return None

    def scrape_urls(self, urls):
        """Parallel scrape list of URLs; return list of dicts with markdown."""
        if not self.available or not urls:
            return []

        seen = set()
        unique = [u for u in urls if u and u not in seen and not seen.add(u)]

        results = []
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            futures = {pool.submit(self._scrape_single, url): url for url in unique[:self.MAX_BATCH]}
            for fut in as_completed(futures):
                res = fut.result()
                if res:
                    results.append(res)
        logger.info(f"Firecrawl scraped {len(results)}/{len(unique)} URLs")
        return results

    # ------------------------------------------------------------------
    #  High-level commodity pipeline
    # ------------------------------------------------------------------
    def fetch_commodity_news(self, commodity_config):
        """
        Full pipeline: search firecrawl for each web_query → collect URLs
        → parallel scrape → return enriched article dicts.
        Articles contain: title, markdown, url, source, published, summary.
        """
        if not self.available:
            return []

        # 1) Search
        raw_results = []
        for query in commodity_config.get("web_queries", []):
            hits = self.search_news(query, num_results=10)
            raw_results.extend(hits)
            if len(raw_results) >= 35:
                break

        # Deduplicate URLs
        seen = set()
        urls = []
        for r in raw_results:
            u = r.get("url")
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

        if not urls:
            return []

        # 2) Scrape
        scraped = self.scrape_urls(urls)

        # 3) Map search metadata onto scraped results
        url_meta = {r["url"]: r for r in raw_results if r.get("url")}
        articles = []
        now = datetime.now(timezone.utc)
        for s in scraped:
            md = s.get("markdown", "")
            # Build text field for keyword scorer (backward compat)
            title = s.get("title") or url_meta.get(s["url"], {}).get("title", "")
            desc = url_meta.get(s["url"], {}).get("description", "")
            text = f"{title}. {desc}. {md[:800]}".strip()

            # Extract date if possible
            pub = s.get("published") or url_meta.get(s["url"], {}).get("published", "")

            articles.append({
                "title": title or "Untitled",
                "markdown": md,
                "summary": md[:500].replace("\n", " ").strip(),
                "text": text,
                "link": s["url"],
                "source": s.get("source", "firecrawl"),
                "published": pub,
                "fetched_at": now.isoformat(),
                "scraper": "firecrawl",
            })

        logger.info(f"Firecrawl pipeline: {len(articles)} enriched articles for commodity")
        return articles
