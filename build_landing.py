"""Generate a static landing.html from live data — run every 5 minutes.
Serves as SEO-friendly, LLM-readable snapshot of the dashboard."""
import os
import sys
import json
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import COMMODITY_CONFIGS
from collector import DataCollector
from analyzer import SentimentAnalyzer
from groq_client import GroqAnalyzer

GROQ = GroqAnalyzer()
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing.html")


def _run_analysis(commodity):
    cfg = COMMODITY_CONFIGS.get(commodity, COMMODITY_CONFIGS["gold"])
    collector = DataCollector(commodity=commodity)
    analyzer = SentimentAnalyzer(commodity=commodity, groq_client=GROQ)
    price_data = collector.fetch_price()
    market_data = collector.fcpo_market_data() if commodity == "fcpo" else None
    data = collector.collect_all(groq_client=GROQ)
    result = analyzer.run_full_analysis(data["articles"])
    result["collection_meta"] = {
        "total_articles": data["total_articles"],
        "rss_count": data["rss_count"],
        "web_count": data["web_count"],
        "timestamp": data["timestamp"],
        "price_label": cfg["price_label"],
    }
    return result, data, price_data, market_data


def _build_headline_cards(articles, limit=12):
    cards = []
    for a in articles[:limit]:
        vs = a.get("vader_score", 0)
        tone = "positive" if vs > 0.05 else "negative" if vs < -0.05 else "neutral"
        age = a.get("age", "")
        title = a.get("title", "")[:90]
        link = a.get("link", "")
        published = a.get("published", "")
        cards.append({
            "title": title,
            "link": link,
            "tone": tone,
            "age": age,
            "published": published,
        })
    return cards


def _build_html(gold_data, wti_data, fcpo_data):
    """Generate the full static HTML with OG, Twitter, JSON-LD, semantic HTML."""
    g_result, g_articles, g_price, _ = gold_data
    w_result, w_articles, w_price, _ = wti_data
    f_result, f_articles, f_price, f_market = fcpo_data

    gold_bias = g_result["final_synthesis"]["final_gold_xauusd_bias"]
    wti_bias = w_result["final_synthesis"]["final_wti_bias"]
    fcpo_bias = f_result["final_synthesis"]["final_fcpo_bias"]
    gold_score = g_result["analysis_2_sentiment"]["xauusd_sentiment_score"]
    wti_score = w_result["analysis_2_sentiment"]["wti_sentiment_score"]
    fcpo_score = f_result["analysis_2_sentiment"]["fcpo_sentiment_score"]

    gold_headlines = _build_headline_cards(g_articles["articles"])
    wti_headlines = _build_headline_cards(w_articles["articles"])
    fcpo_headlines = _build_headline_cards(f_articles["articles"])

    from datetime import datetime, timezone, timedelta
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%d %b %Y, %I:%M %p")
    updated_iso = datetime.now(timezone.utc).isoformat()

    # Price formatting
    def _fmt(p):
        if p and p.get("price"):
            s = "+" if p.get("change", 0) >= 0 else ""
            return f"${p['price']:,.2f} ({s}{p.get('change', 0):.2f})"
        return "—"

    def _fmt_fcpo(p, m):
        if p and p.get("price"):
            s = "+" if p.get("change", 0) >= 0 else ""
            return f"RM{p['price']:,.2f} ({s}{p.get('change', 0):.2f})"
        return "—"

    gold_price_str = _fmt(g_price)
    wti_price_str = _fmt(w_price)
    fcpo_price_str = _fmt_fcpo(f_price, f_market)

    og_desc = (
        f"Gold: {gold_bias} ({gold_score:,.1f}) | "
        f"WTI: {wti_bias} ({wti_score:,.1f}) | "
        f"FCPO: {fcpo_bias} ({fcpo_score:,.1f})"
    )

    def _badge_color(bias):
        return {
            "Strong Buy": "#30D158", "Buy": "#34C759",
            "Neutral": "#FFD60A",
            "Sell": "#FF453A", "Strong Sell": "#FF3B30",
        }.get(bias, "#86868B")

    def _headline_html(headlines):
        lines = []
        for h in headlines:
            marker = "🟢" if h["tone"] == "positive" else "🔴" if h["tone"] == "negative" else "🟡"
            age = f"<span style='color:#0A84FF;'>{h['age']} ago</span>" if h["age"] else ""
            link_open = f'<a href="{h["link"]}" target="_blank" style="color:#1a1a1a;text-decoration:none;">' if h["link"] else ''
            link_close = '</a>' if h["link"] else ''
            lines.append(
                f'<article itemscope itemtype="https://schema.org/NewsArticle">'
                f'<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #e5e5e5;">'
                f'<span style="font-size:14px;flex-shrink:0;">{marker}</span>'
                f'<div style="flex:1;">'
                f'<div itemprop="headline" style="font-size:14px;color:#1a1a1a;font-weight:500;margin-bottom:2px;">{link_open}{h["title"]}{link_close}</div>'
                f'<time itemprop="datePublished" datetime="{h["published"]}" style="font-size:12px;color:#666;">{age}</time>'
                f'</div></div></article>'
            )
        return "\n".join(lines)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Commodity Sentiment Intelligence — Gold, WTI, FCPO Real-Time Dashboard</title>
<meta name="description" content="{og_desc}. Real-time sentiment analysis powered by Groq AI + VADER NLP. Updated every 5 minutes.">

<!-- Open Graph / Facebook -->
<meta property="og:title" content="Commodity Sentiment • {gold_bias} | {wti_bias} | {fcpo_bias}">
<meta property="og:description" content="{og_desc}. Live sentiment dashboard tracking Gold, WTI Crude Oil & FCPO Palm Oil via AI-powered analysis.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://tengkolok-commoditysentiment.hf.space">
<meta property="og:locale" content="en_US">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{now_str} — Commodity Sentiment Report">
<meta name="twitter:description" content="Gold: {gold_price_str} • WTI: {wti_price_str} • FCPO: {fcpo_price_str}">

<!-- JSON-LD Structured Data -->
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Commodity Sentiment Intelligence Dashboard",
  "description": "{og_desc}",
  "url": "https://tengkolok-commoditysentiment.hf.space",
  "dateModified": "{updated_iso}",
  "publisher": {{
    "@type": "Person",
    "name": "@PedotTTRG",
    "url": "https://t.me/PedotTTRG"
  }},
  "about": [
    {{
      "@type": "Thing",
      "name": "Gold (XAU/USD)",
      "description": "Sentiment score: {gold_score:,.1f} / Bias: {gold_bias}. Price: {gold_price_str}"
    }},
    {{
      "@type": "Thing",
      "name": "WTI Crude Oil",
      "description": "Sentiment score: {wti_score:,.1f} / Bias: {wti_bias}. Price: {wti_price_str}"
    }},
    {{
      "@type": "Thing",
      "name": "FCPO Crude Palm Oil",
      "description": "Sentiment score: {fcpo_score:,.1f} / Bias: {fcpo_bias}. Price: {fcpo_price_str}"
    }}
  ]
}}
</script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {{ --bg: #F5F5F7; --card: #ffffff; --text: #1a1a1a; --muted: #666; --accent: #0A84FF; }}
* {{ box-sizing:border-box; margin:0; padding:0; font-family: 'Inter', -apple-system, sans-serif; }}
body {{ background: var(--bg); color: var(--text); line-height:1.5; }}
.container {{ max-width:960px; margin:0 auto; padding:24px 16px; }}
header {{ text-align:center; padding:40px 0 24px; }}
header h1 {{ font-size:32px; font-weight:700; letter-spacing:-0.02em; margin-bottom:8px; }}
header p {{ color: var(--muted); font-size:15px; margin-bottom:20px; }}
.launch-btn {{ display:inline-block; background:#000; color:#fff; padding:14px 32px; border-radius:999px; font-weight:600; text-decoration:none; font-size:15px; transition:opacity 0.2s; }}
.launch-btn:hover {{ opacity:0.85; }}
.updated {{ font-size:13px; color:#999; margin-top:8px; }}

.badge {{ display:inline-block; background:#e8f5e9; color:#1b5e20; padding:4px 12px; border-radius:999px; font-size:12px; font-weight:600; margin-left:8px; }}
.badge-sell {{ background:#ffebee; color:#b71c1c; }}
.badge-neutral {{ background:#fff8e1; color:#5d4037; }}

.grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(280px,1fr)); gap:16px; margin:32px 0; }}
.card {{ background:var(--card); border:1px solid #e0e0e0; border-radius:20px; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.04); }}
.card h2 {{ font-size:22px; font-weight:600; margin-bottom:8px; display:flex;align-items:center;gap:8px; }}
.price {{ font-size:28px; font-weight:700; color:var(--text); margin:8px 0; }}
.score {{ font-size:14px; color:var(--muted); margin-bottom:12px; }}

.headlines {{ background:var(--card); border:1px solid #e0e0e0; border-radius:20px; padding:24px; margin-top:16px; }}
.headlines h3 {{ font-size:16px; font-weight:600; margin-bottom:16px; text-transform:uppercase; letter-spacing:0.05em; }}

footer {{ text-align:center; color:#999; font-size:13px; padding:40px 0; }}
footer a {{ color:var(--accent); text-decoration:none; }}
</style>
</head>
<body>

<header>
<h1>Commodity Sentiment Intelligence</h1>
<p>Real-time sentiment for Gold, WTI Crude Oil &amp; FCPO — powered by Groq AI + VADER NLP</p>
<p class="updated">Last updated: {now_str} MYT &middot; Auto-refreshes every 5 minutes</p>
<a href="./dashboard" class="launch-btn">Launch Dashboard 🚀</a>
</header>

<div class="container">

<section itemscope itemtype="https://schema.org/Dataset">
<meta itemprop="name" content="Commodity Sentiment Scores">
<meta itemprop="dateModified" content="{updated_iso}">

<div class="grid">

<!-- Gold -->
<article class="card" itemprop="about" itemscope itemtype="https://schema.org/FinancialProduct">
<meta itemprop="name" content="Gold (XAU/USD)">
<h2 itemprop="tickerSymbol">🥇 Gold <span class="badge" style="background:{_badge_color(gold_bias)}22;color:{_badge_color(gold_bias)};">{gold_bias}</span></h2>
<div class="price" itemprop="price">{gold_price_str}</div>
<div class="score">Sentiment: <strong>{gold_score:,.1f}</strong></div>
<div class="headlines">
<h3>Latest Headlines</h3>
{_headline_html(gold_headlines)}
</div>
</article>

<!-- WTI -->
<article class="card" itemprop="about" itemscope itemtype="https://schema.org/FinancialProduct">
<meta itemprop="name" content="WTI Crude Oil">
<h2 itemprop="tickerSymbol">🛢️ WTI <span class="badge" style="background:{_badge_color(wti_bias)}22;color:{_badge_color(wti_bias)};">{wti_bias}</span></h2>
<div class="price" itemprop="price">{wti_price_str}</div>
<div class="score">Sentiment: <strong>{wti_score:,.1f}</strong></div>
<div class="headlines">
<h3>Latest Headlines</h3>
{_headline_html(wti_headlines)}
</div>
</article>

<!-- FCPO -->
<article class="card" itemprop="about" itemscope itemtype="https://schema.org/FinancialProduct">
<meta itemprop="name" content="FCPO Crude Palm Oil">
<h2 itemprop="tickerSymbol">🌴 FCPO <span class="badge" style="background:{_badge_color(fcpo_bias)}22;color:{_badge_color(fcpo_bias)};">{fcpo_bias}</span></h2>
<div class="price" itemprop="price">{fcpo_price_str}</div>
<div class="score">Sentiment: <strong>{fcpo_score:,.1f}</strong> <span style="color:#666;font-size:12px;">MYR</span></div>
<div class="headlines">
<h3>Latest Headlines</h3>
{_headline_html(fcpo_headlines)}
</div>
</article>

</div>
</section>

<footer>
Prepared by <a href="https://t.me/PedotTTRG" target="_blank">@PedotTTRG</a> &middot;
Daily reports at 6:01 AM MYT &middot;
Sentiment data: Groq AI + VADER NLP
</footer>

</div>
</body>
</html>
"""
    return html


def build_and_save():
    """Generate landing.html once."""
    try:
        gold = _run_analysis("gold")
        wti = _run_analysis("wti")
        fcpo = _run_analysis("fcpo")
        html = _build_html(gold, wti, fcpo)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[landing] Generated {OUTPUT_PATH}")
    except Exception as e:
        print(f"[landing] Error: {e}")


def run_background(interval_sec=300):
    """Run builder in a background thread every N seconds."""
    def _loop():
        while True:
            build_and_save()
            time.sleep(interval_sec)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[landing] Background builder started ({interval_sec}s interval)")


if __name__ == "__main__":
    build_and_save()
