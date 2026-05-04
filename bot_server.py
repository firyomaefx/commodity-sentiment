"""
FastAPI webhook server for Telegram bot.

- Lifespan initializes Application + APScheduler
- POST /webhook receives Telegram updates
- GET /set_webhook registers webhook URL with Telegram
- GET /health and /debug for monitoring
- Daily cron runs independently via APScheduler
"""
import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from bot import init_bot, shutdown_bot, process_update, _BOT_STATUS

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("bot_server")

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
if not WEBHOOK_URL:
    # Auto-derive from Render service name
    service_name = "commodity-sentiment-bot"
    WEBHOOK_URL = f"https://{service_name}.onrender.com/webhook"

_app_instance = None
_scheduler_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _app_instance, _scheduler_instance
    try:
        logger.info("FastAPI lifespan: initializing bot...")
        _app_instance, _scheduler_instance = await init_bot()
        logger.info("FastAPI lifespan: bot initialized")

        # Register webhook with Telegram
        try:
            await _app_instance.bot.set_webhook(
                url=WEBHOOK_URL,
                allowed_updates=["message", "callback_query"],
            )
            _BOT_STATUS["webhook_set"] = True
            _BOT_STATUS["last_success"] = f"webhook set: {WEBHOOK_URL}"
            logger.info(f"Webhook registered: {WEBHOOK_URL}")
        except Exception as e:
            _BOT_STATUS["last_error"] = f"Webhook set failed: {e}"
            logger.error(f"Failed to set webhook: {e}")

        yield
    finally:
        logger.info("FastAPI lifespan: shutting down bot...")
        if _app_instance:
            await shutdown_bot(_app_instance, _scheduler_instance)
        logger.info("FastAPI lifespan: shutdown complete")


fastapi_app = FastAPI(lifespan=lifespan)


@fastapi_app.post("/webhook")
async def webhook(request: Request):
    """Receive Telegram updates."""
    try:
        body = await request.json()
        if _app_instance:
            process_update(_app_instance, body)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@fastapi_app.get("/set_webhook")
async def set_webhook():
    """Manually trigger webhook registration."""
    if not _app_instance:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Bot not initialized"})
    try:
        await _app_instance.bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=["message", "callback_query"],
        )
        _BOT_STATUS["webhook_set"] = True
        return {"ok": True, "webhook_url": WEBHOOK_URL}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@fastapi_app.get("/delete_webhook")
async def delete_webhook():
    """Remove webhook (useful for switching back to polling locally)."""
    if not _app_instance:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Bot not initialized"})
    try:
        await _app_instance.bot.delete_webhook()
        _BOT_STATUS["webhook_set"] = False
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@fastapi_app.get("/health")
async def health():
    alive = _app_instance is not None and _BOT_STATUS.get("initialized", False)
    return {
        "status": "ok" if alive else "degraded",
        "service": "commodity-sentiment-bot",
        "bot_initialized": alive,
        "webhook_set": _BOT_STATUS.get("webhook_set", False),
        "webhook_url": WEBHOOK_URL,
        **_BOT_STATUS,
    }


@fastapi_app.get("/debug")
async def debug():
    return {
        "status": "ok",
        "bot_initialized": _BOT_STATUS.get("initialized", False),
        "webhook_set": _BOT_STATUS.get("webhook_set", False),
        "webhook_url": WEBHOOK_URL,
        "bot_status": _BOT_STATUS,
        "env_check": {
            "token_set": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
            "groq_set": bool(os.environ.get("GROQ_API_KEY")),
            "firecrawl_set": bool(os.environ.get("FIRECRAWL_API_KEY")),
        },
    }


@fastapi_app.get("/")
async def root():
    return {
        "message": "Commodity Sentiment Telegram Bot (Webhook Mode)",
        "health": "/health",
        "debug": "/debug",
        "set_webhook": "/set_webhook",
        "delete_webhook": "/delete_webhook",
    }
