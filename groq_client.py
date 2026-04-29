import sys
import os
import logging
import json

logger = logging.getLogger(__name__)

GROQ_AVAILABLE = False
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError as e:
    logger.warning(f"groq package not installed: {e}")


class GroqAnalyzer:
    MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
    MAX_ARTICLES = 20
    BATCH_SIZE = 10

    def __init__(self, api_key=None):
        self.available = False
        self.client = None
        if not GROQ_AVAILABLE:
            return
        key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not key:
            return
        try:
            self.client = Groq(api_key=key)
            self.available = True
            logger.info(f"Groq client initialized (model={self.MODEL})")
        except Exception as e:
            logger.error(f"Groq client init failed: {e}")

    def _call(self, system_prompt, user_prompt, temperature=0.3, max_tokens=300):
        try:
            resp = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_completion_tokens=max_tokens,
                timeout=20,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Groq API call failed: {e}")
            return None

    def batch_classify_articles(self, articles, commodity):
        if not self.available or not articles:
            return articles

        top_articles = articles[:self.MAX_ARTICLES]
        label_map = {
            "gold": "gold (XAU/USD)", "wti": "WTI crude oil", "fcpo": "crude palm oil (FCPO)"
        }
        comm_label = label_map.get(commodity, commodity)

        for i in range(0, len(top_articles), self.BATCH_SIZE):
            batch = top_articles[i:i + self.BATCH_SIZE]
            batch_texts = []
            for idx, a in enumerate(batch):
                batch_texts.append(f"[{idx+1}] {a['title'][:120]}\n{a.get('summary', '')[:300]}")

            prompt = f"""Analyze these commodity news articles about {comm_label}.
For each article [1]-[{len(batch)}], return a JSON array with objects:
{{"id":<number>,"sentiment":"bullish"|"neutral"|"bearish","score":-100 to 100,"categories":["cat1","cat2"],"summary":"<25 word summary>","confidence":0-100}}

Categories (pick 1-4 per article): fed,inflation,rates,employment,geopolitical,dxy,usd,supply,demand,weather,policy,competing,fear,risk_on,risk_off

Articles:
""" + "\n\n".join(batch_texts)

            result = self._call(
                f"You are a {comm_label} commodities market analyst. Return ONLY valid JSON, no explanation.",
                prompt,
                temperature=0.2,
                max_tokens=800,
            )
            if not result:
                continue

            try:
                cleaned = result.strip().removeprefix("```json").removesuffix("```").strip()
                parsed = json.loads(cleaned)
                for item in parsed:
                    idx = item.get("id", 0) - 1
                    if 0 <= idx < len(batch):
                        a = batch[idx]
                        a["groq_sentiment_score"] = item.get("score", 0)
                        a["groq_sentiment_label"] = item.get("sentiment", "neutral")
                        a["groq_categories"] = item.get("categories", [])
                        a["groq_summary"] = item.get("summary", a.get("summary", "")[:200])
                        a["groq_confidence"] = item.get("confidence", 50)
                        a["groq_enhanced"] = True
                logger.info(f"Groq classified {len(parsed)} articles for {commodity}")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error(f"Groq parse error: {e}")

        return articles

    def generate_justification(self, bias, sentiment_score, dxy_bias, geo_intensity,
                                macro_bias, contrarian, supply_score, commodity, top_headlines=""):
        if not self.available:
            return None

        label_map = {
            "gold": "gold (XAU/USD)", "wti": "WTI crude oil", "fcpo": "crude palm oil (FCPO)"
        }
        prompt = f"""Write a 3-4 sentence professional market analysis for {label_map.get(commodity, commodity)}.
Final Bias: {bias} | Sentiment Score: {sentiment_score} | DXY: {dxy_bias} | Geo Intensity: {geo_intensity}
Macro: {macro_bias} | Contrarian: {contrarian} | Supply: {supply_score}
Key headlines: {top_headlines[:500]}

Be concise, factual, no fluff. Explain the primary drivers."""
        result = self._call(
            "You are a senior commodities market analyst. Write concise professional analysis.",
            prompt,
            temperature=0.4,
            max_tokens=250,
        )
        return result

    def get_badge_html(self):
        return '<span style="background:rgba(100,200,255,0.15);color:#64C8FF;font-size:10px;font-weight:600;padding:2px 8px;border-radius:980px;margin-left:8px;vertical-align:middle;">AI ENHANCED</span>' if self.available else ""
