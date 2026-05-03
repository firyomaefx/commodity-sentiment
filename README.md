# Commodity Sentiment Intelligence

Real-time sentiment analysis for **Gold (XAU/USD)**, **WTI Crude Oil**, and **FCPO Crude Palm Oil**.

## Architecture

| Component | Host | URL |
|-----------|------|-----|
| Interactive Dashboard | **Streamlit Cloud** | `commodity-sentiment.streamlit.app` |
| Telegram Bot | **Render.com** | (no public URL) |
| Source Code | **GitHub** | `github.com/firyomaefx/commodity-sentiment` |

## How It Works

- **Groq AI (Llama 4 Scout)** classifies top headlines for bias enrichment
- **VADER NLP** scores all articles for sentiment polarity
- **Keyword-weighting** matches articles to commodity-specific topics
- **Telegram Bot** delivers daily reports at **6:01 AM MYT**
- **On-demand** reports: `/report`, `/report_wti`, `/report_fcpo`

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Subscribe to daily reports |
| `/stop` | Unsubscribe |
| `/report` / `/report_wti` / `/report_fcpo` | Get report now |
| `/status` | Check subscription status |

## Deploy

### Dashboard — Streamlit Cloud
1. Push code to GitHub
2. Go to [streamlit.io/cloud](https://streamlit.io/cloud)
3. Deploy from GitHub → `dashboard.py`
4. Set secrets: `GROQ_API_KEY`

### Bot — Render.com
1. Create new **Web Service** from GitHub
2. Start command: `uvicorn bot_server:app --host 0.0.0.0 --port $PORT`
3. Build command: `pip install -r requirements-bot.txt`
4. Set env vars: `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `TELEGRAM_BOT_USERNAME=SentimentIntelligence26Bot`, `SENANGPAY_URL=https://app.senangpay.my/payment/177739832230`

## Prepared by
[@PedotTTRG](https://t.me/PedotTTRG)
