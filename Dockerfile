FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860 8502

HEALTHCHECK CMD curl --fail http://localhost:7860/_stcore/health || exit 1

CMD ["sh", "-c", "python bot.py & streamlit run dashboard.py --server.port=7860 --server.address=0.0.0.0"]