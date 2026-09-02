"""
Anti-Manipulation & Fraud Detection
====================================
Detects and mitigates spam, bot attacks, and gaming attempts.

Techniques:
1. Duplicate detection (Jaccard similarity)
2. Extremity bias detection (text patterns)
3. Bot pattern detection (temporal clustering)
4. Anomaly detection (Isolation Forest)
5. Submission pattern analysis
"""

import numpy as np
from typing import Dict, List, Tuple, Set
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib
import logging

logger = logging.getLogger(__name__)

class DuplicateDetector:
    """Detects duplicate or near-duplicate submissions."""
    
    @staticmethod
    def jaccard_similarity(text1: str, text2: str) -> float:
        """
        Compute Jaccard similarity between two texts.
        
        Jaccard(A, B) = |A ∩ B| / |A ∪ B|
        
        Uses word-level tokens.
        
        Args:
            text1, text2: Input texts
        
        Returns:
            Similarity in [0, 1]
        """
        tokens1 = set(text1.lower().split())
        tokens2 = set(text2.lower().split())
        
        if not tokens1 and not tokens2:
            return 1.0
        
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        
        return float(intersection / union) if union > 0 else 0.0
    
    @staticmethod
    def comment_hash(text: str) -> str:
        """Get hash of comment for deduplication."""
        return hashlib.sha256(text.lower().encode()).hexdigest()
    
    def find_duplicates(
        self,
        comments: List[str],
        threshold: float = 0.85
    ) -> List[Tuple[int, int, float]]:
        """
        Find duplicate or near-duplicate comments.
        
        Args:
            comments: List of comment texts
            threshold: Jaccard similarity threshold (default: 0.85)
        
        Returns:
            List of (idx1, idx2, similarity) tuples where similarity >= threshold
        """
        duplicates = []
        
        for i in range(len(comments)):
            for j in range(i + 1, len(comments)):
                sim = self.jaccard_similarity(comments[i], comments[j])
                if sim >= threshold:
                    duplicates.append((i, j, sim))
        
        return duplicates


class ExtremityBiasDetector:
    """Detects suspicious text patterns (all caps, excessive punctuation, etc.)."""
    
    @staticmethod
    def uppercase_ratio(text: str) -> float:
        """Compute ratio of uppercase characters."""
        if not text:
            return 0.0
        uppercase = sum(1 for c in text if c.isupper())
        return float(uppercase / len(text))
    
    @staticmethod
    def punctuation_density(text: str, punctuation: str = "!?~#") -> float:
        """Compute ratio of intensive punctuation marks."""
        if not text:
            return 0.0
        punct_count = sum(1 for c in text if c in punctuation)
        return float(punct_count / len(text))
    
    @staticmethod
    def emoji_count(text: str) -> int:
        """Count emoji-like characters (simple heuristic)."""
        emoji_ranges = [
            (0x1F300, 0x1F9FF),  # Emojis
            (0x2600, 0x26FF),    # Misc symbols
        ]
        count = 0
        for char in text:
            char_code = ord(char)
            for start, end in emoji_ranges:
                if start <= char_code <= end:
                    count += 1
        return count
    
    def get_extremity_score(self, text: str) -> float:
        """
        Compute extremity score in [0, 1].
        
        Higher score = more suspicious/extreme text pattern.
        
        Returns:
            Score in [0, 1]
        """
        upper_ratio = self.uppercase_ratio(text)
        punct_density = self.punctuation_density(text)
        emoji_count = self.emoji_count(text)
        
        # Weighted combination
        extremity = (
            0.4 * min(upper_ratio, 1.0) +  # Excessive caps
            0.4 * min(punct_density * 5, 1.0) +  # Excessive punctuation
            0.2 * min(emoji_count / 10, 1.0)  # Emojis
        )
        
        return float(np.clip(extremity, 0.0, 1.0))
    
    def is_suspicious(self, text: str, threshold: float = 0.6) -> Tuple[bool, float]:
        """
        Check if text is suspiciously extreme.
        
        Args:
            text: Input text
            threshold: Extremity score threshold (default: 0.6)
        
        Returns:
            (is_suspicious, extremity_score)
        """
        score = self.get_extremity_score(text)
        return score >= threshold, score


class TemporalClusteringDetector:
    """Detects coordinated submission spikes (bot attacks)."""
    
    def __init__(self, spike_threshold: float = 3.0):
        """
        Initialize detector.
        
        Args:
            spike_threshold: Ratio of current_rate to historical_avg (default: 3x)
        """
        self.spike_threshold = spike_threshold
    
    def detect_spike(
        self,
        recent_count: int,
        time_window_minutes: int,
        historical_daily_avg: float = 1.0
    ) -> Tuple[bool, float]:
        """
        Detect if submission rate is unusually high.
        
        Args:
            recent_count: Submissions in recent window
            time_window_minutes: Duration of window
            historical_daily_avg: Average daily submissions (baseline)
        
        Returns:
            (is_spike, spike_ratio)
        """
        # Convert recent_count to daily rate
        daily_rate = recent_count * (1440 / time_window_minutes)
        
        # Compute spike ratio
        spike_ratio = daily_rate / max(historical_daily_avg, 0.1)
        
        is_spike = spike_ratio >= self.spike_threshold
        
        return is_spike, spike_ratio


class AnomalyDetector:
    """Detects sentiment anomalies using Isolation Forest."""
    
    def __init__(self, contamination: float = 0.1):
        """
        Initialize anomaly detector.
        
        Args:
            contamination: Expected fraction of anomalies (default: 0.1 = 10%)
        """
        self.contamination = contamination
        self.forest = None
    
    def fit_on_embeddings(self, embeddings: np.ndarray):
        """
        Fit Isolation Forest on embedding vectors.
        
        Args:
            embeddings: Array of shape (n_samples, embedding_dim)
        """
        try:
            from sklearn.ensemble import IsolationForest
            
            self.forest = IsolationForest(
                contamination=self.contamination,
                random_state=42
            )
            self.forest.fit(embeddings)
            logger.info(f"Fitted Isolation Forest on {len(embeddings)} embeddings")
        
        except ImportError:
            logger.warning("scikit-learn not available; anomaly detection disabled")
    
    def predict_anomalies(self, embeddings: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Predict anomaly labels and scores.
        
        Args:
            embeddings: Array of shape (n_samples, embedding_dim)
        
        Returns:
            (labels, scores)
            - labels: -1 for anomaly, 1 for normal
            - scores: anomaly score (lower = more anomalous)
        """
        if self.forest is None:
            logger.warning("Forest not fitted; returning all normal")
            return np.ones(len(embeddings)), np.zeros(len(embeddings))
        
        labels = self.forest.predict(embeddings)
        scores = self.forest.score_samples(embeddings)
        
        return labels, scores


class AntiManipulationEngine:
    """Main anti-manipulation coordinator."""
    
    def __init__(self, max_submissions_per_day_per_ip: int = 10):
        """
        Initialize engine.
        
        Args:
            max_submissions_per_day_per_ip: Threshold for bot-like behavior
        """
        self.duplicate_detector = DuplicateDetector()
        self.extremity_detector = ExtremityBiasDetector()
        self.temporal_detector = TemporalClusteringDetector()
        self.anomaly_detector = AnomalyDetector()
        
        self.max_submissions_per_day = max_submissions_per_day_per_ip
        
        # Track submissions
        self.submissions_by_ip = defaultdict(list)
        self.submission_history = []
    
    def check_submission(
        self,
        text: str,
        ip_hash: str,
        recent_submissions: List[str] = None,
        sentiment_confidence: float = 0.95
    ) -> Dict:
        """
        Check a submission for suspicious patterns.
        
        Args:
            text: Submission text
            ip_hash: Anonymized IP hash
            recent_submissions: Recent comments for this company (for duplicate check)
            sentiment_confidence: Confidence from sentiment model
        
        Returns:
            Dictionary with flags and recommendations:
            {
                'is_suspicious': bool,
                'flags': [list of detected issues],
                'weight_factor': float (1.0 = normal, <1.0 = downweight),
                'recommendation': 'approve' | 'review' | 'reject',
                'details': {rule-specific diagnostics}
            }
        """
        flags = []
        weight_factor = 1.0
        extremity_score = None
        duplicate_similarity = None
        ip_count_today = None

        low_conf_threshold = 0.60
        extremity_threshold = 0.60
        duplicate_threshold = 0.85
        
        # Flag 1: Low sentiment confidence
        if sentiment_confidence < low_conf_threshold:
            flags.append('low_confidence')
        
        # Flag 2: Extremity bias
        is_extreme, extremity_score = self.extremity_detector.is_suspicious(
            text,
            threshold=extremity_threshold
        )
        if is_extreme:
            flags.append('extremity_bias')
            weight_factor *= 0.5  # Half-weight
        
        # Flag 3: Duplicate detection
        if recent_submissions:
            best_sim = 0.0
            for past_comment in recent_submissions:
                sim = self.duplicate_detector.jaccard_similarity(text, past_comment)
                if sim > best_sim:
                    best_sim = sim
                if sim > duplicate_threshold:
                    flags.append('duplicate')
                    weight_factor *= 0.3  # Heavily downweight
                    break
            if best_sim > 0.0:
                duplicate_similarity = best_sim
        
        # Flag 4: Temporal clustering (many submissions from same IP)
        if ip_hash:
            now = datetime.now()
            recent_ips = [
                (ts, sender_ip) for ts, sender_ip in self.submission_history
                if (now - ts).total_seconds() < 86400  # Last 24 hours
            ]
            
            ip_count_today = sum(1 for _, sender_ip in recent_ips if sender_ip == ip_hash)
            
            if ip_count_today > self.max_submissions_per_day:
                flags.append('temporal_clustering')
                weight_factor *= 0.5
            
            # Track this submission
            self.submission_history.append((now, ip_hash))
        
        # Recommendation logic
        if len(flags) >= 2:
            recommendation = 'review'  # Multiple flags → human review
        elif 'duplicate' in flags:
            recommendation = 'review'
        elif 'temporal_clustering' in flags:
            recommendation = 'review'
        else:
            recommendation = 'approve'
        
        return {
            'is_suspicious': len(flags) > 0,
            'flags': flags,
            'weight_factor': float(weight_factor),
            'recommendation': recommendation,
            'extremity_score': extremity_score if 'extremity_bias' in flags else None,
            'details': {
                'low_confidence': {
                    'triggered': 'low_confidence' in flags,
                    'confidence': float(sentiment_confidence),
                    'threshold': float(low_conf_threshold)
                },
                'extremity_bias': {
                    'triggered': 'extremity_bias' in flags,
                    'score': float(extremity_score) if extremity_score is not None else None,
                    'threshold': float(extremity_threshold)
                },
                'duplicate': {
                    'triggered': 'duplicate' in flags,
                    'max_similarity': float(duplicate_similarity) if duplicate_similarity is not None else None,
                    'threshold': float(duplicate_threshold)
                },
                'temporal_clustering': {
                    'triggered': 'temporal_clustering' in flags,
                    'count_last_24h': int(ip_count_today) if ip_count_today is not None else None,
                    'max_per_day': int(self.max_submissions_per_day)
                }
            }
        }
    
    def downweight_anomalies(
        self,
        sentiment_signals: List[float],
        anomaly_scores: np.ndarray,
        percentile_threshold: float = 20.0
    ) -> Tuple[List[float], List[float]]:
        """
        Downweight anomalous sentiment signals.
        
        Args:
            sentiment_signals: Sentiment signals for comments
            anomaly_scores: Anomaly scores (lower = more anomalous)
            percentile_threshold: Threshold for anomaly classification (default: 20th percentile)
        
        Returns:
            (downweighted_signals, weight_factors)
        """
        if len(anomaly_scores) == 0:
            return sentiment_signals, [1.0] * len(sentiment_signals)
        
        # Compute percentile threshold
        threshold = np.percentile(anomaly_scores, percentile_threshold)
        
        downweighted = []
        weights = []
        
        for signal, score in zip(sentiment_signals, anomaly_scores):
            if score < threshold:
                # Anomalous: downweight
                weight = 0.5
            else:
                # Normal
                weight = 1.0
            
            downweighted.append(signal * weight)
            weights.append(weight)
        
        return downweighted, weights


def demo_anti_manipulation():
    """Demo anti-manipulation detection."""
    
    print("=" * 80)
    print("ANTI-MANIPULATION DETECTION DEMO")
    print("=" * 80)
    
    engine = AntiManipulationEngine()
    
    # Test 1: Duplicate detection
    print("\n[1] DUPLICATE DETECTION")
    print("─" * 80)
    comment1 = "I love the team and culture!"
    comment2 = "I love the team and culture!"
    comment3 = "The team is amazing, great culture"
    
    sim_1_2 = engine.duplicate_detector.jaccard_similarity(comment1, comment2)
    sim_1_3 = engine.duplicate_detector.jaccard_similarity(comment1, comment3)
    
    print(f"  Comment 1: '{comment1}'")
    print(f"  Comment 2: '{comment2}'")
    print(f"  Similarity: {sim_1_2:.3f} {'[DUPLICATE]' if sim_1_2 > 0.85 else '[OK]'}")
    print(f"\n  Comment 3: '{comment3}'")
    print(f"  Similarity (1 vs 3): {sim_1_3:.3f} {'[DUPLICATE]' if sim_1_3 > 0.85 else '[DIFFERENT]'}")
    
    # Test 2: Extremity bias
    print("\n[2] EXTREMITY BIAS DETECTION")
    print("─" * 80)
    extremity_samples = [
        "Great place to work",
        "BEST COMPANY EVER!!!!!!",
        "Terrible place NO GOOD!!!!"
    ]
    
    for sample in extremity_samples:
        is_extreme, score = engine.extremity_detector.is_suspicious(sample)
        print(f"  '{sample}'")
        print(f"    Extremity Score: {score:.3f} {'[SUSPICIOUS]' if is_extreme else '[OK]'}")
    
    # Test 3: Temporal clustering
    print("\n[3] TEMPORAL CLUSTERING DETECTION")
    print("─" * 80)
    
    detector = TemporalClusteringDetector(spike_threshold=3.0)
    
    # Scenario 1: Normal rate
    is_spike_1, ratio_1 = detector.detect_spike(
        recent_count=2,
        time_window_minutes=60,
        historical_daily_avg=2.0
    )
    print(f"  2 submissions in 1 hour (normal avg: 2/day)")
    print(f"    Daily equivalent rate: 48/day")
    print(f"    Historical avg: 2/day")
    print(f"    Spike? {is_spike_1} (ratio: {ratio_1:.1f}x)")
    
    # Scenario 2: Spike
    is_spike_2, ratio_2 = detector.detect_spike(
        recent_count=50,
        time_window_minutes=60,
        historical_daily_avg=2.0
    )
    print(f"\n  50 submissions in 1 hour (normal avg: 2/day)")
    print(f"    Daily equivalent rate: 1200/day")
    print(f"    Historical avg: 2/day")
    print(f"    Spike? {is_spike_2} (ratio: {ratio_2:.1f}x) {'[BOT ATTACK]' if is_spike_2 else ''}")
    
    # Test 4: Submission checking
    print("\n[4] FULL SUBMISSION CHECK")
    print("─" * 80)
    
    test_submissions = [
        ("Great culture and supportive team", "normal"),
        ("AMAZING BEST EVER!!!!", "extreme"),
        ("I hate this place", "negative"),
    ]
    
    for text, label in test_submissions:
        result = engine.check_submission(
            text=text,
            ip_hash="ip_hash_123",
            sentiment_confidence=0.85
        )
        print(f"\n  [{label}] '{text}'")
        print(f"    Result: {result['recommendation'].upper()}")
        print(f"    Flags: {result['flags'] if result['flags'] else 'None'}")
        print(f"    Weight Factor: {result['weight_factor']:.2f}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    demo_anti_manipulation()
