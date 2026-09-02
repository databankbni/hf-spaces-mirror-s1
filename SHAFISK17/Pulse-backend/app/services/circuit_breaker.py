"""
Provider Circuit Breaker
========================

Prevents wasting time/bandwidth on rate-limited or failing API providers.

Features:
- Automatic failure detection
- Exponential backoff
- Circuit state: CLOSED → OPEN → HALF_OPEN → CLOSED
- Per-provider tracking
- Redis-backed persistence: circuit state survives server restarts
"""

import time
import asyncio
import logging
from typing import Dict, Optional
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, skip provider
    HALF_OPEN = "half_open"  # Testing if recovered


class ProviderCircuitBreaker:
    """
    Circuit breaker for news API providers

    Prevents repeatedly calling providers that are:
    - Rate limited (HTTP 429)
    - Down (HTTP 5xx)
    - Slow to respond

    Strategy:
    - After 3 failures in 5 minutes → OPEN circuit (skip for 1 hour)
    - After 1 hour → HALF_OPEN (allow 1 test request)
    - If test succeeds → CLOSED (normal operation)
    - If test fails → OPEN for another hour

    Redis Persistence (NEW):
    - When a circuit opens, we write the state to Redis with a 1-hour TTL.
    - On server boot, we read from Redis to restore any previously open circuits.
    - When a circuit closes, we delete the Redis key so it doesn't block a recovered provider.
    - If Redis is unavailable, we fall back gracefully to in-memory only.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        failure_window: int = 300,  # 5 minutes
        open_duration: int = 3600,  # 1 hour
        half_open_max_attempts: int = 1
    ):
        """
        Initialize circuit breaker

        Args:
            failure_threshold: Number of failures before opening circuit
            failure_window: Time window for counting failures (seconds)
            open_duration: How long to keep circuit open (seconds)
            half_open_max_attempts: Max test requests in HALF_OPEN state
        """
        self.failure_threshold = failure_threshold
        self.failure_window = failure_window
        self.open_duration = open_duration
        self.half_open_max_attempts = half_open_max_attempts

        # Provider state tracking
        self.states: Dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        # Fix 1: Track actual timestamps of failures so we can enforce the failure_window.
        self.failure_timestamps: Dict[str, list[float]] = defaultdict(list)
        self.circuit_open_time: Dict[str, float] = {}
        self.half_open_attempts: Dict[str, int] = defaultdict(int)

        # Known providers — used by the boot-time Redis restore.
        # IMPORTANT: Every provider registered in news_aggregator.py MUST be
        # listed here. If a provider is missing, a circuit that was OPEN before
        # a server restart will not be restored — the Space will hammer a broken
        # API on every restart until it fails 3 more times to re-open.
        #
        # Phases 1-2 (legacy):      gnews, newsapi, newsdata, google_rss, medium, official_cloud
        # Phases 3-11 (new modules): hacker_news, direct_rss, thenewsapi, inshorts,
        #                            saurav_static, worldnewsai, openrss, webz, wikinews
        self._known_providers = [
            # ── Legacy providers (Phases 1-2) ────────────────────────────────
            "gnews", "newsapi", "newsdata",
            "google_rss", "medium", "official_cloud",
            # ── New modular providers (Phases 3-11) ───────────────────────────
            "hacker_news", "direct_rss", "thenewsapi",
            "inshorts", "saurav_static", "worldnewsai",
            "openrss", "webz", "wikinews",
        ]

        logger.info("=" * 70)
        logger.info("⚡ [CIRCUIT BREAKER] Provider protection initialized")
        logger.info(f"   Failure threshold: {failure_threshold} failures")
        logger.info(f"   Failure window: {failure_window}s")
        logger.info(f"   Open duration: {open_duration}s ({open_duration//60} min)")
        logger.info(f"   Redis persistence: ENABLED")
        logger.info("=" * 70)

        # NOTE: We deliberately do NOT try to load Redis state here.
        #
        # When Python imports this file, FastAPI's event loop is NOT running yet.
        # Calling asyncio.get_running_loop() at import-time raises RuntimeError,
        # and we would silently swallow it — meaning the restore never happens.
        #
        # The correct approach: main.py calls startup_circuit_breaker() from the
        # FastAPI lifespan hook, AFTER the event loop is fully alive.
        # See the bottom of this file for that function.

    # ──────────────────────────────────────────────────────────────────────────
    # Redis Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _redis_key(self, provider: str) -> str:
        """Build the Redis key for a provider's circuit state."""
        return f"circuit:{provider}:state"

    async def _load_from_redis(self):
        """
        On server boot, check Redis for any circuit states that were open
        before the server restarted. If we find one, restore it in memory
        so we don't call a broken API immediately after booting.
        """
        try:
            from app.services.upstash_cache import get_upstash_cache
            cache = get_upstash_cache()

            for provider in self._known_providers:
                key = self._redis_key(provider)
                value = await cache._execute_command(["GET", key])

                if value == "open":
                    # The circuit was open before the restart — keep it open.
                    self.states[provider] = CircuitState.OPEN
                    # We don't know the exact open time, so we set it to "now".
                    # This means the 1-hour timeout will count from this boot,
                    # which is safe — the TTL on the Redis key is the real gate.
                    self.circuit_open_time[provider] = time.time()
                    logger.info(
                        "⚡ [CIRCUIT BREAKER] Restored OPEN state for %s from Redis (was open before restart).",
                        provider
                    )

        except Exception as e:
            # Redis is unavailable. That's fine — we start with all circuits CLOSED.
            logger.debug("[CIRCUIT BREAKER] Redis restore skipped (%s) — starting with clean state.", e)

    async def _persist_open_to_redis(self, provider: str):
        """
        Write 'circuit:{provider}:state = open' to Redis with a 1-hour TTL.
        Called whenever a circuit trips to OPEN.
        This is fire-and-forget: if Redis is unavailable, we log and move on.
        """
        try:
            from app.services.upstash_cache import get_upstash_cache
            cache = get_upstash_cache()
            key = self._redis_key(provider)
            # SET key "open" EX 3600 — expires in exactly 1 hour, same as open_duration.
            await cache._execute_command(["SET", key, "open", "EX", self.open_duration])
            logger.debug("[CIRCUIT BREAKER] Persisted OPEN state for %s to Redis.", provider)
        except Exception as e:
            logger.debug("[CIRCUIT BREAKER] Redis write failed for %s (%s) — in-memory state still protects us.", provider, e)

    async def _delete_from_redis(self, provider: str):
        """
        Delete 'circuit:{provider}:state' from Redis.
        Called whenever a circuit recovers to CLOSED, or on a full reset.
        """
        try:
            from app.services.upstash_cache import get_upstash_cache
            cache = get_upstash_cache()
            key = self._redis_key(provider)
            await cache._execute_command(["DEL", key])
            logger.debug("[CIRCUIT BREAKER] Cleared Redis state for %s.", provider)
        except Exception as e:
            logger.debug("[CIRCUIT BREAKER] Redis delete failed for %s (%s) — not a blocker.", provider, e)

    # ──────────────────────────────────────────────────────────────────────────
    # Core Circuit Breaker Logic
    # ──────────────────────────────────────────────────────────────────────────

    def should_skip(self, provider: str) -> bool:
        """
        Check if provider should be skipped

        Args:
            provider: Provider name (e.g., "gnews", "newsapi")

        Returns:
            True if provider should be skipped, False otherwise
        """
        current_state = self.states[provider]
        current_time = time.time()

        # CLOSED = normal operation, don't skip
        if current_state == CircuitState.CLOSED:
            return False

        # OPEN = provider failing, check if should move to HALF_OPEN
        if current_state == CircuitState.OPEN:
            open_time = self.circuit_open_time.get(provider, 0)

            # Check if open duration has elapsed
            if current_time - open_time >= self.open_duration:
                # Move to HALF_OPEN (allow test request)
                self.states[provider] = CircuitState.HALF_OPEN
                self.half_open_attempts[provider] = 0
                logger.info(f"⚡ Circuit HALF_OPEN for {provider} (testing recovery)")
                return False  # Allow test request
            else:
                # Still in open period, skip
                remaining = int(self.open_duration - (current_time - open_time))
                logger.debug(f"⚡ Circuit OPEN for {provider} ({remaining}s remaining)")
                return True

        # HALF_OPEN = testing recovery
        if current_state == CircuitState.HALF_OPEN:
            # Allow limited test requests
            if self.half_open_attempts[provider] < self.half_open_max_attempts:
                # FIX (Bug A): Increment the counter so we don't let infinite
                # test requests through. The old code checked this counter but
                # never actually increased it, causing an endless loop.
                self.half_open_attempts[provider] += 1
                return False  # Allow test
            else:
                # FIX (Bug B — self-rescue):
                # The test request went through but no success or failure was
                # recorded. This happens when the API returned HTTP 200 with
                # 0 articles — a quiet day with no news, not a broken key.
                #
                # If we just return True here and do nothing, the circuit stays
                # frozen in HALF_OPEN forever because there is no other path out.
                #
                # Solution: push it back to OPEN with a fresh 1-hour timer.
                # The cycle will be:
                #   OPEN (1 hour) → HALF_OPEN (1 test) → inconclusive → OPEN again
                # Eventually an actual article response will trigger record_success()
                # and the circuit will properly close. No permanent freeze.
                logger.warning(
                    "⚡ [%s] HALF_OPEN test inconclusive (API reached but returned no articles). "
                    "Resetting to OPEN for another %d minutes.",
                    provider, self.open_duration // 60
                )
                self.states[provider] = CircuitState.OPEN
                self.circuit_open_time[provider] = time.time()

                # Persist the new OPEN state to Redis so it survives a restart.
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._persist_open_to_redis(provider))
                except RuntimeError:
                    pass

                return True


        return False

    def record_success(self, provider: str):
        """
        Record successful request

        Args:
            provider: Provider name
        """
        current_state = self.states[provider]

        # Reset failure tracking
        self.failure_timestamps[provider].clear()

        # Close circuit if it was open/half-open
        if current_state != CircuitState.CLOSED:
            self.states[provider] = CircuitState.CLOSED
            logger.info(f"✅ Circuit CLOSED for {provider} (recovered)")

            # Clean up the Redis key so this provider isn't blocked after the next restart.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._delete_from_redis(provider))
            except RuntimeError:
                pass

    def record_failure(
        self,
        provider: str,
        error_type: str = "unknown",
        status_code: Optional[int] = None
    ):
        """
        Record failed request

        Args:
            provider: Provider name
            error_type: Type of error ("rate_limit", "timeout", "server_error")
            status_code: HTTP status code (if applicable)
        """
        current_state = self.states[provider]
        current_time = time.time()

        # Fix 1: Enforce the failure_window by pruning old failures.
        # Remove any timestamps older than (current_time - self.failure_window)
        cutoff_time = current_time - self.failure_window
        self.failure_timestamps[provider] = [
            ts for ts in self.failure_timestamps[provider] if ts >= cutoff_time
        ]

        # Append this new failure
        self.failure_timestamps[provider].append(current_time)
        current_failure_count = len(self.failure_timestamps[provider])

        # Log failure with details
        status_str = f" (HTTP {status_code})" if status_code else ""
        logger.warning(
            f"⚠️  {provider} failure #{current_failure_count} (in last {self.failure_window}s): "
            f"{error_type}{status_str}"
        )

        # Check if should open circuit
        if current_state == CircuitState.CLOSED:
            # Check failure window
            if current_failure_count >= self.failure_threshold:
                # Open circuit in memory first (instant protection)
                self.states[provider] = CircuitState.OPEN
                self.circuit_open_time[provider] = current_time

                logger.warning(
                    f"🔴 Circuit OPEN for {provider} "
                    f"({current_failure_count} failures in {self.failure_window}s) "
                    f"- skipping for {self.open_duration//60} minutes"
                )

                # Persist to Redis so the state survives a server restart.
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._persist_open_to_redis(provider))
                except RuntimeError:
                    pass

        # If in HALF_OPEN and fails, go back to OPEN
        elif current_state == CircuitState.HALF_OPEN:
            self.states[provider] = CircuitState.OPEN
            self.circuit_open_time[provider] = current_time

            logger.warning(
                f"🔴 Circuit back to OPEN for {provider} "
                f"(test failed) - skipping for {self.open_duration//60} minutes"
            )

            # Persist the re-opened state to Redis too.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_open_to_redis(provider))
            except RuntimeError:
                pass

    def reset(self, provider: Optional[str] = None):
        """
        Reset circuit breaker

        Args:
            provider: Provider to reset (None = reset all)
        """
        if provider:
            # Reset specific provider in memory
            self.states[provider] = CircuitState.CLOSED
            self.failure_timestamps[provider].clear()
            self.half_open_attempts[provider] = 0
            logger.info(f"🔄 Circuit reset for {provider}")

            # Also remove the Redis key for this provider
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._delete_from_redis(provider))
            except RuntimeError:
                pass
        else:
            # Reset all providers in memory
            self.states.clear()
            self.failure_timestamps.clear()
            self.circuit_open_time.clear()
            self.half_open_attempts.clear()
            logger.info("🔄 All circuits reset")

            # Remove all Redis keys for known providers
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._reset_all_redis_keys())
            except RuntimeError:
                pass

    async def _reset_all_redis_keys(self):
        """Delete all circuit state keys from Redis. Called by reset()."""
        for provider in self._known_providers:
            await self._delete_from_redis(provider)
        logger.info("[CIRCUIT BREAKER] All Redis circuit keys cleared.")

    def get_stats(self) -> dict:
        """Get circuit breaker statistics"""
        total_open = sum(1 for s in self.states.values() if s == CircuitState.OPEN)
        total_half_open = sum(1 for s in self.states.values() if s == CircuitState.HALF_OPEN)
        total_closed = sum(1 for s in self.states.values() if s == CircuitState.CLOSED)

        # Provider details
        provider_details = {}
        for provider, state in self.states.items():
            timestamps = self.failure_timestamps.get(provider, [])
            last_fail = timestamps[-1] if timestamps else None
            provider_details[provider] = {
                'state': state.value,
                'failures': len(timestamps),
                'last_failure': last_fail
            }

        return {
            'total_open': total_open,
            'total_half_open': total_half_open,
            'total_closed': total_closed,
            'providers': provider_details
        }

    def print_stats(self):
        """Print circuit breaker statistics"""
        stats = self.get_stats()

        logger.info("")
        logger.info("=" * 70)
        logger.info("⚡ [CIRCUIT BREAKER] Provider Status")
        logger.info("=" * 70)
        logger.info(f"   🔹 Open Circuits: {stats['total_open']}")
        logger.info(f"   🔹 Half-Open Circuits: {stats['total_half_open']}")
        logger.info(f"   🔹 Closed Circuits: {stats['total_closed']}")
        logger.info("")

        for provider, details in stats['providers'].items():
            state_emoji = {
                'closed': '✅',
                'open': '🔴',
                'half_open': '🟡'
            }.get(details['state'], '❓')

            logger.info(
                f"   {state_emoji} {provider.upper()}: "
                f"{details['state'].upper()} "
                f"({details['failures']} failures)"
            )

        logger.info("=" * 70)
        logger.info("")


# Global singleton instance
_circuit_breaker: Optional[ProviderCircuitBreaker] = None


def get_circuit_breaker() -> ProviderCircuitBreaker:
    """
    Get or create global circuit breaker instance.

    This is a lazy singleton — it creates the breaker the first time it's
    called and returns the same object on every call after that.
    It does NOT load Redis state here. That happens in startup_circuit_breaker().
    """
    global _circuit_breaker

    if _circuit_breaker is None:
        _circuit_breaker = ProviderCircuitBreaker(
            failure_threshold=3,  # 3 failures...
            failure_window=300,   # ...within 5 minutes = circuit OPEN
            open_duration=3600,   # skip provider for 1 hour
            half_open_max_attempts=1  # allow 1 test request after the hour
        )

    return _circuit_breaker


async def startup_circuit_breaker():
    """
    Load saved circuit states from Redis on server startup.

    This function is called by FastAPI's lifespan hook in main.py,
    AFTER the event loop is fully running. Calling it here (instead of
    inside __init__) is the correct way to run async work at boot time.

    If Redis is offline, we log a warning and continue — the breaker
    will just start with all circuits CLOSED, which is safe.
    """
    logger.info("[CIRCUIT BREAKER] Running startup Redis restore...")
    try:
        breaker = get_circuit_breaker()
        await breaker._load_from_redis()
        logger.info("[CIRCUIT BREAKER] Startup Redis restore complete.")
    except Exception as e:
        # Redis is offline or unreachable — not a crash, just a warning.
        # The circuit breaker will work fine in memory-only mode.
        logger.warning(
            "[CIRCUIT BREAKER] Startup Redis restore failed (%s). "
            "Starting with all circuits CLOSED — this is safe.", e
        )
