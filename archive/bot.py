"""
Telegram bot handlers + webhook entry point.

- init_bot() builds the Application and starts APScheduler.
- process_update(update_json) receives webhook POSTs from FastAPI.
- All command handlers remain unchanged.
"""
import json
import os
import sys
import re
import logging
import asyncio
import requests
from datetime import datetime, timezone, timedelta
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from collector import DataCollector
from analyzer import SentimentAnalyzer
from config import COMMODITY_CONFIGS
from groq_client import GroqAnalyzer
from firecrawl_client import FireCrawlClient

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MYT = timezone(timedelta(hours=8))

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

_MD2_SPECIAL = r"[_*\[\]()~`>#+\-=|{}.!]"


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

_BOT_STATUS = {
    "initialized": False,
    "polling": False,
    "webhook_set": False,
    "last_error": None,
    "last_success": None,
}


groq_client = GroqAnalyzer()
firecrawl_client = FireCrawlClient()


# ------------------------------------------------------------------
#  Subscriber persistence (unchanged from before)
# ------------------------------------------------------------------
class SubscriberStore:
    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def load(self):
        local_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscribers.json")
        try:
            if os.path.exists(local_file):
                with open(local_file, "r") as f:
                    data = json.load(f)
                    self._subs = set(data)
                    logger.info(f"Loaded {len(self._subs)} subscribers")
        except Exception:
            pass

    def save(self, subs):
        local_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscribers.json")
        try:
            with open(local_file, "w") as f:
                json.dump(list(subs), f, indent=2)
        except IOError:
            pass

    def add(self, chat_id):
        with self._lock:
            self._subs.add(chat_id)
            self.save(self._subs)

    def remove(self, chat_id):
        with self._lock:
            self._subs.discard(chat_id)
            self.save(self._subs)

    def list(self):
        with self._lock:
            return list(self._subs)

    def count(self):
        with self._lock:
            return len(self._subs)


store = SubscriberStore()


# ------------------------------------------------------------------
#  Report generator (unchanged)
# ------------------------------------------------------------------
def generate_report(commodity="gold", groq_client=None):
    cfg = COMMODITY_CONFIGS.get(commodity, COMMODITY_CONFIGS["gold"])
    sk = cfg.get("score_key", commodity)
    currency = cfg.get("currency", "$")
    collector = DataCollector(commodity=commodity)
    analyzer = SentimentAnalyzer(commodity=commodity, groq_client=groq_client)
    price_data = collector.fetch_price()
    market_data = collector.fcpo_market_data() if commodity == "fcpo" else None
    data = collector.collect_all(groq_client=groq_client, firecrawl_client=firecrawl_client)
    result = analyzer.run_full_analysis(data["articles"])

    a1 = result["analysis_1_macro"]
    a2 = result["analysis_2_sentiment"]
    a3 = result["analysis_3_dxy"]
    fs = result["final_synthesis"]
    meta = result["meta"]

    price_line = ""
    if price_data and price_data.get("price"):
        p = price_data["price"]
        price_line = f"*{escape_md2(cfg['price_label'])} Spot\\:* {currency}{escape_md2(f'{p:,.2f}')}"
        if price_data.get("change") is not None:
            chg = price_data["change"]
            pct = price_data["change_pct"]
            sign = "+" if chg >= 0 else ""
            emoji = "📈" if chg >= 0 else "📉"
            price_line += f" ({emoji} {sign}{escape_md2(f'{chg:,.2f}')} / {sign}{escape_md2(f'{pct:.2f}')}%)"

    macro_label = cfg.get("macro_label", "Macro Drivers")
    bias_label = meta.get("bias", "Neutral")
    bias_emoji = {"Strong Buy": "🟢", "Buy": "🟢", "Neutral": "⚪", "Sell": "🔴", "Strong Sell": "🔴"}.get(bias_label, "⚪")

    drivers = meta.get("top_drivers", [])
    drivers_text = ""
    if drivers:
        drivers_text = "\n🎯 *Key Drivers\\:*\n"
        for d in drivers:
            drivers_text += f"  • {escape_md2(d)}\n"

    groq_text = ""
    if groq_client and groq_client.available:
        just = groq_client.generate_justification(
            bias_label, meta.get("sentiment_score", 0),
            meta.get("dxy_bias", 0), meta.get("geo_intensity", 0),
            meta.get("macro_bias", 0), meta.get("contrarian", False),
            meta.get("supply_score", 0), commodity,
        )
        if just:
            groq_text = f"\n🤖 *Groq AI Justification\\:*\n{escape_md2(just)}\n"

    dxy_line = ""
    if "dxy" in meta and meta["dxy"] is not None:
        dxy_line = f"\n💵 *DXY\\:* {escape_md2(f'{meta['dxy']:.2f}')}"

    supply_line = ""
    if "supply" in meta and meta["supply"] is not None:
        supply_line = f"\n⛽ *Supply Score\\:* {escape_md2(f'{meta['supply']:.2f}')}"

    support_line = ""
    if "support" in meta and meta["support"] is not None:
        support_line = f"\n🪜 *Support\\:* {escape_md2(f'{meta['support']:.2f}')}"

    resistance_line = ""
    if "resistance" in meta and meta["resistance"] is not None:
        resistance_line = f"\n🧱 *Resistance\\:* {escape_md2(f'{meta['resistance']:.2f}')}"

    if commodity == "fcpo":
        report = f"""
📊 *{escape_md2(cfg['display_name'])} Report*
━━━━━━━━━━━━━━━
{price_line}
{drivers_text}
{bias_emoji} *Bias\\:* {escape_md2(bias_label)}
💪 *Sentiment\\:* {escape_md2(f'{meta.get('sentiment_score', 0):.1f}')}
📉 *Risk Mood\\:* {escape_md2(meta.get('risk_mood', 'Neutral'))}
🕐 *MYT Time\\:* {escape_md2(datetime.now(MYT).strftime('%I:%M %p'))}
{groq_text}
💍 *Prepared by @PedotTTRG*
        """.strip()
    else:
        report = f"""
📊 *{escape_md2(cfg['display_name'])} Report*
━━━━━━━━━━━━━━━
{price_line}
{dxy_line}
{drivers_text}
{bias_emoji} *Bias\\:* {escape_md2(bias_label)}
💪 *Sentiment\\:* {escape_md2(f'{meta.get('sentiment_score', 0):.1f}')}
📉 *Risk Mood\\:* {escape_md2(meta.get('risk_mood', 'Neutral'))}
🕐 *MYT Time\\:* {escape_md2(datetime.now(MYT).strftime('%I:%M %p'))}
{groq_text}
💍 *Prepared by @PedotTTRG*
        """.strip()

    return report, result["articles"]


# ------------------------------------------------------------------
#  Telegram Handlers
# ------------------------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username or "Trader"
    store.add(chat_id)
    logger.info(f"User {chat_id} (@{username}) subscribed")

    welcome = f"""
🚀 *Welcome\\, {escape_md2(username)}\\!*

You are now subscribed to *Commodity Sentiment Intelligence* daily reports\\.

*Available Commands\\:*
📈 `/report` — Gold \(XAU/USD\)
🛢️ `/report_wti` — WTI Crude Oil
🌴 `/report_fcpo` — FCPO Crude Palm Oil
ℹ️ `/status` — Check subscription
🛑 `/stop` — Unsubscribe

📅 Daily report at *6\\:01 AM MYT*

💍 *Prepared by @PedotTTRG*
    """.strip()

    support_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("☕ Support Us\\!", url=SENANGPAY_URL)],
    ])

    await context.bot.send_message(chat_id=chat_id, text=welcome, parse_mode="MarkdownV2", reply_markup=support_keyboard)


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    store.remove(chat_id)
    logger.info(f"User {chat_id} unsubscribed")
    await context.bot.send_message(
        chat_id=chat_id,
        text="🛑 *Unsubscribed\\!* You will no longer receive daily reports\\. Send `/start` to resubscribe\\.",
        parse_mode="MarkdownV2",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    is_sub = chat_id in store.list()
    count = store.count()
    status = "✅ *Subscribed*" if is_sub else "❌ *Not subscribed*"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"ℹ️ {status}\\. Total subscribers\\: {count}\.",
        parse_mode="MarkdownV2",
    )


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_report(update, context, "gold")


async def report_wti_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_report(update, context, "wti")


async def report_fcpo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_report(update, context, "fcpo")


async def _send_report(update: Update, context: ContextTypes.DEFAULT_TYPE, commodity: str):
    chat_id = update.effective_chat.id
    username = update.effective_user.username or "Trader"
    logger.info(f"User {chat_id} (@{username}) requested {commodity} report")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔄 Generating {commodity.upper()} report\\, please wait\\.",
        parse_mode="MarkdownV2",
    )
    try:
        report, articles = generate_report(commodity, groq_client)
        support_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("☕ Support Us\\!", url=SENANGPAY_URL)],
        ])
        await context.bot.send_message(chat_id=chat_id, text=report, parse_mode="MarkdownV2", reply_markup=support_keyboard)
        if articles:
            headlines = "\n".join([f"{i+1}\\. [{escape_md2(a['title'][:70])}]({escape_md2(a['link'])})" for i, a in enumerate(articles[:5])])
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📰 *Latest Headlines\\:*\n{headlines}",
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ *Sorry\\, failed to generate report\\.* Please try again later\\.",
            parse_mode="MarkdownV2",
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "support":
        await query.edit_message_text(
            text=f"☕ *Support Us\\!*\n\nClick here to contribute\\:\n{SENANGPAY_URL}",
            parse_mode="MarkdownV2",
        )


# ------------------------------------------------------------------
#  Daily report cron job (unchanged logic)
# ------------------------------------------------------------------
async def daily_report_job(application: Application):
    subs = store.list()
    if not subs:
        logger.info("No subscribers for daily report")
        return
    for commodity in ["gold", "wti", "fcpo"]:
        try:
            report, articles = generate_report(commodity, groq_client)
            for chat_id in subs:
                try:
                    support_keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("☕ Support Us\\!", url=SENANGPAY_URL)],
                    ])
                    await application.bot.send_message(chat_id=chat_id, text=report, parse_mode="MarkdownV2", reply_markup=support_keyboard)
                    if articles:
                        headlines = "\n".join([f"{i+1}\\. [{escape_md2(a['title'][:70])}]({escape_md2(a['link'])})" for i, a in enumerate(articles[:5])])
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=f"📰 *Latest Headlines\\:*\n{headlines}",
                            parse_mode="MarkdownV2",
                            disable_web_page_preview=True,
                        )
                    logger.info(f"Sent {commodity} daily report to {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send {commodity} report to {chat_id}: {e}")
            if commodity == "gold":
                await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Daily report failed for {commodity}: {e}")


# ------------------------------------------------------------------
#  Bot initialization for WEBHOOK mode
# ------------------------------------------------------------------
async def init_bot():
    """
    Initialize the Telegram bot Application and APScheduler.
    Returns (application, scheduler) tuple.
    Does NOT start polling — webhook receives updates via POST.
    """
    global _BOT_STATUS

    if not BOT_TOKEN:
        _BOT_STATUS["last_error"] = "TELEGRAM_BOT_TOKEN not set"
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    _BOT_STATUS["initialized"] = False
    _BOT_STATUS["polling"] = False
    _BOT_STATUS["webhook_set"] = False
    store.load()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("report", report_cmd))
    application.add_handler(CommandHandler("report_wti", report_wti_cmd))
    application.add_handler(CommandHandler("report_fcpo", report_fcpo_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CallbackQueryHandler(button_handler))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: application.create_task(daily_report_job(application)),
        CronTrigger(hour=22, minute=1, timezone=timezone.utc),
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: daily report at 6:01 AM MYT (22:01 UTC)")

    try:
        await application.initialize()
        _BOT_STATUS["initialized"] = True
        _BOT_STATUS["last_success"] = "initialized"
        logger.info("Bot initialized successfully")
    except Exception as e:
        _BOT_STATUS["last_error"] = f"Initialize failed: {e}"
        logger.error(f"Bot initialize failed: {e}")
        raise

    await application.start()
    logger.info("Bot started (webhook mode)")

    return application, scheduler


async def shutdown_bot(application, scheduler):
    """Graceful shutdown."""
    global _BOT_STATUS
    _BOT_STATUS["initialized"] = False
    _BOT_STATUS["webhook_set"] = False
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        await application.stop()
    except Exception:
        pass
    try:
        await application.shutdown()
    except Exception:
        pass
    logger.info("Bot shutdown complete")


# ------------------------------------------------------------------
#  Webhook entry point
# ------------------------------------------------------------------
def process_update(application, update_json: dict):
    """
    Called by FastAPI POST /webhook.
    Converts JSON dict to telegram.Update and processes it.
    """
    try:
        update = Update.de_json(update_json, application.bot)
        application.create_task(application.process_update(update))
    except Exception as e:
        logger.error(f"process_update error: {e}")
