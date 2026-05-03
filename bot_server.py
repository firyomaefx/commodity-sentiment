"""FastAPI wrapper that runs the Telegram bot in a background thread.
Deploy to Render.com as a Web Service. Start command: uvicorn bot_server:app --host 0.0.0.0 --port $PORT"""
import os
import sys
import asyncio
import threading
import logging
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
from bot import start_bot

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("bot_server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the bot in a background asyncio task
    task = asyncio.create_task(start_bot())
    logger.info("Telegram bot background task started")
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "commodity-sentiment-bot"}


@app.get("/")
async def root():
    return {"message": "Commodity Sentiment Telegram Bot", "health": "/health"}
