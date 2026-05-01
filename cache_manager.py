"""JSON disk cache — survives server restarts and page refreshes."""
import json
import os
from datetime import datetime, timezone, timedelta

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache")


def _ensure_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(commodity):
    _ensure_dir()
    return os.path.join(CACHE_DIR, f"{commodity}_analysis.json")


def load(commodity, ttl_seconds=300):
    """Load cached analysis data for commodity if within TTL.
    Returns (result, data, price_data, market_data) or (None, None, None, None).
    """
    path = _cache_path(commodity)
    if not os.path.exists(path):
        return None, None, None, None

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        cached_at = datetime.fromisoformat(payload.get("cached_at", "1970-01-01T00:00:00+00:00"))
        if datetime.now(timezone.utc) - cached_at > timedelta(seconds=ttl_seconds):
            return None, None, None, None  # stale
        return payload.get("result"), payload.get("data"), payload.get("price_data"), payload.get("market_data")
    except (json.JSONDecodeError, KeyError, ValueError):
        return None, None, None, None


def save(commodity, result, data, price_data, market_data):
    """Persist analysis data to disk."""
    path = _cache_path(commodity)
    try:
        payload = {
            "commodity": commodity,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
            "data": data,
            "price_data": price_data,
            "market_data": market_data,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    except (OSError, TypeError):
        pass
