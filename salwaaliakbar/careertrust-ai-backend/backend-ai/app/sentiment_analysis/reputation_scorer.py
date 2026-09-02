"""
Reputation Scoring Algorithm
============================
Aggregates sentiment signals into stable, fair company reputation scores
with Bayesian smoothing and anti-manipulation safeguards.

Mathematical foundation:
- Temporal weighting (recency bias)
- Bayesian smoothing (low-sample bias mitigation)
- Confidence intervals (uncertainty quantification)
- Scale conversion (1-5 stars or 0-100%)
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class ReputationScorer:
    """
    Computes company reputation scores from sentiment signals.
    
    Key mechanisms:
    1. Temporal weighting: Recent comments weighted more (90-day half-life)
    2. Bayesian smoothing: Regress toward global mean for small samples
    3. Confidence intervals: Quantify score uncertainty
    4. Aspect weighting: Optional per-aspect score computation
    """
    
    def __init__(
        self,
        temporal_half_life_days: int = 90,
        bayesian_alpha: int = 20,
        global_mean: float = 0.0,
        min_calibrated_confidence: float = 0.60
    ):
        """
        Initialize reputation scorer.
        
        Args:
            temporal_half_life_days: Comments half their weight after N days (default: 90)
            bayesian_alpha: Pseudo-count for Bayesian prior (default: 20)
            global_mean: Prior reputation mean (default: 0, neutral)
            min_calibrated_confidence: Min sentiment model confidence to include (default: 0.60)
        """
        self.temporal_half_life = temporal_half_life_days
        self.bayesian_alpha = bayesian_alpha
        self.global_mean = global_mean
        self.min_calibrated_confidence = min_calibrated_confidence
    
    @staticmethod
    def temporal_weight(days_ago: int, half_life: int = 90) -> float:
        """
        Compute temporal weight for a comment based on age.
        
        Formula: weight = exp(-days / half_life)
        After half_life days, weight = 0.5
        
        Args:
            days_ago: Age of comment in days
            half_life: Half-life decay (days)
        
        Returns:
            Weight in [0, 1]
        """
        if days_ago < 0:
            days_ago = 0
        
        # Use exponential decay: weight = exp(-ln(2) * days / half_life)
        weight = np.exp(-np.log(2) * days_ago / half_life)
        return float(weight)
    
    @staticmethod
    def bayesian_smooth(
        raw_score: float,
        sample_size: int,
        prior_mean: float = 0.0,
        alpha: int = 20
    ) -> float:
        """
        Apply Bayesian smoothing to regress toward prior.
        
        Formula: smooth_score = (n * raw_score + alpha * prior_mean) / (n + alpha)
        
        Intuition:
        - Large n: score ≈ raw_score (empirical dominates)
        - Small n: score ≈ prior_mean (prior dominates)
        - At n = alpha: score is 50-50 mix of empirical and prior
        
        Args:
            raw_score: Empirical mean sentiment signal
            sample_size: Number of comments
            prior_mean: Prior mean (default: 0, neutral)
            alpha: Effective sample size of prior
        
        Returns:
            Smoothed score
        """
        smoothed = (sample_size * raw_score + alpha * prior_mean) / (sample_size + alpha)
        return float(smoothed)
    
    @staticmethod
    def confidence_interval(
        sentiments: List[float],
        confidence_level: float = 0.95
    ) -> Tuple[float, float]:
        """
        Compute confidence interval for score.
        
        Uses standard error approach:
        CI = mean ± z * SE
        where SE = std / sqrt(n)
        
        Args:
            sentiments: List of sentiment signals
            confidence_level: 0.95 for 95% CI (z ≈ 1.96)
        
        Returns:
            (lower_bound, upper_bound)
        """
        if len(sentiments) < 2:
            return (-1.0, 1.0)  # Full range for single sample
        
        mean = np.mean(sentiments)
        std = np.std(sentiments)
        se = std / np.sqrt(len(sentiments))
        
        # Z-score for 95% CI
        z = 1.96 if confidence_level == 0.95 else 1.64
        
        margin = z * se
        return (float(mean - margin), float(mean + margin))
    
    def compute_reputation_score(
        self,
        sentiments: List[Dict],
        submission_timestamps: List[datetime] = None,
        current_time: datetime = None,
        scale: str = '5star'  # or '100percent'
    ) -> Dict:
        """
        Compute reputation score from sentiment signals.
        
        Args:
            sentiments: List of sentiment dictionaries with keys:
                       - 'signal': S_c (sentiment signal in [-1, 1])
                       - 'confidence': model confidence [0, 1]
            submission_timestamps: Timestamps when comments were submitted
            current_time: Reference time for age calculation (default: now)
            scale: '5star' for [1, 5] or '100percent' for [0, 100]
        
        Returns:
            Dictionary with:
            - 'score': Reputation score in requested scale
            - 'ci_lower', 'ci_upper': Confidence interval
            - 'sample_size': Number of included comments
            - 'temporal_weight': Total temporal weight applied
            - 'sentiment_signal': Underlying normalized signal [-1, 1]
        """
        if not sentiments:
            logger.warning("No sentiments provided; returning neutral score")
            return {
                'score': 3.0 if scale == '5star' else 50.0,
                'ci_lower': 1.0 if scale == '5star' else 0.0,
                'ci_upper': 5.0 if scale == '5star' else 100.0,
                'sample_size': 0,
                'temporal_weight': 0.0,
                'sentiment_signal': 0.0,
                'warning': 'No sentiments provided'
            }
        
        if current_time is None:
            current_time = datetime.now()
        
        # Filter by confidence
        calibrated_sentiments = []
        valid_timestamps = []
        
        for i, sentiment_dict in enumerate(sentiments):
            if sentiment_dict.get('confidence', 0.0) >= self.min_calibrated_confidence:
                calibrated_sentiments.append(sentiment_dict['signal'])
                if submission_timestamps:
                    valid_timestamps.append(submission_timestamps[i])
        
        if not calibrated_sentiments:
            logger.warning(f"No sentiments passed calibration (min confidence: {self.min_calibrated_confidence})")
            return {
                'score': 3.0 if scale == '5star' else 50.0,
                'ci_lower': 1.0 if scale == '5star' else 0.0,
                'ci_upper': 5.0 if scale == '5star' else 100.0,
                'sample_size': 0,
                'temporal_weight': 0.0,
                'sentiment_signal': 0.0,
                'warning': 'No calibrated sentiments'
            }
        
        # Compute temporal weights
        weights = []
        total_weight = 0.0
        
        for i, timestamp in enumerate(valid_timestamps if valid_timestamps else [None] * len(calibrated_sentiments)):
            if timestamp:
                age_days = (current_time - timestamp).days
                w = self.temporal_weight(age_days, self.temporal_half_life)
            else:
                w = 1.0  # No timestamp info; use unit weight
            
            weights.append(w)
            total_weight += w
        
        # Weighted mean sentiment
        raw_score = np.average(calibrated_sentiments, weights=weights)
        
        # Bayesian smoothing
        smoothed_score = self.bayesian_smooth(
            raw_score,
            sample_size=len(calibrated_sentiments),
            prior_mean=self.global_mean,
            alpha=self.bayesian_alpha
        )
        
        # Clamp to [-1, 1]
        smoothed_score = np.clip(smoothed_score, -1.0, 1.0)
        
        # Confidence interval
        ci_lower, ci_upper = self.confidence_interval(calibrated_sentiments)
        
        # Convert to requested scale
        if scale == '5star':
            reputation_score = 3.0 + 2.0 * smoothed_score
            ci_lower_scaled = 3.0 + 2.0 * ci_lower
            ci_upper_scaled = 3.0 + 2.0 * ci_upper
        else:  # '100percent'
            reputation_score = 50.0 + 50.0 * smoothed_score
            ci_lower_scaled = 50.0 + 50.0 * ci_lower
            ci_upper_scaled = 50.0 + 50.0 * ci_upper
        
        return {
            'score': float(reputation_score),
            'ci_lower': float(ci_lower_scaled),
            'ci_upper': float(ci_upper_scaled),
            'sample_size': len(calibrated_sentiments),
            'temporal_weight': float(total_weight),
            'sentiment_signal': float(smoothed_score),
            'raw_sentiment_signal': float(raw_score),
            'scale': scale
        }
    
    def compute_aspect_scores(
        self,
        aspect_sentiments: List[Dict[str, float]],
        submission_timestamps: List[datetime] = None,
        current_time: datetime = None,
        scale: str = '5star'
    ) -> Dict[str, float]:
        """
        Compute per-aspect reputation scores.
        
        Args:
            aspect_sentiments: List of dicts mapping aspect -> sentiment signal
            submission_timestamps: Timestamps
            current_time: Reference time
            scale: '5star' or '100percent'
        
        Returns:
            Dictionary mapping aspect -> reputation score
        """
        # Collect sentiments per aspect
        aspect_dicts = {}
        
        for aspect_dict in aspect_sentiments:
            for aspect, signal in aspect_dict.items():
                if aspect not in aspect_dicts:
                    aspect_dicts[aspect] = []
                aspect_dicts[aspect].append({'signal': signal, 'confidence': 0.95})  # High confidence for aspect
        
        # Score each aspect
        aspect_scores = {}
        for aspect, sentiments in aspect_dicts.items():
            result = self.compute_reputation_score(
                sentiments,
                submission_timestamps=submission_timestamps,
                current_time=current_time,
                scale=scale
            )
            aspect_scores[aspect] = result['score']
        
        return aspect_scores
    
    def score_stability_check(
        self,
        previous_score: float,
        new_score: float,
        max_allowed_change: float = 0.3
    ) -> Tuple[bool, float]:
        """
        Check if new score is suspiciously different from previous.
        
        Args:
            previous_score: Score before new comment (1-5 scale)
            new_score: Score after new comment
            max_allowed_change: Max allowed change per comment (default: 0.3)
        
        Returns:
            (is_stable, delta)
            - is_stable: True if change is reasonable
            - delta: Actual change
        """
        delta = abs(new_score - previous_score)
        is_stable = delta <= max_allowed_change
        return is_stable, delta


def demo_reputation_scoring():
    """Demo reputation scoring algorithm."""
    
    scorer = ReputationScorer(
        temporal_half_life_days=90,
        bayesian_alpha=20
    )
    
    print("=" * 80)
    print("REPUTATION SCORING DEMO")
    print("=" * 80)
    
    # Sample sentiments from comments
    sample_sentiments = [
        {'signal': +0.91, 'confidence': 0.93},  # Amazing culture
        {'signal': -0.80, 'confidence': 0.85},  # Pay is low
        {'signal': +0.05, 'confidence': 0.75},  # Decent place
        {'signal': -0.84, 'confidence': 0.88},  # Manager was awful
        {'signal': +0.64, 'confidence': 0.72},  # Interview smooth
    ]
    
    # Sample timestamps (varying ages)
    now = datetime.now()
    timestamps = [
        now - timedelta(days=120),  # 120 days ago (0.5x weight)
        now - timedelta(days=30),   # 30 days ago
        now - timedelta(days=5),    # 5 days ago
        now,                        # Just now (1.0x weight)
        now - timedelta(days=60),   # 60 days ago
    ]
    
    print("\nInput sentiments:")
    for i, (sent, ts) in enumerate(zip(sample_sentiments, timestamps)):
        age = (now - ts).days
        print(f"  [{i}] Signal={sent['signal']:+.2f}, Conf={sent['confidence']:.2f}, Age={age}d")
    
    # Compute score
    result = scorer.compute_reputation_score(
        sample_sentiments,
        submission_timestamps=timestamps,
        current_time=now,
        scale='5star'
    )
    
    print(f"\n{'─' * 80}")
    print("5-STAR SCALE:")
    print(f"{'─' * 80}")
    print(f"  Reputation Score: {result['score']:.1f} / 5.0")
    print(f"  95% CI: [{result['ci_lower']:.1f}, {result['ci_upper']:.1f}]")
    print(f"  Sample Size: {result['sample_size']}")
    print(f"  Temporal Weight: {result['temporal_weight']:.2f}")
    print(f"  Underlying Signal: {result['sentiment_signal']:+.3f}")
    
    # Also compute 100% scale
    result_100 = scorer.compute_reputation_score(
        sample_sentiments,
        submission_timestamps=timestamps,
        current_time=now,
        scale='100percent'
    )
    
    print(f"\n{'─' * 80}")
    print("100% SCALE (Glassdoor-style):")
    print(f"{'─' * 80}")
    print(f"  Reputation Score: {result_100['score']:.0f}%")
    print(f"  95% CI: [{result_100['ci_lower']:.0f}%, {result_100['ci_upper']:.0f}%]")
    
    # Bayesian smoothing effect
    print(f"\n{'─' * 80}")
    print("BAYESIAN SMOOTHING EFFECT:")
    print(f"{'─' * 80}")
    print(f"  Raw Sentiment Signal: {result['raw_sentiment_signal']:+.3f}")
    print(f"  Smoothed Signal: {result['sentiment_signal']:+.3f}")
    print(f"  Prior Mean: {scorer.global_mean:.1f}")
    print(f"  Bayesian Alpha: {scorer.bayesian_alpha}")
    print(f"  → Interpretation: With {result['sample_size']} comments, smoothing moves")
    print(f"                    score toward neutral (prior) by factor proportional to alpha.")
    
    # Temporal weighting
    print(f"\n{'─' * 80}")
    print("TEMPORAL WEIGHTING:")
    print(f"{'─' * 80}")
    for i, ts in enumerate(timestamps):
        age = (now - ts).days
        w = ReputationScorer.temporal_weight(age, half_life=90)
        print(f"  Comment {i}: Age={age:3d}d, Weight={w:.3f}")
    
    # Confidence interval explanation
    print(f"\n{'─' * 80}")
    print("CONFIDENCE INTERVAL INTERPRETATION:")
    print(f"{'─' * 80}")
    print(f"  Score: {result['score']:.1f} with 95% CI [{result['ci_lower']:.1f}, {result['ci_upper']:.1f}]")
    print(f"  → 95% chance true reputation is in this range")
    print(f"  → wider CI = less certain (small sample or inconsistent reviews)")
    print(f"  → narrow CI = more certain (large sample or consistent reviews)")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    demo_reputation_scoring()
