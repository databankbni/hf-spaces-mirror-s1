from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import os
import threading
from typing import Any, Callable


class ProcessorExecutors:
    _dispatch_workers = max(8, (os.cpu_count() or 4) * 4)
    _call_workers = max(8, (os.cpu_count() or 4) * 4)
    _dispatch = ThreadPoolExecutor(max_workers=_dispatch_workers, thread_name_prefix="agentflow-dispatch")
    _calls = ThreadPoolExecutor(max_workers=_call_workers, thread_name_prefix="agentflow-call")
    _inflight = threading.BoundedSemaphore(_dispatch_workers * 4)
    _lock = threading.RLock()

    @classmethod
    def _executor_is_shutdown(cls, executor: ThreadPoolExecutor) -> bool:
        return bool(getattr(executor, "_shutdown", False))

    @classmethod
    def _reset_dispatch_executor(cls) -> None:
        with cls._lock:
            if not cls._executor_is_shutdown(cls._dispatch):
                return
            cls._dispatch = ThreadPoolExecutor(
                max_workers=cls._dispatch_workers,
                thread_name_prefix="agentflow-dispatch",
            )

    @classmethod
    def _reset_call_executor(cls) -> None:
        with cls._lock:
            if not cls._executor_is_shutdown(cls._calls):
                return
            cls._calls = ThreadPoolExecutor(
                max_workers=cls._call_workers,
                thread_name_prefix="agentflow-call",
            )

    @classmethod
    def submit_process(cls, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        cls._inflight.acquire()

        def wrapped() -> None:
            try:
                func(*args, **kwargs)
            finally:
                cls._inflight.release()

        try:
            cls._dispatch.submit(wrapped)
        except RuntimeError as exc:
            if "shutdown" not in str(exc).lower():
                cls._inflight.release()
                raise
            cls._reset_dispatch_executor()
            try:
                cls._dispatch.submit(wrapped)
            except RuntimeError:
                cls._inflight.release()
                raise

    @classmethod
    def run_sync(cls, func: Callable[[], Any], timeout: float | None = None) -> Any:
        if timeout is None:
            return func()
        try:
            future = cls._calls.submit(func)
        except RuntimeError as exc:
            if "shutdown" not in str(exc).lower():
                raise
            cls._reset_call_executor()
            future = cls._calls.submit(func)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"Processor core_process timed out after {timeout:.2f}s") from exc

    @staticmethod
    def run_async(coro, timeout: float | None = None) -> Any:
        effective_timeout = timeout or 300.0  # 兜底 5 分钟超时
        return asyncio.run(asyncio.wait_for(coro, timeout=effective_timeout))
