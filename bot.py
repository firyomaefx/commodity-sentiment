import json
import os
import sys
import re
import logging
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from collector import DataCollector
from analyzer import SentimentAnalyzer
from config import COMMODITY_CONFIGS

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MYT = timezone(timedelta(hours=8))

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

_MD2_SPECIAL = r"[_*[\]()~`>#+\-=|{}.!]"


def escape_md2(text):
    return re.sub(f"([{re.escape(_MD2_SPECIAL)}])", r"\\\1", str(text))


def load_env():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


load_env()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SENANGPAY_URL = os.environ.get("SENANGPAY_URL", "https://app.senangpay.my/payment/177739832230")
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "")
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID", "")


class SubscriberStore:
    def __init__(self):
        self._cache = {}
        self._use_jsonbin = bool(JSONBIN_API_KEY and JSONBIN_BIN_ID)

    def load(self):
        if self._use_jsonbin:
            try:
                resp = requests.get(
                    f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
                    headers={"X-Master-Key": JSONBIN_API_KEY},
                    timeout=10,
                )
                if resp.status_code == 200:
                    self._cache = resp.json().get("record", {})
                    logger.info(f"Loaded {len(self._cache)} subscribers from JSONBin")
                    return self._cache
            except Exception as e:
                logger.error(f"JSONBin load failed: {e}")

        local_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscribers.json")
        if os.path.exists(local_file):
            try:
                with open(local_file, "r") as f:
                    self._cache = json.load(f)
                logger.info(f"Loaded {len(self._cache)} subscribers from local file")
            except (json.JSONDecodeError, IOError):
                self._cache = {}
        return self._cache

    def save(self, subs):
        self._cache = subs

        if self._use_jsonbin:
            try:
                resp = requests.put(
                    f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
                    headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"},
                    json=subs,
                    timeout=10,
                )
                if resp.status_code == 200:
                    logger.info(f"Saved {len(subs)} subscribers to JSONBin")
                    return
            except Exception as e:
                logger.error(f"JSONBin save failed: {e}")

        local_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscribers.json")
        try:
            with open(local_file, "w") as f:
                json.dump(subs, f, indent=2)
            logger.info(f"Saved {len(subs)} subscribers to local file")
        except IOError as e:
            logger.error(f"Local save failed: {e}")


store = SubscriberStore()


def generate_report(commodity="gold"):
    cfg = COMMODITY_CONFIGS.get(commodity, COMMODITY_CONFIGS["gold"])
    sk = cfg.get("score_key", commodity)
    collector = DataCollector(commodity=commodity)
    analyzer = SentimentAnalyzer(commodity=commodity)
    price_data = collector.fetch_price()
    data = collector.collect_all()
    result = analyzer.run_full_analysis(data["articles"])

    a1 = result["analysis_1_macro"]
    a2 = result["analysis_2_sentiment"]
    a3 = result["analysis_3_dxy"]
    fs = result["final_synthesis"]
    meta = result["meta"]

    price_line = ""
    if price_data and price_data.get("price"):
        p = price_data["price"]
        price_line = f"*{escape_md2(cfg['price_label'])} Spot\\:* ${p:,.2f}"
        if price_data.get("change") is not None:
            chg = price_data["change"]
            pct = price_data["change_pct"]
            sign = "+" if chg >= 0 else ""
            arrow = "🟢" if chg >= 0 else "🔴"
            price_line += f"  {arrow} {sign}{chg:.2f} \\({sign}{pct:.2f}%\\)"

    bias_emoji = {"Strong Buy": "🟢🟢", "Buy": "🟢", "Neutral": "🟡", "Sell": "🔴", "Strong Sell": "🔴🔴"}
    bias_key = f"final_{sk}_bias"
    score_key = f"{sk}_sentiment_score"
    be = bias_emoji.get(fs[bias_key], "🟡")
    mood_emoji = "🛡️" if a1["overall_market_mood"] == "Risk-Off" else "📈"
    contrarian_emoji = "⚠️" if a2["contrarian_signal"] == "YES" else "✅"

    cat_counts = meta.get("category_counts", {})
    cat_line = " \\| ".join(f"{escape_md2(k.title())}: {v}" for k, v in cat_counts.items() if v > 0)

    top_articles = data["articles"][:5]
    articles_text = ""
    for i, a in enumerate(top_articles, 1):
        vs = a.get("vader_score", 0)
        indicator = "🟢" if vs > 0.05 else "🔴" if vs < -0.05 else "🟡"
        title = escape_md2(a["title"][:60])
        articles_text += f"\n{i}\\. {indicator} _{title}_"

    supply_line = ""
    if commodity == "wti":
        supply_score = meta.get("supply_score", 0)
        supply_label = "Tight" if supply_score > 0 else "Oversupply" if supply_score < 0 else "Balanced"
        supply_line = f"\n🛢️ *Supply\\:* {escape_md2(supply_label)} \\({supply_score}\\)"

    report = f"""*{escape_md2(cfg['display_name'])} Sentiment Report*
📅 {escape_md2(datetime.now(MYT).strftime('%d %b %Y, %H:%M'))} MYT

{price_line}

*━━━ SIGNAL ━━━*
{be} *{escape_md2(fs[bias_key])}*

*━━━ METRICS ━━━*
📊 *Sentiment\\:* {a2[score_key]} \\({escape_md2(a2['sentiment_label'])}\\)
{mood_emoji} *Mood\\:* {escape_md2(a1['overall_market_mood'])}
💵 *DXY\\:* {escape_md2(a3['dxy_directional_bias'])}
{contrarian_emoji} *Contrarian\\:* {escape_md2(a2['contrarian_signal'])}{supply_line}

*━━━ MACRO ━━━*
{escape_md2(a1['macro_event_impact'])}

*━━━ GEOPOLITICAL ━━━*
{escape_md2(a1['geopolitical_summary'])}

*━━━ KEYWORDS ━━━*
{cat_line}

*━━━ TOP HEADLINES ━━━*{articles_text}

*━━━ JUSTIFICATION ━━━*
{escape_md2(fs['justification'])}

_Data\\: VADER \\+ Rule\\-Based \\| {meta['articles_analyzed']} articles_"""

    return report


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    username = escape_md2(update.effective_user.username or update.effective_user.first_name or "Unknown")
    subs = store.load()

    if chat_id in subs:
        await update.message.reply_text(
            f"✅ You're already subscribed, *{username}*\\!\n\n"
            "You'll receive daily reports at 6:01 AM MYT\\.\n\n"
            "Commands:\n"
            "/report — Gold report now\n"
            "/report\\_wti — WTI report now\n"
            "/stop — Unsubscribe\n"
            "/status — Check status",
            parse_mode="MarkdownV2",
        )
        return

    subs[chat_id] = username
    store.save(subs)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥇 Gold Report", callback_data="report_gold"),
         InlineKeyboardButton("🛢️ WTI Report", callback_data="report_wti")],
        [InlineKeyboardButton("☕ Support RM1.99", url=SENANGPAY_URL)],
    ])

    await update.message.reply_text(
        f"Welcome, *{username}*\\! 🎉\n\n"
        "You're now subscribed to *Commodity Sentiment Reports*\\.\n\n"
        "🌟 *Your Perks:*\n"
        "🕕 Daily Gold \\+ WTI reports at *6:01 AM MYT*\n"
        "📊 On-demand /report \\| /report\\_wti anytime\n"
        "📱 Instant delivery to your phone\n\n"
        "Commands:\n"
        "🥇 /report — Gold report now\n"
        "🛢️ /report\\_wti — WTI report now\n"
        "🚫 /stop — Unsubscribe\n\n"
        "☕ Support us: *RM1\\.99* via SenangPay\n\n"
        "Tap the buttons below\\!",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )
    logger.info(f"New subscriber: {chat_id} ({username})")


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = store.load()

    if chat_id not in subs:
        await update.message.reply_text(
            "You're not subscribed\\. Subscribe with /start",
            parse_mode="MarkdownV2",
        )
        return

    username = escape_md2(subs.pop(chat_id))
    store.save(subs)
    await update.message.reply_text(
        f"👋 Unsubscribed, *{username}*\\. You won't receive daily reports anymore\\.\n\n"
        "Resubscribe anytime with /start",
        parse_mode="MarkdownV2",
    )
    logger.info(f"Unsubscribed: {chat_id} ({username})")


async def _send_report(chat_or_query, commodity):
    try:
        report = await asyncio.to_thread(generate_report, commodity)
        await chat_or_query.reply_text(report, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"{commodity} report generation failed: {e}", exc_info=True)
        await chat_or_query.reply_text(f"❌ Failed to generate report\\: {escape_md2(str(e)[:100])}", parse_mode="MarkdownV2")


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Generating Gold report\\.\\.\\.", parse_mode="MarkdownV2")
    await _send_report(update.message, "gold")


async def report_wti_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Generating WTI report\\.\\.\\.", parse_mode="MarkdownV2")
    await _send_report(update.message, "wti")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = store.load()
    is_sub = chat_id in subs
    total_subs = len(subs)

    status = "✅ Subscribed" if is_sub else "❌ Not subscribed"
    await update.message.reply_text(
        f"*Your Status:* {status}\n*Total Subscribers:* {total_subs}\n*Daily Reports:* Gold \\+ WTI at 6:01 AM MYT",
        parse_mode="MarkdownV2",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    commodity = "gold" if query.data == "report_gold" else "wti" if query.data == "report_wti" else None
    if commodity:
        label = "Gold" if commodity == "gold" else "WTI"
        await query.message.reply_text(f"⏳ Generating {label} report\\.\\.\\.", parse_mode="MarkdownV2")
        await _send_report(query.message, commodity)


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    subs = store.load()
    if not subs:
        logger.info("No subscribers, skipping daily report")
        return

    logger.info(f"Sending daily reports to {len(subs)} subscribers")
    for commodity in ["gold", "wti"]:
        try:
            report = await asyncio.to_thread(generate_report, commodity)
        except Exception as e:
            logger.error(f"Daily {commodity} report generation failed: {e}", exc_info=True)
            continue

        for chat_id, username in subs.items():
            try:
                await context.bot.send_message(
                    chat_id=int(chat_id),
                    text=report,
                    parse_mode="MarkdownV2",
                )
                logger.info(f"Sent {commodity} report to {chat_id} ({username})")
            except Exception as e:
                logger.error(f"Failed to send {commodity} report to {chat_id}: {e}")

        if commodity == "gold":
            await asyncio.sleep(30)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"commodity-sentiment-bot"}')

    def log_message(self, format, *args):
        pass


def run_health_server(port=8502):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


async def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set! Set it in .env or as environment variable.")
        sys.exit(1)

    store.load()

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("Health server started on port 8502")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("report_wti", report_wti_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: app.create_task(daily_report_job(app)),
        CronTrigger(hour=22, minute=1, timezone=timezone.utc),
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: daily report at 6:01 AM MYT (22:01 UTC)")

    logger.info("Bot starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())