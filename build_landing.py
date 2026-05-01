"""Generate a static landing.html from live data — run every 5 minutes.
Serves as SEO-friendly, LLM-readable snapshot of the dashboard.
OUTPUT IS MINIFIED: removes Google Fonts, strips whitespace, compresses JSON-LD."""
import os
import sys
import json
import threading
import time
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import COMMODITY_CONFIGS
from collector import DataCollector
from analyzer import SentimentAnalyzer
from groq_client import GroqAnalyzer

GROQ = GroqAnalyzer()
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing.html")

# System font stack — no external font requests
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


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
        cards.append({
            "title": a.get("title", "")[:90],
            "link": a.get("link", ""),
            "tone": tone,
            "age": a.get("age", ""),
            "published": a.get("published", ""),
        })
    return cards


def _minify_css(css_raw):
    css = re.sub(r"/\*.*?\*/", "", css_raw, flags=re.S)
    css = re.sub(r"\n\s*", "", css)
    css = re.sub(r";\s*}", "}", css)
    css = re.sub(r"\s*:\s*", ":", css)
    css = re.sub(r"\s*;\s*", ";", css)
    css = re.sub(r"\s*,\s*", ",", css)
    css = re.sub(r"\s*\{\s*", "{", css)
    css = re.sub(r"\s*\}\s*", "}", css)
    css = re.sub(r"\s+", " ", css).strip()
    return css


def _minify_html(html_raw):
    html = re.sub(r"\n\s*", "", html_raw)
    html = re.sub(r">\s+<", "><", html)
    html = re.sub(r"\s{2,}", " ", html)
    html = re.sub(r"\s*>", ">", html)
    html = re.sub(r"\s{2,}", " ", html).strip()
    return html


def _build_html(gold_data, wti_data, fcpo_data):
    g_result, g_articles, g_price, _ = gold_data
    w_result, w_articles, w_price, _ = wti_data
    f_result, f_articles, f_price, f_market = fcpo_data

    gold_bias = g_result["final_synthesis"]["final_gold_xauusd_bias"]
    wti_bias = w_result["final_synthesis"]["final_wti_bias"]
    fcpo_bias = f_result["final_synthesis"]["final_fcpo_bias"]
    gold_score = g_result["analysis_2_sentiment"]["xauusd_sentiment_score"]
    wti_score = w_result["analysis_2_sentiment"]["wti_sentiment_score"]
    fcpo_score = f_result["analysis_2_sentiment"]["fcpo_sentiment_score"]

    gh = _build_headline_cards(g_articles["articles"])
    wh = _build_headline_cards(w_articles["articles"])
    fh = _build_headline_cards(f_articles["articles"])

    from datetime import datetime, timezone, timedelta
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%d %b %Y, %I:%M %p")
    updated_iso = datetime.now(timezone.utc).isoformat()

    def _fmt(p):
        if p and p.get("price"):
            s = "+" if p.get("change", 0) >= 0 else ""
            return f"${p['price']:,.2f} ({s}{p.get('change', 0):.2f})"
        return "—"

    def _fmtf(p):
        if p and p.get("price"):
            s = "+" if p.get("change", 0) >= 0 else ""
            return f"RM{p['price']:,.2f} ({s}{p.get('change', 0):.2f})"
        return "—"

    gp = _fmt(g_price)
    wp = _fmt(w_price)
    fp = _fmtf(f_price)

    og_desc = f"Gold: {gold_bias} ({gold_score:,.1f}) | WTI: {wti_bias} ({wti_score:,.1f}) | FCPO: {fcpo_bias} ({fcpo_score:,.1f})"

    def _bc(bias):
        return {"Strong Buy": "#30D158", "Buy": "#34C759", "Neutral": "#FFD60A",
                "Sell": "#FF453A", "Strong Sell": "#FF3B30"}.get(bias, "#86868B")

    def _hh(headlines):
        parts = []
        for h in headlines:
            marker = "🟢" if h["tone"] == "positive" else "🔴" if h["tone"] == "negative" else "🟡"
            age = f"\u003cspan style='color:#0A84FF'\u003e{h['age']} ago\u003c/span\u003e" if h["age"] else ""
            link_o = f"\u003ca href='{h['link']}' target='_blank' style='color:#1a1a1a;text-decoration:none'\u003e" if h["link"] else ""
            link_c = "\u003c/a\u003e" if h["link"] else ""
            parts.append(
                f"\u003carticle itemscope itemtype='https://schema.org/NewsArticle'\u003e"
                f"\u003cdiv style='display:flex;align-items:flex-start;gap:8px;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #e5e5e5'\u003e"
                f"\u003cspan style='font-size:14px;flex-shrink:0'\u003e{marker}\u003c/span\u003e"
                f"\u003cdiv style='flex:1'\u003e"
                f"\u003cdiv itemprop='headline' style='font-size:14px;color:#1a1a1a;font-weight:500;margin-bottom:2px'\u003e{link_o}{h['title']}{link_c}\u003c/div\u003e"
                f"\u003ctime itemprop='datePublished' datetime='{h['published']}' style='font-size:12px;color:#666'\u003e{age}\u003c/time\u003e"
                f"\u003c/div\u003e\u003c/div\u003e\u003c/article\u003e"
            )
        return "\n".join(parts)

    css_raw = (
        f":root{{--bg:#F5F5F7;--card:#fff;--text:#1a1a1a;--muted:#666;--accent:#0A84FF}}"
        f"*{{box-sizing:border-box;margin:0;padding:0;font-family:{FONT}}}"
        f"body{{background:var(--bg);color:var(--text);line-height:1.5}}"
        f".container{{max-width:960px;margin:0 auto;padding:24px 16px}}"
        f"header{{text-align:center;padding:40px 0 24px}}"
        f"header h1{{font-size:32px;font-weight:700;letter-spacing:-0.02em;margin-bottom:8px}}"
        f"header p{{color:var(--muted);font-size:15px;margin-bottom:20px}}"
        f".launch-btn{{display:inline-block;background:#000;color:#fff;padding:14px 32px;border-radius:999px;font-weight:600;text-decoration:none;font-size:15px}}"
        f".updated{{font-size:13px;color:#999;margin-top:8px}}"
        f".badge{{display:inline-block;padding:4px 12px;border-radius:999px;font-size:12px;font-weight:600;margin-left:8px}}"
        f".grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin:32px 0}}"
        f".card{{background:var(--card);border:1px solid #e0e0e0;border-radius:20px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}}"
        f".card h2{{font-size:22px;font-weight:600;margin-bottom:8px;display:flex;align-items:center;gap:8px}}"
        f".price{{font-size:28px;font-weight:700;color:var(--text);margin:8px 0}}"
        f".score{{font-size:14px;color:var(--muted);margin-bottom:12px}}"
        f".headlines{{background:var(--card);border:1px solid #e0e0e0;border-radius:20px;padding:24px;margin-top:16px}}"
        f".headlines h3{{font-size:16px;font-weight:600;margin-bottom:16px;text-transform:uppercase;letter-spacing:0.05em}}"
        f"footer{{text-align:center;color:#999;font-size:13px;padding:40px 0}}"
        f"footer a{{color:var(--accent);text-decoration:none}}"
    )

    jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": "Commodity Sentiment Intelligence Dashboard",
        "description": og_desc,
        "url": "https://tengkolok-commoditysentiment.hf.space",
        "dateModified": updated_iso,
        "publisher": {"@type": "Person", "name": "@PedotTTRG", "url": "https://t.me/PedotTTRG"},
        "about": [
            {"@type": "Thing", "name": "Gold (XAU/USD)", "description": f"Sentiment score: {gold_score:,.1f} / Bias: {gold_bias}. Price: {gp}"},
            {"@type": "Thing", "name": "WTI Crude Oil", "description": f"Sentiment score: {wti_score:,.1f} / Bias: {wti_bias}. Price: {wp}"},
            {"@type": "Thing", "name": "FCPO Crude Palm Oil", "description": f"Sentiment score: {fcpo_score:,.1f} / Bias: {fcpo_bias}. Price: {fp}"}
        ]
    }, separators=(",", ":"), ensure_ascii=False)

    html_raw = (
        f"\u003c!DOCTYPE html\u003e\u003chtml lang='en'\u003e\u003chead\u003e"
        f"\u003cmeta charset='UTF-8'\u003e"
        f"\u003cmeta name='viewport' content='width=device-width,initial-scale=1.0'\u003e"
        f"\u003ctitle\u003eCommodity Sentiment — Gold, WTI, FCPO Real-Time Dashboard\u003c/title\u003e"
        f"\u003cmeta name='description' content='{og_desc}. Real-time sentiment via Groq AI + VADER NLP. Updated every 5 minutes.'\u003e"
        f"\u003cmeta property='og:title' content='Commodity Sentiment • {gold_bias} | {wti_bias} | {fcpo_bias}'\u003e"
        f"\u003cmeta property='og:description' content='{og_desc}. Live sentiment dashboard.'\u003e"
        f"\u003cmeta property='og:type' content='website'\u003e"
        f"\u003cmeta property='og:url' content='https://tengkolok-commoditysentiment.hf.space'\u003e"
        f"\u003cmeta property='og:locale' content='en_US'\u003e"
        f"\u003cmeta name='twitter:card' content='summary_large_image'\u003e"
        f"\u003cmeta name='twitter:title' content='{now_str} — Commodity Sentiment'\u003e"
        f"\u003cmeta name='twitter:description' content='Gold: {gp} • WTI: {wp} • FCPO: {fp}'\u003e"
        f"\u003cscript type='application/ld+json'\u003e{jsonld}\u003c/script\u003e"
        f"\u003cstyle\u003e{_minify_css(css_raw)}\u003c/style\u003e"
        f"\u003c/head\u003e\u003cbody\u003e"
        f"\u003cheader\u003e\u003ch1\u003eCommodity Sentiment Intelligence\u003c/h1\u003e"
        f"\u003cp\u003eReal-time sentiment for Gold, WTI Crude Oil &amp; FCPO — Groq AI + VADER NLP\u003c/p\u003e"
        f"\u003cp class='updated'\u003eLast updated: {now_str} MYT • Auto-refresh 5 min\u003c/p\u003e"
        f"\u003ca href='./dashboard' class='launch-btn'\u003eLaunch Dashboard 🚀\u003c/a\u003e\u003c/header\u003e"
        f"\u003cdiv class='container'\u003e"
        f"\u003csection itemscope itemtype='https://schema.org/Dataset'\u003e"
        f"\u003cmeta itemprop='name' content='Commodity Sentiment Scores'\u003e"
        f"\u003cmeta itemprop='dateModified' content='{updated_iso}'\u003e"
        f"\u003cdiv class='grid'\u003e"
        + _card_html("Gold", "GC=F", "🥇", gold_bias, gp, gold_score, _bc(gold_bias), _hh(gh))
        + _card_html("WTI Crude Oil", "CL=F", "🛢️", wti_bias, wp, wti_score, _bc(wti_bias), _hh(wh))
        + _card_html("FCPO Crude Palm Oil", "", "🌴", fcpo_bias, fp, fcpo_score, _bc(fcpo_bias), _hh(fh), myr=True)
        + "\u003c/div\u003e\u003c/section\u003e"
        f"\u003cfooter\u003ePrepared by \u003ca href='https://t.me/PedotTTRG' target='_blank'\u003e@PedotTTRG\u003c/a\u003e • Daily reports at 6:01 AM MYT • Groq AI + VADER NLP\u003c/footer\u003e"
        f"\u003c/div\u003e\u003c/body\u003e\u003c/html\u003e"
    )

    return _minify_html(html_raw)


def _card_html(name, ticker, emoji, bias, price, score, badge_color, headlines_html, myr=False):
    myr_tag = " \u003cspan style='color:#666;font-size:12px'\u003eMYR\u003c/span\u003e" if myr else ""
    return (
        f"\u003carticle class='card' itemprop='about' itemscope itemtype='https://schema.org/FinancialProduct'\u003e"
        f"\u003cmeta itemprop='name' content='{name}'\u003e"
        f"\u003ch2\u003e{emoji} {name.split()[0]} \u003cspan class='badge' style='background:{badge_color}22;color:{badge_color};'\u003e{bias}\u003c/span\u003e\u003c/h2\u003e"
        f"\u003cdiv class='price' itemprop='price'\u003e{price}\u003c/div\u003e"
        f"\u003cdiv class='score'\u003eSentiment: \u003cstrong\u003e{score:,.1f}\u003c/strong\u003e{myr_tag}\u003c/div\u003e"
        f"\u003cdiv class='headlines'\u003e\u003ch3\u003eLatest Headlines\u003c/h3\u003e{headlines_html}\u003c/div\u003e"
        f"\u003c/article\u003e"
    )


def build_and_save():
    try:
        gold = _run_analysis("gold")
        wti = _run_analysis("wti")
        fcpo = _run_analysis("fcpo")
        html = _build_html(gold, wti, fcpo)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(html)
        size_kb = len(html.encode("utf-8")) / 1024
        print(f"[landing] Generated {OUTPUT_PATH} ({size_kb:.1f} KB)")
    except Exception as e:
        print(f"[landing] Error: {e}")


def run_background(interval_sec=300):
    def _loop():
        while True:
            build_and_save()
            time.sleep(interval_sec)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[landing] Background builder started ({interval_sec}s interval)")


if __name__ == "__main__":
    build_and_save()
