"""FastAPI wrapper that runs the Telegram bot in a dedicated background thread.
Deploy to Render.com as a Web Service. Start command: uvicorn bot_server:app --host 0.0.0.0 --port $PORT
"""
import os
import sys
import asyncio
import threading
import logging
import traceback
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env if running locally
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

from fastapi import FastAPI
from bot import start_bot, _BOT_STATUS

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("bot_server")


_bot_task_thread = None


def _run_bot_in_thread():
    """Run async start_bot() in its own event loop inside a daemon thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info("Bot thread: event loop created, starting start_bot()...")
        loop.run_until_complete(start_bot())
    except Exception as e:
        logger.error(f"Bot thread CRASHED: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        loop.close()
        logger.info("Bot thread: event loop closed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_task_thread
    # Start the bot in a background daemon thread with its own event loop
    _bot_task_thread = threading.Thread(target=_run_bot_in_thread, daemon=True)
    _bot_task_thread.start()
    logger.info("Telegram bot background thread started")
    yield
    logger.info("FastAPI shutting down — bot thread will terminate (daemon)")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    alive = _bot_task_thread is not None and _bot_task_thread.is_alive()
    return {
        "status": "ok",
        "service": "commodity-sentiment-bot",
        "bot_thread_alive": alive,
        **_BOT_STATUS,
    }


@app.get("/debug")
async def debug():
    """Return live bot internal status."""
    alive = _bot_task_thread is not None and _bot_task_thread.is_alive()
    return {
        "status": "ok",
        "bot_thread_alive": alive,
        "bot_status": _BOT_STATUS,
        "env_check": {
            "token_set": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
            "groq_set": bool(os.environ.get("GROQ_API_KEY")),
            "firecrawl_set": bool(os.environ.get("FIRECRAWL_API_KEY")),
        },
    }


@app.get("/")
async def root():
    return {
        "message": "Commodity Sentiment Telegram Bot",
        "health": "/health",
        "debug": "/debug",
    }
