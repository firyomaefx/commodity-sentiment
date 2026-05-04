# Commodity Sentiment Intelligence

Real-time sentiment analysis for **Gold (XAU/USD)**, **WTI Crude Oil**, and **FCPO Crude Palm Oil**.

## Live URL

- **Dashboard:** https://commodity-sentiment.streamlit.app

## Architecture

| Component | Host | URL |
|-----------|------|-----|
| Dashboard | **Streamlit Cloud** | `https://commodity-sentiment.streamlit.app` |
| Source Code | **GitHub** | `github.com/firyomaefx/commodity-sentiment` |

## How It Works

- **Firecrawl API** searches and scrapes full article markdown for deep context
- **Groq AI (Llama 4 Scout)** classifies articles with 800-char body text for rich sentiment analysis
- **VADER NLP** scores all articles for sentiment polarity
- **Keyword-weighting** matches articles to commodity-specific topics (Fed, DXY, supply, weather, policy)
- **Auto-refresh** every 5 minutes with `@st.cache_data` + background prefetch

## Features

| Feature | Description |
|---------|-------------|
| 3 Commodities | Gold (XAU/USD), WTI Crude Oil, FCPO Crude Palm Oil |
| Real-time Price | Yahoo Finance (Gold/WTI), Investing.com (FCPO) |
| Deep Articles | Full markdown content via Firecrawl scraping |
| AI Sentiment | Groq Llama 4 Scout + VADER hybrid scoring |
| Macro Drivers | Fed, DXY, inflation, supply, geopolitical, weather, policy |
| Apple Dark UI | #0A0A0A background, #1C1C1E cards |
| Support Us | SenangPay donation link (RM1.99) |

## Deploy

### Streamlit Cloud
1. Push code to GitHub
2. Go to [streamlit.io/cloud](https://streamlit.io/cloud)
3. Deploy from GitHub → `dashboard.py`
4. Set secrets:
   - `GROQ_API_KEY`
   - `FIRECRAWL_API_KEY`

### Required Secrets

| Secret | Value |
|--------|-------|
| `GROQ_API_KEY` | Your Groq API key |
| `FIRECRAWL_API_KEY` | `fc-bcd6a6e5c0a9423a9790262b258f954f` |

## Prepared by
[@PedotTTRG](https://t.me/PedotTTRG)
