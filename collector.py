import feedparser
import logging
import re
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from config import COMMODITY_CONFIGS, MAX_ARTICLE_AGE_HOURS

logger = logging.getLogger(__name__)


try:
    from firecrawl_client import FireCrawlClient
    _HAS_FIRECRAWL = True
except ImportError:
    _HAS_FIRECRAWL = False

try:
    import cloudscraper
    _HAS_CLOUDSCRAPER = True
except ImportError:
    _HAS_CLOUDSCRAPER = False


class DataCollector:
    def __init__(self, commodity="gold"):
        self.commodity = commodity
        self.config = COMMODITY_CONFIGS.get(commodity, COMMODITY_CONFIGS["gold"])
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        })
        self.articles = []
        self._analyzer = None

    def _parse_published(self, entry):
        """Extract the original published datetime (UTC) from an RSS entry."""
        # Try feedparser's parsed tuple first
        pp = entry.get("published_parsed")
        if pp:
            try:
                return datetime.utcfromtimestamp(
                    (datetime(*pp[:6]) - datetime(1970, 1, 1)).total_seconds()
                ).replace(tzinfo=timezone.utc)
            except Exception:
                pass
        # Fallback: parse published string
        ps = entry.get("published", "")
        if ps:
            try:
                # Use email.utils which handles RFC 822
                dt = parsedate_to_datetime(ps)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
        return None

    @staticmethod
    def _age_str(now, published_dt):
        """Return human-readable age: '45m', '3h 20m', '1d'."""
        if not published_dt:
            return None
        delta = now - published_dt.astimezone(timezone.utc)
        total_secs = int(delta.total_seconds())
        if total_secs < 0:
            return None
        if total_secs < 3600:
            return f"{total_secs // 60}m"
        if total_secs < 86400:
            h = total_secs // 3600
            m = (total_secs % 3600) // 60
            return f"{h}h {m}m" if m else f"{h}h"
        d = total_secs // 86400
        return f"{d}d"

    @staticmethod
    def _filter_fresh(articles):
        """Reject articles older than MAX_ARTICLE_AGE_HOURS."""
        if MAX_ARTICLE_AGE_HOURS <= 0:
            return articles
        cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_ARTICLE_AGE_HOURS)
        fresh = []
        for a in articles:
            pub = a.get("published")
            if not pub:
                # No date info — keep it (can't determine age)
                fresh.append(a)
                continue
            try:
                if isinstance(pub, str):
                    # Try ISO format first
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                elif isinstance(pub, datetime):
                    dt = pub
                else:
                    fresh.append(a)
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    fresh.append(a)
            except Exception:
                # Date parsing failed — keep it to avoid losing articles
                fresh.append(a)
        return fresh

    @staticmethod
    def _parse_relative_time(text):
        """Parse strings like '2 hours ago', '30 minutes ago' into datetime (UTC)."""
        text = text.lower().strip()
        now = datetime.now(timezone.utc)
        import re as _re
        # e.g. "2 hours ago", "4 h", "30 min"
        m = _re.search(r'(\d+)\s*(?:h(?:ours?)?|hr?)\b', text)
        if m:
            return now - timedelta(hours=int(m.group(1)))
        m = _re.search(r'(\d+)\s*(?:minutes?|min|m)\b', text)
        if m:
            return now - timedelta(minutes=int(m.group(1)))
        m = _re.search(r'(\d+)\s*(?:days?|d)\b', text)
        if m:
            return now - timedelta(days=int(m.group(1)))
        return None

    def _clean_html(self, text):
        if not text:
            return ""
        return BeautifulSoup(text, "html.parser").get_text(strip=True)

    def _keyword_match_score(self, text):
        if self._analyzer is None:
            from analyzer import SentimentAnalyzer
            self._analyzer = SentimentAnalyzer(commodity=self.commodity)
        return self._analyzer._keyword_match_score(text)

    def fetch_price(self):
        ticker = self.config["ticker"]
        currency = self.config.get("currency", "$")
        try:
            resp = self.session.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1m",
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta.get("regularMarketPrice", 0)
                prev = meta.get("chartPreviousClose", 0)
                if price and prev:
                    change = price - prev
                    change_pct = (change / prev) * 100
                    volume = meta.get("regularMarketVolume")
                    open_ = meta.get("regularMarketOpen")
                    high = meta.get("regularMarketDayHigh")
                    low = meta.get("regularMarketDayLow")
                    result = {"price": round(price, 2), "change": round(change, 2), "change_pct": round(change_pct, 2), "source": "yahoo", "currency": currency}
                    if open_:
                        result["open"] = round(open_, 2)
                    if high:
                        result["high"] = round(high, 2)
                    if low:
                        result["low"] = round(low, 2)
                    if prev:
                        result["prev_close"] = round(prev, 2)
                    if volume is not None:
                        result["volume"] = volume
                        result["volume_display"] = f"{volume:,}" if isinstance(volume, int) else str(volume)
                    return result
        except Exception:
            pass

        if self.commodity == "fcpo":
            return self._fetch_fcpo_price()
        return None

    def _fetch_fcpo_market_data(self):
        """Investing.com scraper: CSS selectors + regex dual fallback."""
        url = "https://www.investing.com/commodities/palm-oil"
        html = ""
        try:
            if _HAS_CLOUDSCRAPER:
                scraper = cloudscraper.create_scraper()
                resp = scraper.get(url, timeout=20)
            else:
                resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None
            html = resp.text
        except Exception:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # ---- Phase 1: CSS selectors ----
        def _sel(css):
            el = soup.select_one(css)
            if el:
                txt = el.get_text(strip=True).replace(",", "").replace("%", "").strip()
                try:
                    return float(txt)
                except ValueError:
                    return txt if txt else None
            return None

        price = _sel('[data-test="instrument-price-last"]') or _sel('.text-5xl') or _sel('.last-price') or _sel('.arial_26')
        prev = _sel('[data-test="prevClose"]') or _sel('[data-test="instrument-price-prev-close"]')
        open_ = _sel('[data-test="open"]')
        daily_range = _sel('[data-test="dailyRange"]')
        weekly_range = _sel('[data-test="weekRange"]')
        volume = _sel('[data-test="volume"]')

        # ---- Phase 2: Regex fallback (extract from raw HTML) ----
        if price is None:
            m_price = re.search(r'(?:Price|Last|Current)[\s:]+([\d,]+\.?\d*)', html)
            if not m_price:
                # Investing.com pattern: "4,570.00" near "Palm Oil"
                m_price = re.search(r'(\d{1,2},\d{3}\.\d{2})', html)
            if m_price:
                try:
                    price = float(m_price.group(1).replace(",", ""))
                except ValueError:
                    pass

        if prev is None and price is not None:
            m_prev = re.search(r'(?:Prev\.?\s*Close|Previous)[\s:]+([\d,]+\.?\d*)', html)
            if m_prev:
                try:
                    prev = float(m_prev.group(1).replace(",", ""))
                except ValueError:
                    pass

        if price is None:
            logger.warning("FCPO: Could not extract price from investing.com (CSS + regex both failed)")
            return None

        def _safe_float(v, default=None):
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        price_f = _safe_float(price, 0)
        prev_f = _safe_float(prev, price_f)
        change = round(price_f - prev_f, 2)
        change_pct = round((change / prev_f) * 100, 2) if prev_f else 0

        high = None
        low = None
        if daily_range and isinstance(daily_range, str) and "-" in daily_range:
            parts = daily_range.split("-")
            try:
                low = float(parts[0].strip().replace(",", ""))
                high = float(parts[1].strip().replace(",", ""))
            except (ValueError, IndexError):
                pass

        volume_display = volume
        if isinstance(volume, (int, float)):
            volume_display = f"{int(volume):,}"
        elif isinstance(volume, str):
            volume_display = volume
        else:
            volume_display = None

        return {
            "price": price_f,
            "open": _safe_float(open_),
            "high": high,
            "low": low,
            "prev_close": prev_f,
            "change": change,
            "change_pct": change_pct,
            "volume": _safe_float(volume),
            "volume_display": volume_display,
            "day_range": str(daily_range) if daily_range else None,
            "week_range_52": str(weekly_range) if weekly_range else None,
            "source": "investing.com",
            "currency": "RM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def fcpo_market_data(self):
        if self.commodity != "fcpo":
            return None
        return self._fetch_fcpo_market_data()

    def fetch_rss(self, feed_urls=None):
        if feed_urls is None:
            feed_urls = list(dict.fromkeys(self.config["rss_feeds"] + self.config["news_feeds"]))

        all_entries = []
        for url in feed_urls:
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                for entry in feed.entries:
                    title = entry.get("title", "")
                    summary = self._clean_html(entry.get("summary", ""))
                    link = entry.get("link", "")
                    published_dt = self._parse_published(entry)
                    age_str = None
                    if published_dt:
                        age_str = self._age_str(datetime.now(timezone.utc), published_dt)

                    full_text = f"{title}. {summary}"
                    score, categories = self._keyword_match_score(full_text)

                    if score > 0:
                        all_entries.append({
                            "title": title,
                            "summary": summary[:500],
                            "text": full_text,
                            "link": link,
                            "keyword_score": score,
                            "categories": list(categories),
                            "source": "rss",
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "published": published_dt.isoformat() if published_dt else "",
                            "age": age_str,
                        })
            except (requests.RequestException, ValueError):
                continue

        all_entries.sort(key=lambda x: x["keyword_score"], reverse=True)
        return all_entries

    def fetch_web_search(self):
        all_entries = []
        for query in self.config["web_queries"]:
            try:
                url = f"https://www.google.com/search?q={query.replace(' ', '+')}&tbm=nws"
                resp = self.session.get(url, timeout=10)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                for result_block in soup.select("div.Gx5Zad, div.soZOfe, div.SoaBEf"):
                    title_el = result_block.select_one("div.BNeawe.vvjwJb, div.n0gyMr, div.MBeuO, a h3")
                    if not title_el:
                        continue
                    snippet_el = result_block.select_one("div.BNeawe.s3v9rd, div.GI74Re, div.kY2Ob")
                    title = title_el.get_text(strip=True)
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    import re as _re
                    # Try to extract relative time from snippet or nearby text
                    nearby = result_block.get_text(strip=True)
                    age_dt = self._parse_relative_time(nearby)
                    age_str = self._age_str(datetime.now(timezone.utc), age_dt) if age_dt else None

                    if not title or len(title) < 10:
                        continue
                    full_text = f"{title}. {snippet}"
                    score, categories = self._keyword_match_score(full_text)
                    if score > 0:
                        all_entries.append({
                            "title": title,
                            "summary": snippet[:500],
                            "text": full_text,
                            "keyword_score": score,
                            "categories": list(categories),
                            "source": "web",
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "published": age_dt.isoformat() if age_dt else "",
                            "age": age_str,
                        })
            except (requests.RequestException, ValueError):
                continue

        return all_entries

    def collect_all(self, groq_client=None, firecrawl_client=None):
        """
        Collect articles: Firecrawl search+scrape PRIMARY, RSS supplement.
        Firecrawl unavailable → falls back to RSS + Google News scrape.
        """
        self.articles = []
        fc_articles = []

        # 1) Firecrawl primary
        if _HAS_FIRECRAWL and (firecrawl_client is None or firecrawl_client.available):
            try:
                if firecrawl_client is None:
                    firecrawl_client = FireCrawlClient()
                if firecrawl_client.available:
                    fc_raw = firecrawl_client.fetch_commodity_news(self.config)
                    # Score with keyword matcher
                    now = datetime.now(timezone.utc)
                    for a in fc_raw:
                        text = a.get("text", "")
                        score, categories = self._keyword_match_score(text)
                        a["keyword_score"] = score
                        a["categories"] = list(categories)
                        # Parse age from published string if present
                        if a.get("published"):
                            try:
                                dt = parsedate_to_datetime(a["published"])
                                if dt and dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                a["published"] = dt.isoformat()
                                a["age"] = self._age_str(now, dt)
                            except Exception:
                                a["age"] = None
                        else:
                            a["age"] = None
                        a.setdefault("source", "firecrawl")
                    fc_articles = [a for a in fc_raw if a.get("keyword_score", 0) > 0]
            except Exception as e:
                logger.warning(f"Firecrawl failed for {self.commodity}: {e}")

        # 2) RSS supplement (always fetch; merges if Firecrawl thin)
        rss_results = self.fetch_rss()

        # 3) Fallback: Google News scrape ONLY if Firecrawl empty AND RSS thin
        web_results = []
        if not fc_articles or len(fc_articles) < 5:
            web_results = self.fetch_web_search()

        # 4) Merge + dedup by URL
        self.articles = fc_articles + rss_results + web_results
        seen_urls = set()
        unique = []
        for a in self.articles:
            url = a.get("link", a.get("url", "")).strip()
            if not url:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            unique.append(a)

        # 5) Freshness filter: reject articles older than MAX_ARTICLE_AGE_HOURS
        self.articles = self._filter_fresh(unique)
        fresh_count = len(self.articles)

        # 6) Groq AI enrichment
        if groq_client and groq_client.available:
            self.articles = groq_client.batch_classify_articles(self.articles, self.commodity)

        rss_count = sum(1 for a in self.articles if a.get("source") == "rss")
        web_count = sum(1 for a in self.articles if a.get("source") in ("firecrawl", "web"))

        return {
            "total_articles": len(self.articles),
            "rss_count": rss_count,
            "web_count": web_count,
            "firecrawl_count": len(fc_articles),
            "fresh_count": fresh_count,
            "articles": self.articles,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "commodity": self.commodity,
        }


if __name__ == "__main__":
    for comm in ["gold", "wti", "fcpo"]:
        c = DataCollector(commodity=comm)
        data = c.collect_all()
        print(f"\n=== {comm.upper()} ===")
        print(f"Collected {data['total_articles']} articles")
        for a in data["articles"][:3]:
            print(f"  [{a['keyword_score']}] {a['title'][:80]}")