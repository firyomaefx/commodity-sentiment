from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import COMMODITY_CONFIGS
import re

_TOKEN_RE = re.compile(r"\b[%\w]+\b", re.UNICODE)


class SentimentAnalyzer:
    def __init__(self, commodity="gold", groq_client=None):
        self.commodity = commodity
        self.config = COMMODITY_CONFIGS.get(commodity, COMMODITY_CONFIGS["gold"])
        self.groq = groq_client
        self.vader = SentimentIntensityAnalyzer()
        self.keywords = self.config["keywords"]
        self.bullish_phrases = self.config["bullish_phrases"]
        self.bearish_phrases = self.config["bearish_phrases"]
        self.fear_keywords = self.config["fear_keywords"]
        self.fed_dovish = self.config["fed_dovish"]
        self.fed_hawkish = self.config["fed_hawkish"]

        _kw_exact = {"usd", "dxy", "pce", "ppi", "nfp", "adp", "opec", "cpi", "wti", "eia"}
        self._keyword_matchers = {}
        for category, kws in self.keywords.items():
            matchers = []
            for kw in kws:
                kl = kw.lower()
                if kl in _kw_exact or (len(kl) <= 5 and kl.isalpha()):
                    matchers.append(("word", kl))
                else:
                    matchers.append(("substring", kl))
            self._keyword_matchers[category] = matchers

    def _keyword_match_score(self, text):
        text_lower = text.lower()
        tokens = set(_TOKEN_RE.findall(text_lower))
        score = 0
        matched_categories = set()
        for category, matchers in self._keyword_matchers.items():
            for mtype, pattern in matchers:
                if mtype == "word":
                    if pattern in tokens:
                        score += 1
                        matched_categories.add(category)
                        break
                else:
                    if pattern in text_lower:
                        score += 1
                        matched_categories.add(category)
                        break
        return score, matched_categories

    def _phrase_sentiment(self, text):
        text_lower = text.lower()
        score = 0
        for phrase in self.bullish_phrases:
            if phrase in text_lower:
                score += 1
        for phrase in self.bearish_phrases:
            if phrase in text_lower:
                score -= 1
        return score

    def _vader_sentiment(self, text):
        scores = self.vader.polarity_scores(text)
        return scores["compound"]

    def _count_category_mentions(self, articles):
        counts = {cat: 0 for cat in self.keywords}
        for article in articles:
            for cat in article.get("categories", []):
                if cat in counts:
                    counts[cat] += 1
        return counts

    def compute_article_vader(self, text):
        return self._vader_sentiment(text)

    def analyze_geopolitical(self, articles):
        fear_articles = []
        for a in articles:
            text_lower = a["text"].lower()
            if any(kw in text_lower for kw in self.fear_keywords):
                fear_articles.append(a)

        if not fear_articles:
            return "No significant geopolitical flashpoints detected.", "Low"

        fear_topics = set()
        for a in fear_articles:
            text_lower = a["text"].lower()
            for kw in self.fear_keywords:
                if kw in text_lower:
                    fear_topics.add(kw)

        if len(fear_articles) >= 5 or len(fear_topics) >= 5:
            intensity = "High"
        elif len(fear_articles) >= 2:
            intensity = "Moderate"
        else:
            intensity = "Low"

        topics_str = ", ".join(list(fear_topics)[:5])
        summary = f"Geopolitical tension detected across {len(fear_articles)} articles. Key themes: {topics_str}. Market fear factor is {intensity.lower()}."
        return summary, intensity

    def analyze_macro_events(self, articles):
        dovish_count = 0
        hawkish_count = 0
        fed_articles = []

        fed_terms = ["fed", "fomc", "powell", "federal reserve", "interest rate", "rate cut", "rate hike", "rate decision", "monetary policy"]
        for a in articles:
            text_lower = a["text"].lower()
            if any(t in text_lower for t in fed_terms):
                fed_articles.append(a)
                if any(p in text_lower for p in self.fed_dovish):
                    dovish_count += 1
                if any(p in text_lower for p in self.fed_hawkish):
                    hawkish_count += 1

        if not fed_articles:
            return "No significant Fed or macro event headlines detected in current feed.", "Neutral"

        if dovish_count > hawkish_count:
            bias = "Dovish"
            if self.commodity == "wti":
                summary = f"Fed sentiment leans dovish ({dovish_count} dovish vs {hawkish_count} hawkish signals). Lower rates weaken USD, supporting oil prices via stronger demand outlook."
            elif self.commodity == "fcpo":
                summary = f"Fed sentiment leans dovish ({dovish_count} dovish vs {hawkish_count} hawkish signals). Weaker USD supports palm oil prices and emerging market demand."
            else:
                summary = f"Fed sentiment leans dovish ({dovish_count} dovish vs {hawkish_count} hawkish signals). Rate cut expectations supporting gold as real yields face downward pressure."
        elif hawkish_count > dovish_count:
            bias = "Hawkish"
            if self.commodity == "wti":
                summary = f"Fed sentiment leans hawkish ({hawkish_count} hawkish vs {dovish_count} dovish signals). Higher rates strengthen USD and weigh on oil demand outlook."
            elif self.commodity == "fcpo":
                summary = f"Fed sentiment leans hawkish ({hawkish_count} hawkish vs {dovish_count} dovish signals). Stronger USD pressures palm oil prices and emerging market demand."
            else:
                summary = f"Fed sentiment leans hawkish ({hawkish_count} hawkish vs {dovish_count} dovish signals). Rate hold/hike expectations pressuring gold via stronger dollar and higher yield outlook."
        else:
            bias = "Mixed"
            summary = f"Mixed Fed signals ({dovish_count} dovish, {hawkish_count} hawkish). Market uncertain on rate path."

        return summary, bias

    def compute_sentiment_score(self, articles):
        if not articles:
            return 0, "Neutral"

        total_score = 0
        total_weight = 0

        for a in articles:
            if a.get("groq_enhanced"):
                gs = a.get("groq_sentiment_score", 0)
                combined = gs * 1.5
                weight = a.get("keyword_score", 1) * 1.5
            else:
                vader_s = self._vader_sentiment(a["text"])
                phrase_s = self._phrase_sentiment(a["text"])
                combined = vader_s * 40 + phrase_s * 15
                weight = a.get("keyword_score", 1)

            total_score += combined * weight
            total_weight += weight

        if total_weight == 0:
            return 0, "Neutral"

        raw = total_score / total_weight
        score = max(-100, min(100, raw))

        if score > 75:
            label = "Extremely Bullish"
        elif score > 25:
            label = "Bullish"
        elif score > -25:
            label = "Neutral"
        elif score > -75:
            label = "Bearish"
        else:
            label = "Extremely Bearish"

        return round(score, 1), label

    def compute_contrarian_signal(self, score):
        if score > 75 or score < -75:
            return "YES"
        return "NO"

    def determine_market_mood(self, geo_intensity, macro_bias, sentiment_score):
        risk_off_signals = 0
        risk_on_signals = 0

        if self.commodity == "fcpo":
            if sentiment_score > 30:
                risk_on_signals += 2
            elif sentiment_score < -30:
                risk_off_signals += 2
            if geo_intensity in ["High", "Moderate"]:
                risk_off_signals += 1
        else:
            if geo_intensity in ["High", "Moderate"]:
                risk_off_signals += 2
            if macro_bias == "Dovish":
                risk_off_signals += 2
            if macro_bias == "Hawkish":
                risk_on_signals += 2
            if sentiment_score > 30:
                risk_off_signals += 1
            elif sentiment_score < -30:
                risk_on_signals += 1

        if risk_off_signals > risk_on_signals:
            return "Risk-Off"
        if risk_on_signals > risk_off_signals:
            return "Risk-On"
        return "Risk-Off"

    def analyze_dxy(self, articles):
        dxy_score = 0

        for a in articles:
            text_lower = a["text"].lower()
            has_dollar_ref = "dxy" in text_lower or "dollar index" in text_lower or "us dollar" in text_lower or "dollar" in text_lower
            if not has_dollar_ref:
                continue
            if any(p in text_lower for p in ["strong", "rallies", "rises", "firm", "gains", "strengthens"]):
                dxy_score += 1
            if any(p in text_lower for p in ["weak", "falls", "drops", "slides", "softens", "declines"]):
                dxy_score -= 1

            if any(p in text_lower for p in self.fed_dovish):
                dxy_score -= 1
            if any(p in text_lower for p in self.fed_hawkish):
                dxy_score += 1

        if dxy_score > 2:
            return "Bullish"
        if dxy_score < -2:
            return "Bearish"
        return "Neutral"

    def _analyze_supply(self, articles):
        if self.commodity not in ("wti", "fcpo"):
            return 0
        supply_score = 0
        if self.commodity == "wti":
            supply_bullish = ["opec cut", "production cut", "output cut", "inventory draw", "supply disruption", "strategic reserves", "pipeline attack"]
            supply_bearish = ["opec increase", "production increase", "output hike", "inventory build", "demand destruction", "shale boom", "oversupply"]
        else:
            supply_bullish = ["stocks decline", "lower stockpiles", "production drop", "lower output", "DMO tightening", "export quota reduced", "biodiesel mandate", "El Niño"]
            supply_bearish = ["stockpiles surge", "inventory build", "higher stockpiles", "production surge", "bumper crop", "DMO relaxed", "favorable weather", "oversupply"]
        for a in articles:
            text_lower = a["text"].lower()
            if any(p in text_lower for p in supply_bullish):
                supply_score += 1
            if any(p in text_lower for p in supply_bearish):
                supply_score -= 1
        return supply_score

    def _analyze_myr(self, articles):
        if self.commodity != "fcpo":
            return "Neutral"
        myr_score = 0
        for a in articles:
            text_lower = a["text"].lower()
            has_myr = "myr" in text_lower or "ringgit" in text_lower or "malaysian" in text_lower
            if not has_myr:
                continue
            if any(p in text_lower for p in ["weak", "falls", "drops", "slides", "declines", "depreciates"]):
                myr_score -= 1
            if any(p in text_lower for p in ["strong", "rallies", "rises", "firms", "gains", "appreciates"]):
                myr_score += 1
        if myr_score < -1:
            return "Bearish"
        if myr_score > 1:
            return "Bullish"
        return "Neutral"

    def generate_final_bias(self, sentiment_score, dxy_bias, geo_intensity, macro_bias, contrarian_signal, supply_score=0, myr_bias="Neutral", articles=None):
        score = 0

        if sentiment_score > 50:
            score += 2
        elif sentiment_score > 20:
            score += 1
        if sentiment_score < -50:
            score -= 2
        elif sentiment_score < -20:
            score -= 1

        if self.commodity == "fcpo":
            if myr_bias == "Bearish":
                score += 2
            elif myr_bias == "Bullish":
                score -= 2
        else:
            if dxy_bias == "Bearish":
                score += 2
            elif dxy_bias == "Bullish":
                score -= 2

        if self.commodity == "fcpo":
            if geo_intensity == "High":
                score += 1
            elif geo_intensity == "Moderate":
                score += 1
        else:
            if geo_intensity == "High":
                score += 2
            elif geo_intensity == "Moderate":
                score += 1

        if self.commodity == "fcpo":
            pass
        else:
            if macro_bias == "Dovish":
                score += 2
            elif macro_bias == "Hawkish":
                score -= 2

        if self.commodity in ("wti", "fcpo"):
            if self.commodity == "fcpo":
                score += supply_score * 2
            else:
                score += supply_score

        if self.commodity != "fcpo":
            if contrarian_signal == "YES":
                if sentiment_score > 75:
                    score -= 3
                elif sentiment_score < -75:
                    score += 3

        if score >= 4:
            bias = "Strong Buy"
        elif score >= 2:
            bias = "Buy"
        elif score <= -4:
            bias = "Strong Sell"
        elif score <= -2:
            bias = "Sell"
        else:
            bias = "Neutral"

        drivers = []
        if geo_intensity in ["High", "Moderate"]:
            if self.commodity == "wti":
                drivers.append("geopolitical supply risk")
            elif self.commodity == "fcpo":
                drivers.append("trade disruption risk")
            else:
                drivers.append("geopolitical fear premium")
        if self.commodity != "fcpo":
            if macro_bias == "Dovish":
                drivers.append("dovish Fed expectations")
            elif macro_bias == "Hawkish":
                if self.commodity == "wti":
                    drivers.append("hawkish Fed demand pressure")
                else:
                    drivers.append("hawkish Fed pressure")
        else:
            if macro_bias == "Dovish":
                drivers.append("easier global financial conditions")
            elif macro_bias == "Hawkish":
                drivers.append("tighter global financial conditions")
        if self.commodity == "fcpo":
            if myr_bias == "Bearish":
                drivers.append("weak Ringgit support")
            elif myr_bias == "Bullish":
                drivers.append("strong Ringgit headwind")
        else:
            if dxy_bias == "Bearish":
                drivers.append("weak dollar support")
            elif dxy_bias == "Bullish":
                drivers.append("strong dollar headwind")
        if self.commodity == "wti" and supply_score > 0:
            drivers.append("supply tightness")
        elif self.commodity == "wti" and supply_score < 0:
            drivers.append("supply excess")
        if self.commodity == "fcpo" and supply_score > 0:
            drivers.append("palm oil supply tightness")
        elif self.commodity == "fcpo" and supply_score < 0:
            drivers.append("palm oil oversupply")
        if self.commodity != "fcpo" and contrarian_signal == "YES":
            drivers.append("contrarian reversal risk")

        if self.groq and self.groq.available:
            top_headlines = ", ".join(a["title"][:60] for a in articles[:5]) if articles else ""
            groq_just = self.groq.generate_justification(
                bias, sentiment_score, dxy_bias, geo_intensity, macro_bias,
                contrarian_signal, supply_score, self.commodity, top_headlines
            )
            if groq_just:
                justification = groq_just
            else:
                justification = f"{', '.join(drivers[:3])}. Sentiment {sentiment_score}, contrarian={contrarian_signal}."
        else:
            justification = f"{', '.join(drivers[:3])}. Sentiment {sentiment_score}, contrarian={contrarian_signal}."
        return bias, justification

    def run_full_analysis(self, articles):
        geo_summary, geo_intensity = self.analyze_geopolitical(articles)
        macro_summary, macro_bias = self.analyze_macro_events(articles)
        sentiment_score, sentiment_label = self.compute_sentiment_score(articles)
        contrarian = self.compute_contrarian_signal(sentiment_score)
        market_mood = self.determine_market_mood(geo_intensity, macro_bias, sentiment_score)
        dxy_bias = self.analyze_dxy(articles)
        myr_bias = self._analyze_myr(articles)
        supply_score = self._analyze_supply(articles)
        final_bias, justification = self.generate_final_bias(
            sentiment_score, dxy_bias, geo_intensity, macro_bias, contrarian, supply_score, myr_bias, articles
        )

        for a in articles:
            a["vader_score"] = self._vader_sentiment(a["text"])

        result = {
            "analysis_1_macro": {
                "geopolitical_summary": geo_summary,
                "macro_event_impact": macro_summary,
                "overall_market_mood": market_mood,
            },
            "analysis_2_sentiment": {
                f"{self.config.get('score_key', self.commodity)}_sentiment_score": sentiment_score,
                "sentiment_label": sentiment_label,
                "contrarian_signal": contrarian,
            },
            "analysis_3_dxy": {
                "dxy_directional_bias": dxy_bias,
            },
            "final_synthesis": {
                f"final_{self.config.get('score_key', self.commodity)}_bias": final_bias,
                "justification": justification,
            },
            "meta": {
                "articles_analyzed": len(articles),
                "category_counts": self._count_category_mentions(articles),
                "geo_intensity": geo_intensity,
                "macro_bias": macro_bias,
                "market_mood": market_mood,
                "supply_score": supply_score,
                "myr_bias": myr_bias,
                "commodity": self.commodity,
            }
        }
        return result


if __name__ == "__main__":
    import json
    from collector import DataCollector
    for comm in ["gold", "wti", "fcpo"]:
        c = DataCollector(commodity=comm)
        data = c.collect_all()
        a = SentimentAnalyzer(commodity=comm)
        result = a.run_full_analysis(data["articles"])
        sk = a.config.get("score_key", comm)
        print(f"\n=== {comm.upper()} ===")
        print(json.dumps({
            "bias": result["final_synthesis"][f"final_{sk}_bias"],
            "score": result["analysis_2_sentiment"][f"{sk}_sentiment_score"],
            "mood": result["analysis_1_macro"]["overall_market_mood"],
            "dxy": result["analysis_3_dxy"]["dxy_directional_bias"],
            "supply": result["meta"]["supply_score"],
            "articles": result["meta"]["articles_analyzed"],
        }, indent=2))