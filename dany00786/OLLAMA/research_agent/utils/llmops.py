"""LLMOps utilities for agent monitoring, loop prevention, and error recovery."""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from functools import wraps
import time

logger = logging.getLogger(__name__)


class AgentMonitor:
    """Monitors agent execution to prevent infinite loops and manage timeouts."""

    def __init__(
        self,
        max_iterations: int = 10,
        timeout_seconds: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds or int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
        self.max_retries = max_retries or int(os.getenv("MAX_RETRIES", "3"))
        self._iteration_count = 0
        self._start_time = None
        self._retry_count = 0

    def reset(self):
        """Reset monitor state for new execution."""
        self._iteration_count = 0
        self._start_time = time.time()
        self._retry_count = 0

    def check_iteration_limit(self):
        """Check if iteration limit has been exceeded."""
        self._iteration_count += 1
        if self._iteration_count > self.max_iterations:
            error_msg = f"Agent exceeded maximum iterations ({self.max_iterations})"
            logger.error(error_msg)
            raise LoopDetectionError(error_msg)

    def check_timeout(self):
        """Check if execution has exceeded timeout."""
        if self._start_time is None:
            self._start_time = time.time()

        elapsed = time.time() - self._start_time
        if elapsed > self.timeout_seconds:
            error_msg = f"Agent execution exceeded timeout ({self.timeout_seconds}s)"
            logger.error(error_msg)
            raise TimeoutError(error_msg)

    def check_retry_limit(self):
        """Check if retry limit has been exceeded."""
        if self._retry_count >= self.max_retries:
            error_msg = f"Agent exceeded maximum retries ({self.max_retries})"
            logger.error(error_msg)
            raise RetryExhaustedError(error_msg)

    def increment_retry(self):
        """Increment retry counter."""
        self._retry_count += 1

    def get_status(self) -> Dict[str, Any]:
        """Get current monitor status."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        return {
            "iterations": self._iteration_count,
            "retries": self._retry_count,
            "elapsed_seconds": elapsed,
            "max_iterations": self.max_iterations,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
        }


class LoopDetectionError(Exception):
    """Raised when an infinite loop is detected."""
    pass


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""
    pass


def with_llmops_monitor(agent_name: str = "agent"):
    """
    Decorator that adds LLMOps monitoring to agent functions.
    
    Prevents infinite loops, manages timeouts, and handles retries.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            monitor = AgentMonitor()
            monitor.reset()

            # Log agent start
            logger.info(f"[{agent_name}] Starting execution: {func.__name__}")
            start_time = time.time()

            try:
                # Check limits before execution
                monitor.check_iteration_limit()
                monitor.check_timeout()

                # Execute function
                result = func(*args, **kwargs)

                # Log completion
                elapsed = time.time() - start_time
                logger.info(f"[{agent_name}] Completed {func.__name__} in {elapsed:.2f}s")

                # Add monitor status to result if it's a dict
                if isinstance(result, dict):
                    result["monitor_status"] = monitor.get_status()

                return result

            except LoopDetectionError as e:
                logger.critical(f"[{agent_name}] Loop detected in {func.__name__}: {e}")
                return {
                    "status": "failed",
                    "error": "loop_detected",
                    "message": str(e),
                    "monitor_status": monitor.get_status(),
                }

            except TimeoutError as e:
                logger.critical(f"[{agent_name}] Timeout in {func.__name__}: {e}")
                return {
                    "status": "failed",
                    "error": "timeout",
                    "message": str(e),
                    "monitor_status": monitor.get_status(),
                }

            except RetryExhaustedError as e:
                logger.critical(f"[{agent_name}] Retries exhausted in {func.__name__}: {e}")
                return {
                    "status": "failed",
                    "error": "retries_exhausted",
                    "message": str(e),
                    "monitor_status": monitor.get_status(),
                }

            except Exception as e:
                logger.error(f"[{agent_name}] Error in {func.__name__}: {e}")
                return {
                    "status": "failed",
                    "error": type(e).__name__,
                    "message": str(e),
                    "monitor_status": monitor.get_status(),
                }

        return wrapper
    return decorator


def safe_agent_execution(func):
    """
    Decorator for safe agent execution with automatic retries.
    
    Implements exponential backoff for transient failures.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = int(os.getenv("MAX_RETRIES", "3"))
        base_delay = 1  # seconds

        for attempt in range(max_retries + 1):
            try:
                result = func(*args, **kwargs)
                return result

            except Exception as e:
                if attempt == max_retries:
                    logger.error(f"[{func.__name__}] All retries exhausted. Last error: {e}")
                    raise

                delay = base_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(
                    f"[{func.__name__}] Attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)

        return {"status": "failed", "error": "All retries exhausted"}

    return wrapper


def validate_agent_input(query: str, min_length: int = 3, max_length: int = 500) -> bool:
    """Validate agent input parameters."""
    if not query or not isinstance(query, str):
        logger.error("Invalid input: query must be a non-empty string")
        return False

    if len(query) < min_length:
        logger.error(f"Invalid input: query too short (min {min_length} chars)")
        return False

    if len(query) > max_length:
        logger.error(f"Invalid input: query too long (max {max_length} chars)")
        return False

    return True


def log_agent_metrics(agent_name: str, metrics: Dict[str, Any]):
    """Log agent execution metrics for monitoring and debugging."""
    logger.info(f"[{agent_name}] Metrics: {metrics}")
