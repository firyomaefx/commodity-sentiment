import feedparser
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from config import COMMODITY_CONFIGS

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
        try:
            if _HAS_CLOUDSCRAPER:
                scraper = cloudscraper.create_scraper()
                resp = scraper.get("https://www.investing.com/commodities/palm-oil", timeout=20)
            else:
                resp = self.session.get("https://www.investing.com/commodities/palm-oil", timeout=15)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")

            def _val(test_id):
                el = soup.select_one(f'[data-test="{test_id}"]')
                if not el:
                    return None
                txt = el.text.strip().replace(",", "").replace("%", "").strip()
                try:
                    return float(txt)
                except ValueError:
                    return txt if txt else None

            price = _val("instrument-price-last")
            if price is None:
                return None
            if isinstance(price, float):
                price = round(price, 2)

            prev = _val("prevClose")
            open_ = _val("open")
            daily_range = _val("dailyRange")
            weekly_range = _val("weekRange")
            volume = _val("volume")
            settlement_type = _val("settlement_type")
            contract_size = _val("contract_size")
            point_value = _val("point_value")
            tick_size = _val("tick_size")
            tick_value = _val("tick_value")

            def _safe_float(v, default=None):
                if v is None:
                    return default
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return default

            prev_f = _safe_float(prev, price)
            change = round(_safe_float(price, 0) - prev_f, 2) if isinstance(price, (int, float)) else 0
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
                "price": _safe_float(price, 0),
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
                "settlement_type": str(settlement_type) if settlement_type else None,
                "contract_size": str(contract_size) if contract_size else None,
                "point_value": str(point_value) if point_value else None,
                "tick_size": str(tick_size) if tick_size else None,
                "source": "investing.com",
                "currency": "RM",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            return None

    def _fetch_fcpo_price(self):
        result = self._fetch_fcpo_market_data()
        if result and result.get("price"):
            return {
                "price": result["price"],
                "change": result.get("change"),
                "change_pct": result.get("change_pct"),
                "source": result.get("source", "investing.com"),
                "currency": result.get("currency", "RM"),
                "open": result.get("open"),
                "high": result.get("high"),
                "low": result.get("low"),
                "prev_close": result.get("prev_close"),
                "volume": result.get("volume"),
                "volume_display": result.get("volume_display"),
                "day_range": result.get("day_range"),
                "week_range_52": result.get("week_range_52"),
            }
        try:
            if _HAS_CLOUDSCRAPER:
                scraper = cloudscraper.create_scraper()
                resp = scraper.get("https://www.investing.com/commodities/palm-oil", timeout=20)
            else:
                resp = self.session.get("https://www.investing.com/commodities/palm-oil", timeout=15)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            price_el = soup.select_one('[data-test="instrument-price-last"]')
            if not price_el:
                return None
            price_text = price_el.text.strip().replace(",", "")
            price = float(price_text)
            prev_el = soup.select_one('[data-test="instrument-price-prev-close"]')
            prev = price
            if prev_el:
                try:
                    prev = float(prev_el.text.strip().replace(",", ""))
                except ValueError:
                    pass
            change = price - prev
            change_pct = (change / prev) * 100 if prev else 0
            return {"price": round(price, 2), "change": round(change, 2), "change_pct": round(change_pct, 2), "source": "investing.com", "currency": "RM"}
        except Exception:
            return None

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

    def collect_all(self, groq_client=None):
        self.articles = []
        rss_results = self.fetch_rss()
        web_results = self.fetch_web_search()
        self.articles = rss_results + web_results
        seen_titles = set()
        unique = []
        for a in self.articles:
            key = a["title"][:80].lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                unique.append(a)
        self.articles = sorted(unique, key=lambda x: x["keyword_score"], reverse=True)[:80]
        if groq_client and groq_client.available:
            self.articles = groq_client.batch_classify_articles(self.articles, self.commodity)
        return {
            "total_articles": len(self.articles),
            "rss_count": len(rss_results),
            "web_count": len(web_results),
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