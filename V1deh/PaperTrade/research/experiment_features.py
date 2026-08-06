#!/usr/bin/env python3
"""Backtest-only experimental context builders (reusable for future production integration)."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import yfinance as yf

try:
    from social_sentiment import fetch_social_sentiment
except Exception:
    fetch_social_sentiment = None


_BULL_WORDS = {
    "bullish", "strong", "beat", "growth", "upgrade", "momentum", "rally", "buy",
    "outperform", "positive", "profit", "surge",
}
_BEAR_WORDS = {
    "bearish", "weak", "miss", "downgrade", "risk", "loss", "fall", "sell",
    "underperform", "negative", "crash", "slump",
}


@dataclass
class ExperimentalConfig:
    enable_alt_sentiment: bool = False
    enable_fundamentals: bool = False


class ExperimentContextBuilder:
    """Thread-safe cache for optional backtest context enrichment."""

    def __init__(self, config: ExperimentalConfig):
        self.config = config
        self._lock = threading.Lock()
        self._social_cache: dict[str, dict] = {}
        self._fund_cache: dict[str, dict] = {}

    def build_news_bundle(self, ticker: str, company: str) -> dict:
        """Return a news dict compatible with ai_forecast.get_ai_forecast()."""
        label = "NEUTRAL"
        score = 0
        summary_parts: list[str] = []
        headlines: list[str] = []

        if self.config.enable_alt_sentiment:
            social = self._get_social_sentiment(ticker, company)
            if social:
                score += int(social.get("score", 0))
                summary_parts.append(social.get("summary", ""))
                if social.get("headline"):
                    headlines.append(social["headline"])

        if self.config.enable_fundamentals:
            fund = self._get_fundamentals(ticker)
            if fund:
                score += int(fund.get("score", 0))
                summary_parts.append(fund.get("summary", ""))
                if fund.get("headline"):
                    headlines.append(fund["headline"])

        if score > 5:
            label = "BULLISH"
        elif score < -5:
            label = "BEARISH"

        return {
            "label": label,
            "score": score,
            "summary": " | ".join([p for p in summary_parts if p])[:280],
            "key_headline": headlines[0] if headlines else "",
            "headlines": headlines[:5],
            "source": "backtest-experimental",
        }

    def _get_social_sentiment(self, ticker: str, company: str) -> dict | None:
        if fetch_social_sentiment is None:
            return None
        with self._lock:
            cached = self._social_cache.get(ticker)
        if cached is not None:
            return cached

        try:
            text = fetch_social_sentiment(ticker, company) or ""
            text_l = text.lower()
            bull = sum(1 for w in _BULL_WORDS if w in text_l)
            bear = sum(1 for w in _BEAR_WORDS if w in text_l)
            raw_score = max(-12, min(12, (bull - bear) * 2))
            first_line = (text.splitlines()[0].strip() if text else "social sentiment unavailable")
            result = {
                "score": raw_score,
                "summary": f"Social sentiment score {raw_score:+d}",
                "headline": first_line[:140],
            }
        except Exception:
            result = None

        with self._lock:
            self._social_cache[ticker] = result
        return result

    def _get_fundamentals(self, ticker: str) -> dict | None:
        with self._lock:
            cached = self._fund_cache.get(ticker)
        if cached is not None:
            return cached

        try:
            info = yf.Ticker(ticker).info or {}
            pe = _to_float(info.get("trailingPE"))
            de = _to_float(info.get("debtToEquity"))
            rev_growth = _to_float(info.get("revenueGrowth"))
            fcf = _to_float(info.get("freeCashflow"))

            score = 0
            checks: list[str] = []

            if pe is not None:
                if 0 < pe < 35:
                    score += 2
                    checks.append(f"PE={pe:.1f}")
                elif pe >= 50:
                    score -= 2
                    checks.append(f"PE={pe:.1f}")
            if de is not None:
                if de < 80:
                    score += 2
                    checks.append(f"D/E={de:.1f}")
                elif de > 180:
                    score -= 2
                    checks.append(f"D/E={de:.1f}")
            if rev_growth is not None:
                if rev_growth > 0.08:
                    score += 3
                    checks.append(f"RevGrowth={rev_growth*100:.1f}%")
                elif rev_growth < -0.05:
                    score -= 3
                    checks.append(f"RevGrowth={rev_growth*100:.1f}%")
            if fcf is not None:
                if fcf > 0:
                    score += 2
                    checks.append("FCF positive")
                else:
                    score -= 2
                    checks.append("FCF negative")

            score = max(-12, min(12, score))
            result = {
                "score": score,
                "summary": f"Fundamentals score {score:+d} ({', '.join(checks[:3])})",
                "headline": "Fundamental screen from yfinance",
            }
        except Exception:
            result = None

        with self._lock:
            self._fund_cache[ticker] = result
        return result


def _to_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None
