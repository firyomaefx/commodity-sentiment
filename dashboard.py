import streamlit as st
import json
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone, timedelta
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collector import DataCollector
from analyzer import SentimentAnalyzer
from config import COMMODITY_CONFIGS, REFRESH_INTERVAL_SECONDS
from groq_client import GroqAnalyzer

st.set_page_config(
    page_title="Commodity Sentiment Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BIAS_COLORS = {
    "Strong Buy": "#30D158",
    "Buy": "#34C759",
    "Neutral": "#FFD60A",
    "Sell": "#FF453A",
    "Strong Sell": "#FF3B30",
}

MOOD_ICONS = {"Risk-Off": "🛡️", "Risk-On": "📈"}

APPLE_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', Roboto, Helvetica, Arial, sans-serif"

MYT = timezone(timedelta(hours=8))

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

groq_client = GroqAnalyzer()


@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def fetch_and_analyze(commodity="gold"):
    cfg = COMMODITY_CONFIGS.get(commodity, COMMODITY_CONFIGS["gold"])
    collector = DataCollector(commodity=commodity)
    analyzer = SentimentAnalyzer(commodity=commodity, groq_client=groq_client)
    price_data = collector.fetch_price()
    data = collector.collect_all(groq_client=groq_client)
    result = analyzer.run_full_analysis(data["articles"])
    result["collection_meta"] = {
        "total_articles": data["total_articles"],
        "rss_count": data["rss_count"],
        "web_count": data["web_count"],
        "timestamp": data["timestamp"],
        "price_label": cfg["price_label"],
    }
    return result, data, price_data


def render_gauge(score, title, min_val=-100, max_val=100):
    bar_color = "#FFD60A" if -25 <= score <= 25 else ("#30D158" if score > 25 else "#FF453A")
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=score,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": title, "font": {"size": 15, "color": "#86868B", "family": APPLE_FONT}},
        delta={"reference": 0, "increasing": {"color": "#30D158", "symbol": "▲"}, "decreasing": {"color": "#FF453A", "symbol": "▼"}},
        number={"font": {"size": 36, "color": "#F5F5F7", "family": APPLE_FONT, "weight": 600}},
        gauge={
            "axis": {
                "range": [min_val, max_val],
                "tickwidth": 0.5,
                "tickcolor": "rgba(142,142,147,0.3)",
                "tickfont": {"size": 9, "color": "#86868B", "family": APPLE_FONT},
            },
            "bar": {"color": bar_color, "thickness": 0.6, "line": {"width": 0}},
            "bgcolor": "rgba(0,0,0,0)",
            "steps": [
                {"range": [-100, -75], "color": "rgba(255,59,48,0.1)"},
                {"range": [-75, -25], "color": "rgba(255,69,58,0.07)"},
                {"range": [-25, 25], "color": "rgba(255,214,10,0.06)"},
                {"range": [25, 75], "color": "rgba(48,209,88,0.07)"},
                {"range": [75, 100], "color": "rgba(52,199,90,0.1)"},
            ],
            "threshold": {
                "line": {"color": "#F5F5F7", "width": 2},
                "thickness": 0.9,
                "value": score,
            },
        },
    ))
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#F5F5F7", "family": APPLE_FONT},
    )
    return fig


def render_category_bar(category_counts):
    if not category_counts:
        return None
    cats = list(category_counts.keys())
    vals = list(category_counts.values())
    colors = ["#FF9F0A" if v > 0 else "rgba(142,142,147,0.15)" for v in vals]
    fig = go.Figure(go.Bar(
        x=cats, y=vals, marker_color=colors, text=vals, textposition="auto",
        marker_line_width=0, marker_line_color="rgba(0,0,0,0)",
        textfont={"size": 12, "color": "#F5F5F7", "family": APPLE_FONT},
    ))
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=40, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#86868B", "size": 11, "family": APPLE_FONT},
        title={"text": "KEYWORD CATEGORY HITS", "font": {"size": 11, "color": "#86868B", "family": APPLE_FONT, "weight": 600}},
        xaxis=dict(tickangle=0, gridcolor="rgba(0,0,0,0)", tickfont={"size": 10, "color": "#86868B", "family": APPLE_FONT}),
        yaxis=dict(gridcolor="rgba(142,142,147,0.08)", tickfont={"size": 10, "color": "#86868B", "family": APPLE_FONT}),
    )
    return fig


def render_sentiment_timeline(articles):
    if not articles:
        return None
    df_data = []
    for a in articles:
        vader_s = a.get("vader_score", 0)
        df_data.append({"title": a["title"][:50], "score": vader_s, "category": ", ".join(a.get("categories", []))[:30]})
    df = pd.DataFrame(df_data)
    fig = px.bar(df, x=df.index, y="score", color="score",
                 color_continuous_scale=["#FF453A", "#FFD60A", "#30D158"],
                 hover_data=["title"])
    fig.update_traces(marker_line_width=0, marker_line_color="rgba(0,0,0,0)")
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#86868B", "size": 11, "family": APPLE_FONT},
        title={"text": "ARTICLE SENTIMENT DISTRIBUTION", "font": {"size": 11, "color": "#86868B", "family": APPLE_FONT, "weight": 600}},
        xaxis=dict(title="", gridcolor="rgba(0,0,0,0)", tickfont={"size": 9, "color": "#86868B"}),
        yaxis=dict(title="", gridcolor="rgba(142,142,147,0.08)", tickfont={"size": 9, "color": "#86868B"}),
        coloraxis_colorbar=dict(
            title="",
            tickfont={"size": 9, "color": "#86868B"},
            thickness=12,
            len=0.6,
        ),
    )
    return fig


def metric_card(label, value, delta=None, delta_color=None):
    delta_html = ""
    if delta is not None:
        dc = delta_color or ("#30D158" if "+" in str(delta) else "#FF453A" if "-" in str(delta) else "#86868B")
        delta_html = f'<div style="color:{dc}; font-size:15px; font-weight:600; margin-top:2px; font-family:{APPLE_FONT};">{delta}</div>'
    return f"""
    <div style="
        background: rgba(28,28,30,0.75);
        backdrop-filter: blur(40px);
        -webkit-backdrop-filter: blur(40px);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 20px;
        padding: 28px 32px;
    ">
        <div style="
            color: #86868B;
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-family: {APPLE_FONT};
            margin-bottom: 8px;
        ">{label}</div>
        <div style="
            color: #F5F5F7;
            font-size: 36px;
            font-weight: 600;
            letter-spacing: -0.02em;
            font-variant-numeric: tabular-nums;
            font-family: {APPLE_FONT};
            line-height: 1.1;
        ">{value}</div>
        {delta_html}
    </div>
    """


def main():
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        [data-testid="stAppViewContainer"] {{
            background: #0A0A0A;
        }}
        .stApp {{
            background: #0A0A0A;
            color: #F5F5F7;
            font-family: {APPLE_FONT};
        }}
        [data-testid="stHeader"] {{
            background: #0A0A0A;
        }}
        .stSidebar {{
            background: #111111 !important;
            border-right: 1px solid #1C1C1E !important;
        }}
        section[data-testid="stSidebar"] {{
            background: #111111 !important;
        }}

        h1, h2, h3, h4, h5, h6 {{
            color: #F5F5F7 !important;
            font-family: {APPLE_FONT} !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em !important;
        }}
        .stMarkdown, .stText, p {{
            color: #8E8E93 !important;
            font-family: {APPLE_FONT} !important;
        }}
        .stCaption {{
            color: #6E6E73 !important;
            font-family: {APPLE_FONT} !important;
        }}
        .stDivider {{
            border-top-color: rgba(255,255,255,0.06) !important;
        }}

        .stButton > button {{
            background: rgba(255,255,255,0.08) !important;
            color: #F5F5F7 !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            border-radius: 999px !important;
            padding: 10px 28px !important;
            font-weight: 600 !important;
            font-family: {APPLE_FONT} !important;
            font-size: 14px !important;
            transition: all 0.15s ease !important;
            min-height: 44px !important;
        }}
        .stButton > button:hover {{
            background: rgba(255,255,255,0.14) !important;
            border-color: rgba(255,255,255,0.22) !important;
        }}
        .stButton > button:active {{
            background: rgba(255,255,255,0.2) !important;
        }}

        .stExpander {{
            border: 1px solid rgba(255,255,255,0.06) !important;
            border-radius: 14px !important;
            background: rgba(30,30,32,0.6) !important;
            margin-bottom: 6px !important;
        }}
        .stExpander:hover {{
            border-color: rgba(255,255,255,0.1) !important;
        }}
        .stExpander summary {{
            font-family: {APPLE_FONT} !important;
            color: #F5F5F7 !important;
            font-size: 14px !important;
            font-weight: 500 !important;
            padding: 12px 16px !important;
        }}

        a {{
            color: #0A84FF !important;
            text-decoration: none !important;
        }}
        a:hover {{
            text-decoration: underline !important;
        }}
        code {{
            font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace !important;
            background: rgba(255,255,255,0.06) !important;
            border-radius: 8px !important;
            padding: 2px 8px !important;
            color: #FFD60A !important;
        }}

        [data-testid="stMetricValue"] {{
            font-family: {APPLE_FONT} !important;
            font-size: 32px !important;
            font-weight: 700 !important;
        }}
        [data-testid="stMetricLabel"] {{
            font-family: {APPLE_FONT} !important;
        }}

        .element-container {{
            margin-bottom: 4px !important;
        }}

        @media (max-width: 768px) {{
            .stButton > button {{
                font-size: 13px !important;
                padding: 10px 18px !important;
            }}
        }}
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown(f"<div style='color:#8E8E93;font-size:13px;font-weight:600;letter-spacing:0.1em;margin-bottom:8px;font-family:{APPLE_FONT};'>ABOUT</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='color:#8E8E93;font-size:12px;line-height:1.6;font-family:{APPLE_FONT};'>Real-time sentiment for Gold, WTI Crude Oil & FCPO Palm Oil.<br><br>Groq AI + VADER NLP engine scanning RSS feeds and news articles.<br><br>Daily Telegram report at <b>6:01 AM MYT</b>.<br><br><a href='https://t.me/PedotTTRG' style='color:#0A84FF;'>Prepared by @PedotTTRG</a></div>", unsafe_allow_html=True)

    if "commodity" not in st.session_state:
        st.session_state["commodity"] = "gold"

    commodity = st.session_state["commodity"]
    cfg = COMMODITY_CONFIGS.get(commodity, COMMODITY_CONFIGS["gold"])

    TELEGRAM_BOT = os.environ.get("TELEGRAM_BOT_USERNAME", "SentimentIntelligence26Bot")
    SENANGPAY_URL = os.environ.get("SENANGPAY_URL", "https://app.senangpay.my/payment/177739832230")

    st.markdown(f'''<div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:12px;">
<div style="flex:1;min-width:200px;">
<div style="color:#8E8E93;font-size:13px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;font-family:{APPLE_FONT};">Commodity Sentiment Intelligence</div>
<div style="color:#F5F5F7;font-size:44px;font-weight:700;letter-spacing:-0.03em;line-height:1.1;margin-top:2px;font-family:{APPLE_FONT};">{cfg["display_name"]}</div>
</div>
<div style="text-align:right;">
<div style="display:flex;align-items:center;gap:10px;justify-content:flex-end;flex-wrap:wrap;">
<div>
<div style="color:#8E8E93;font-size:14px;font-family:{APPLE_FONT};">{datetime.now(MYT).strftime("%I:%M %p")} MYT</div>
<div style="color:#6E6E73;font-size:11px;font-family:{APPLE_FONT};margin-top:2px;">Auto-refresh {REFRESH_INTERVAL_SECONDS}s</div>
</div>
<a href="https://t.me/{TELEGRAM_BOT}" target="_blank" style="display:inline-flex;align-items:center;gap:5px;background:#0A84FF;border:1px solid #0A84FF;border-radius:999px;padding:8px 18px;color:#FFFFFF;font-family:{APPLE_FONT};font-size:13px;font-weight:600;text-decoration:none;white-space:nowrap;margin-left:8px;"><span style="font-size:14px;">✈️</span> Get Via Telegram</a>
<a href="{SENANGPAY_URL}" target="_blank" style="display:inline-flex;align-items:center;gap:5px;background:#FFD60A;border:1px solid #FFD60A;border-radius:999px;padding:8px 18px;color:#000000;font-family:{APPLE_FONT};font-size:13px;font-weight:600;text-decoration:none;white-space:nowrap;"><span style="font-size:14px;">☕</span> Support Us</a>
</div>
</div>
</div>''', unsafe_allow_html=True)

    col_gold, col_wti, col_fcpo = st.columns([1, 1, 1])
    with col_gold:
        if st.button("🥇 GOLD", key="btn_gold", use_container_width=True):
            st.session_state["commodity"] = "gold"
            st.rerun()
    with col_wti:
        if st.button("🛢️ WTI CRUDE OIL", key="btn_wti", use_container_width=True):
            st.session_state["commodity"] = "wti"
            st.rerun()
    with col_fcpo:
        if st.button("🌴 FCPO PALM OIL", key="btn_fcpo", use_container_width=True):
            st.session_state["commodity"] = "fcpo"
            st.rerun()

    if st.button("Refresh Analysis", use_container_width=False):
        st.cache_data.clear()
        st.rerun()

    result, data, price_data = fetch_and_analyze(commodity)

    a1 = result["analysis_1_macro"]
    a2 = result["analysis_2_sentiment"]
    a3 = result["analysis_3_dxy"]
    fs = result["final_synthesis"]
    meta = result["meta"]
    cm = result["collection_meta"]

    sk = cfg["score_key"]
    bias_key = f"final_{sk}_bias"
    score_key = f"{sk}_sentiment_score"

    bias_color = BIAS_COLORS.get(fs[bias_key], "#FFD60A")

    currency = cfg.get("currency", "$")
    price_str = ""
    if price_data and price_data.get("price"):
        price_val = price_data["price"]
        price_str = f'<span style="color:#FFD60A;font-size:2.4em;font-weight:700;letter-spacing:-0.03em;font-variant-numeric:tabular-nums;font-family:{APPLE_FONT};">{currency}{price_val:,.2f}</span>'
        if price_data.get("change") is not None:
            chg = price_data["change"]
            pct = price_data["change_pct"]
            chg_color = "#30D158" if chg >= 0 else "#FF453A"
            sign = "+" if chg >= 0 else ""
            price_str += f'<div style="color:{chg_color};font-size:15px;font-weight:600;margin-top:4px;font-family:{APPLE_FONT};">{sign}{chg:.2f} ({sign}{pct:.2f}%)</div>'

    pull_time_str = ""
    try:
        pull_dt = datetime.fromisoformat(cm["timestamp"].replace("Z", "+00:00")).astimezone(MYT)
        pull_time_str = pull_dt.strftime("%I:%M %p")
    except Exception:
        pull_time_str = "—"

    ai_badge = groq_client.get_badge_html() if groq_client and groq_client.available else ""

    st.markdown(f'''<div style="background:#1C1C1E;border:1px solid #2C2C2E;border-radius:20px;padding:32px 40px;margin-bottom:24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:24px;">
<div style="flex:1;min-width:280px;">
<div style="color:#8E8E93;font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;font-family:{APPLE_FONT};margin-bottom:6px;">Signal{ai_badge}</div>
<div style="color:{bias_color};font-size:2.6em;font-weight:700;letter-spacing:-0.03em;line-height:1;font-family:{APPLE_FONT};">{fs[bias_key]}</div>
<div style="color:#8E8E93;font-size:14px;margin-top:10px;max-width:560px;line-height:1.5;font-family:{APPLE_FONT};">{fs["justification"]}</div>
</div>
<div style="text-align:right;flex-shrink:0;min-width:200px;">
<div style="color:#8E8E93;font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;font-family:{APPLE_FONT};margin-bottom:6px;">{cfg["price_label"]}</div>
{price_str}
<div style="color:#6E6E73;font-size:11px;margin-top:8px;font-family:{APPLE_FONT};">Data as of {pull_time_str} MYT</div>
</div>
</div>''', unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(metric_card("Sentiment Score", f"{a2[score_key]}", a2["sentiment_label"]), unsafe_allow_html=True)
    with col2:
        st.markdown(metric_card("Market Mood", a1["overall_market_mood"]), unsafe_allow_html=True)
    with col3:
        dxy_delta = "↑ Dollar" if a3["dxy_directional_bias"] == "Bullish" else "↓ Dollar" if a3["dxy_directional_bias"] == "Bearish" else "—"
        dxy_dc = "#FF453A" if a3["dxy_directional_bias"] == "Bullish" else "#30D158" if a3["dxy_directional_bias"] == "Bearish" else "#86868B"
        st.markdown(metric_card("DXY Bias", a3["dxy_directional_bias"], dxy_delta, dxy_dc), unsafe_allow_html=True)
    with col4:
        if commodity in ("wti", "fcpo"):
            supply_score = meta.get("supply_score", 0)
            supply_label = "Tight" if supply_score > 0.15 else "Oversupply" if supply_score < -0.15 else "Balanced"
            supply_dc = "#30D158" if supply_score > 0.15 else "#FF453A" if supply_score < -0.15 else "#FFD60A"
            st.markdown(metric_card("Supply", supply_label, f"{supply_score:+d}", supply_dc), unsafe_allow_html=True)
        else:
            ca_delta = "Over-leveraged" if a2["contrarian_signal"] == "YES" else "Normal range"
            ca_dc = "#FF9F0A" if a2["contrarian_signal"] == "YES" else "#30D158"
            st.markdown(metric_card("Contrarian Alert", a2["contrarian_signal"], ca_delta, ca_dc), unsafe_allow_html=True)

    st.markdown("<div style='border-top: 1px solid rgba(255,255,255,0.06); margin: 28px 0;'></div>", unsafe_allow_html=True)

    col_gauge, col_bar, col_timeline = st.columns([1, 1, 1.5])
    with col_gauge:
        fig_gauge = render_gauge(a2[score_key], "SENTIMENT GAUGE")
        st.plotly_chart(fig_gauge, width="stretch")

    with col_bar:
        fig_cat = render_category_bar(meta["category_counts"])
        if fig_cat:
            st.plotly_chart(fig_cat, width="stretch")

    with col_timeline:
        fig_tl = render_sentiment_timeline(data["articles"])
        if fig_tl:
            st.plotly_chart(fig_tl, width="stretch")

    st.markdown("<div style='border-top: 1px solid rgba(255,255,255,0.06); margin: 28px 0;'></div>", unsafe_allow_html=True)

    col_macro, col_geo = st.columns(2)
    with col_macro:
        st.markdown(f'<div><div style="color:#86868B;font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;font-family:{APPLE_FONT};margin-bottom:16px;">Macro & Fed</div><div style="color:#F5F5F7;font-size:14px;line-height:1.6;font-family:{APPLE_FONT};">{a1["macro_event_impact"]}</div><div style="margin-top:12px;color:#86868B;font-size:12px;font-family:{APPLE_FONT};">Bias: <span style="color:#0A84FF;font-weight:600;">{meta["macro_bias"]}</span></div></div>', unsafe_allow_html=True)
    with col_geo:
        st.markdown(f'<div><div style="color:#86868B;font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;font-family:{APPLE_FONT};margin-bottom:16px;">Geopolitical</div><div style="color:#F5F5F7;font-size:14px;line-height:1.6;font-family:{APPLE_FONT};">{a1["geopolitical_summary"]}</div><div style="margin-top:12px;color:#86868B;font-size:12px;font-family:{APPLE_FONT};">Intensity: <span style="color:#FF9F0A;font-weight:600;">{meta["geo_intensity"]}</span></div></div>', unsafe_allow_html=True)

    st.markdown("<div style='border-top: 1px solid rgba(255,255,255,0.06); margin: 28px 0;'></div>", unsafe_allow_html=True)

    st.markdown(f"<div style='color:#86868B;font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;font-family:{APPLE_FONT};margin-bottom:12px;'>How to Read</div>", unsafe_allow_html=True)
    g1, g2, g3 = st.columns(3)
    with g1:
        st.markdown(f"<div style='background:rgba(28,28,30,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:16px 20px;margin-bottom:6px;'><div style='color:#F5F5F7;font-size:13px;font-weight:600;font-family:{APPLE_FONT};margin-bottom:6px;'>Sentiment Score</div><div style='color:#86868B;font-size:11px;line-height:1.5;font-family:{APPLE_FONT};'>Range &minus;100 to +100.<br><span style='color:#30D158;'>+50/+100</span> Bullish &middot; <span style='color:#FF453A;'>&minus;50/&minus;100</span> Bearish<br><span style='color:#FFD60A;'>-20/+20</span> Neutral<br><i>VADER x keyword weight</i></div></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='background:rgba(28,28,30,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:16px 20px;margin-bottom:6px;'><div style='color:#F5F5F7;font-size:13px;font-weight:600;font-family:{APPLE_FONT};margin-bottom:6px;'>DXY Bias</div><div style='color:#86868B;font-size:11px;line-height:1.5;font-family:{APPLE_FONT};'>US Dollar direction.<br>Weak dollar = commodities go up<br>Strong dollar = commodities go down</div></div>", unsafe_allow_html=True)
    with g2:
        st.markdown(f"<div style='background:rgba(28,28,30,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:16px 20px;margin-bottom:6px;'><div style='color:#F5F5F7;font-size:13px;font-weight:600;font-family:{APPLE_FONT};margin-bottom:6px;'>Market Mood</div><div style='color:#86868B;font-size:11px;line-height:1.5;font-family:{APPLE_FONT};'>📈 Risk-On = bullish for commodities<br>🛡️ Risk-Off = safe haven (gold up, oil demand down)</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='background:rgba(28,28,30,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:16px 20px;margin-bottom:6px;'><div style='color:#F5F5F7;font-size:13px;font-weight:600;font-family:{APPLE_FONT};margin-bottom:6px;'>Contrarian Alert</div><div style='color:#86868B;font-size:11px;line-height:1.5;font-family:{APPLE_FONT};'>⚠️ YES = sentiment over-leveraged, reversal possible<br>✅ Normal = within safe range</div></div>", unsafe_allow_html=True)
    with g3:
        st.markdown(f"<div style='background:rgba(28,28,30,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:16px 20px;margin-bottom:6px;'><div style='color:#F5F5F7;font-size:13px;font-weight:600;font-family:{APPLE_FONT};margin-bottom:6px;'>VADER (per article)</div><div style='color:#86868B;font-size:11px;line-height:1.5;font-family:{APPLE_FONT};'>🟢 > +0.05 positive article<br>🟡 &minus;0.05 to +0.05 neutral<br>🔴 < &minus;0.05 negative article</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='background:rgba(28,28,30,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:16px 20px;margin-bottom:6px;'><div style='color:#F5F5F7;font-size:13px;font-weight:600;font-family:{APPLE_FONT};margin-bottom:6px;'>Supply (WTI Only)</div><div style='color:#86868B;font-size:11px;line-height:1.5;font-family:{APPLE_FONT};'>Tight = bullish (OPEC cuts, war)<br>Balanced = neutral<br>Oversupply = bearish</div></div>", unsafe_allow_html=True)

    st.markdown("<div style='border-top: 1px solid rgba(255,255,255,0.06); margin: 28px 0;'></div>", unsafe_allow_html=True)

    st.markdown(f'<div style="color:#86868B;font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;font-family:{APPLE_FONT};margin-bottom:16px;">Intelligence Feed</div><div style="color:#636366;font-size:12px;font-family:{APPLE_FONT};margin-bottom:12px;">{len(data["articles"])} articles from {cm["total_articles"]} collected &middot; {cm["rss_count"]} RSS &middot; {cm["web_count"]} web</div>', unsafe_allow_html=True)

    articles_to_show = data["articles"][:20]
    if articles_to_show:
        for i, article in enumerate(articles_to_show):
            cat_str = " &middot; ".join(article.get("categories", []))
            vader_s = article.get("vader_score", 0)
            ic = "#30D158" if vader_s > 0.05 else "#FF453A" if vader_s < -0.05 else "#FFD60A"
            ks = article.get("keyword_score", 0)
            badge = f'<span style="background:rgba(255,255,255,0.06);color:#86868B;font-size:11px;padding:2px 8px;border-radius:980px;font-family:{APPLE_FONT};font-weight:600;">{ks}</span>'
            src = f'<div style="margin-top:6px;"><a href="{article["link"]}" style="font-size:12px;font-family:{APPLE_FONT};">Source</a></div>' if article.get("link") else ""
            fetch_str = ""
            ft = article.get("fetched_at", "")
            try:
                fetch_dt = datetime.fromisoformat(ft.replace("Z", "+00:00")).astimezone(MYT)
                fetch_str = fetch_dt.strftime("%I:%M %p")
            except Exception:
                fetch_str = ""
            ts_line = f'<div style="color:#636366;font-size:10px;font-family:{APPLE_FONT};margin-top:4px;">Extracted {fetch_str} MYT</div>' if fetch_str else ""
            st.markdown(f'<div style="background:rgba(28,28,30,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:16px 20px;margin-bottom:6px;"><div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;"><div style="width:8px;height:8px;border-radius:50%;background:{ic};flex-shrink:0;"></div><div style="color:#F5F5F7;font-size:14px;font-weight:500;font-family:{APPLE_FONT};flex:1;">{article["title"][:90]}</div>{badge}</div><div style="color:#86868B;font-size:11px;font-family:{APPLE_FONT};margin-bottom:4px;">{cat_str}</div><div style="color:#86868B;font-size:11px;font-family:{APPLE_FONT};">VADER <span style="color:{ic};font-weight:600;">{vader_s:.3f}</span></div>{ts_line}<div style="color:#AEAEB2;font-size:13px;line-height:1.5;margin-top:6px;font-family:{APPLE_FONT};">{article["summary"][:200]}</div>{src}</div>', unsafe_allow_html=True)



    st.markdown("<div style='border-top: 1px solid rgba(255,255,255,0.06); margin: 28px 0;'></div>", unsafe_allow_html=True)

    st.markdown(f'<div style="text-align:center;color:#636366;font-size:11px;font-family:{APPLE_FONT};margin-bottom:20px;">Daily reports at 6:01 AM MYT &middot; /report /report\\_wti /report\\_fcpo on-demand &middot; VADER + Groq AI Engine<br><br><span style="color:#86868B;">Prepared by</span> <a href="https://t.me/PedotTTRG" target="_blank" style="color:#0A84FF;text-decoration:none;">@PedotTTRG</a></div>', unsafe_allow_html=True)

    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=REFRESH_INTERVAL_SECONDS * 1000, key="datarefresh")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
