"""
Ranking Utilities - Time Decay & Relevance
===========================================
Implements intelligent ranking algorithms for search results.

Key Features:
- Time decay ranking (fresher content ranked higher)
- Hybrid scoring (semantic + recency)
- Engagement-aware boosting (likes/views)
"""

import time
from typing import List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def apply_time_decay(results: List[Dict[str, Any]], decay_factor: float = 0.1) -> List[Dict[str, Any]]:
    """
    Apply time decay ranking to search results.
    
    Formula: Final Score = (1 / (distance + 1e-6)) * (1 / (1 + (decay_factor * hours_elapsed)))
    
    Args:
        results: List of ChromaDB search results with metadata
        decay_factor: Controls how quickly scores decay (default: 0.1)
                     Higher = faster decay, Lower = slower decay
    
    Returns:
        Re-ranked results sorted by time-decayed relevance score
    """
    current_time = time.time()
    scored_results = []
    
    for result in results:
        try:
            # Extract metadata
            metadata = result.get('metadata', {})
            distance = result.get('distance', 1.0)
            
            # Get timestamp (fallback to current time if missing)
            timestamp = metadata.get('timestamp')
            if timestamp is None or timestamp == 0:
                # Try parsing published_at if timestamp is missing
                published_at = metadata.get('published_at', '')
                if published_at:
                    try:
                        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                        timestamp = int(dt.timestamp())
                    except Exception:
                        timestamp = int(current_time)
                else:
                    timestamp = int(current_time)
                    logger.warning(f"Missing timestamp for article: {metadata.get('title', 'Unknown')[:30]}")
            
            # Calculate time elapsed in hours
            hours_elapsed = (current_time - timestamp) / 3600.0
            
            # Prevent division by zero and negative times
            hours_elapsed = max(0, hours_elapsed)
            
            # Calculate relevance score (inverse of distance)
            # Lower distance = higher relevance
            relevance_score = 1.0 / (distance + 1e-6)
            
            # Apply time decay
            # Recent articles get higher scores
            time_decay_multiplier = 1.0 / (1.0 + (decay_factor * hours_elapsed))
            
            # Final score
            final_score = relevance_score * time_decay_multiplier
            
            # Add scores to result
            result['_relevance_score'] = round(relevance_score, 4)
            result['_time_decay'] = round(time_decay_multiplier, 4)
            result['_final_score'] = round(final_score, 4)
            result['_hours_old'] = round(hours_elapsed, 1)
            
            scored_results.append(result)
            
        except Exception as e:
            logger.error(f"Error calculating score for result: {e}")
            # Keep result but with default score
            result['_final_score'] = 0.0
            scored_results.append(result)
    
    # Sort by final score (descending)
    scored_results.sort(key=lambda x: x.get('_final_score', 0.0), reverse=True)
    
    logger.info(f"🔢 [Ranking] Applied time decay to {len(scored_results)} results (decay_factor={decay_factor})")
    
    return scored_results


def apply_engagement_boost(results: List[Dict[str, Any]], boost_factor: float = 0.05) -> List[Dict[str, Any]]:
    """
    Boost articles with high engagement (likes, views).
    
    Formula: Engagement Boost = 1 + (boost_factor * log(1 + likes + views))
    
    Args:
        results: List of ranked results
        boost_factor: Controls boost magnitude (default: 0.05)
    
    Returns:
        Re-ranked results with engagement boost applied
    """
    import math
    
    for result in results:
        try:
            metadata = result.get('metadata', {})
            
            likes = int(metadata.get('likes', 0))
            views = int(metadata.get('views', 0))
            
            # Logarithmic boost (prevents viral articles from dominating)
            engagement_score = likes + (views / 10)  # Views count less than likes
            engagement_boost = 1.0 + (boost_factor * math.log(1.0 + engagement_score))
            
            # Apply boost to existing score
            current_score = result.get('_final_score', 1.0)
            boosted_score = current_score * engagement_boost
            
            result['_engagement_boost'] = round(engagement_boost, 4)
            result['_final_score'] = round(boosted_score, 4)
            
        except Exception as e:
            logger.error(f"Error applying engagement boost: {e}")
    
    # Re-sort after boosting
    results.sort(key=lambda x: x.get('_final_score', 0.0), reverse=True)
    
    return results


def filter_by_recency(results: List[Dict[str, Any]], max_hours: int = 72) -> List[Dict[str, Any]]:
    """
    Filter out articles older than max_hours.
    
    Args:
        results: List of results
        max_hours: Maximum age in hours (default: 72 = 3 days)
    
    Returns:
        Filtered results
    """
    current_time = time.time()
    cutoff_time = current_time - (max_hours * 3600)
    
    filtered = []
    for result in results:
        metadata = result.get('metadata', {})
        timestamp = metadata.get('timestamp', 0)
        
        if timestamp >= cutoff_time:
            filtered.append(result)
    
    logger.info(f"📅 [Ranking] Filtered to {len(filtered)}/{len(results)} articles within {max_hours}h")
    
    return filtered
