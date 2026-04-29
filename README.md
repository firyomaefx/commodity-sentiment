---
title: Commodity Sentiment Dashboard
emoji: 📊
colorFrom: yellow
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Commodity Sentiment Intelligence

Real-time Gold (XAU/USD) and WTI Crude Oil sentiment analysis dashboard.

## Features
- VADER + Rule-Based sentiment engine
- Multi-commodity: Gold and WTI Crude Oil
- Telegram bot daily reports at 6:01 AM MYT
- Apple-style dark UI with glass-morphism
- Auto-refresh every 120s

## Telegram Commands
- `/start` — Subscribe
- `/report` — Gold report now
- `/report_wti` — WTI report now
- `/stop` — Unsubscribe
- `/status` — Check subscription