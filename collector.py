import feedparser
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from config import COMMODITY_CONFIGS


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
                    return {"price": round(price, 2), "change": round(change, 2), "change_pct": round(change_pct, 2), "source": "yahoo", "currency": currency}
        except Exception:
            pass
        return None

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
        self.articles = sorted(unique, key=lambda x: x["keyword_score"], reverse=True)[:150]
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