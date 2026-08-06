"""
Async Bridge Module

为 agentflow 处理器提供统一的异步调用桥接机制。

核心问题：agentflow 处理器在 ThreadPoolExecutor 线程中同步执行，
但需要调用 server 的异步服务（数据库 session 绑定到主事件循环）。
正确做法是通过 run_coroutine_threadsafe() 将协程调度回主循环执行。
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Optional

from .packet import InfoPacket, PacketType


# ── 主事件循环管理 ──

_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """设置主事件循环引用，供子线程中的 run_async 使用

    应在 FastAPI 启动时调用，保存 uvicorn 的事件循环。
    """
    global _main_loop
    _main_loop = loop


# ── 错误分类 ──


class AsyncBridgeError(Exception):
    """异步桥接错误基类"""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        self.message = message
        self.original_error = original_error
        super().__init__(message)


class TimeoutError(AsyncBridgeError):
    """超时错误"""
    pass


class NetworkError(AsyncBridgeError):
    """网络错误"""
    pass


class BusinessError(AsyncBridgeError):
    """业务逻辑错误"""
    pass


# ── 核心桥接函数 ──

_DEFAULT_TIMEOUT = 60.0


def run_async(
    coro,
    timeout: Optional[float] = None,
    context: str = "async operation",
) -> Any:
    """
    在子线程中运行异步协程，调度到主事件循环执行

    优先使用 run_coroutine_threadsafe 将协程调度到主事件循环，
    因为数据库 session 绑定到主循环，不能在子线程中用 asyncio.run() 创建新循环。

    Args:
        coro: 异步协程
        timeout: 超时时间（秒），默认 60s
        context: 操作上下文，用于错误信息

    Returns:
        协程的返回值

    Raises:
        TimeoutError: 操作超时
        AsyncBridgeError: 其他异步桥接错误
    """
    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    try:
        # 优先调度到主事件循环
        loop = _main_loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=effective_timeout)

        # fallback：尝试获取当前线程的循环
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is not None and current_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, current_loop)
            return future.result(timeout=effective_timeout)

        # 最后 fallback：直接 asyncio.run
        return asyncio.run(coro)

    except FutureTimeoutError as exc:
        raise TimeoutError(
            f"{context} timed out after {effective_timeout:.2f}s",
            original_error=exc,
        ) from exc
    except asyncio.CancelledError as exc:
        raise AsyncBridgeError(
            f"{context} was cancelled",
            original_error=exc,
        ) from exc
    except AsyncBridgeError:
        raise
    except Exception as exc:
        error_msg = str(exc).lower()
        if any(kw in error_msg for kw in ("connection", "network", "timeout")):
            raise NetworkError(
                f"{context} failed due to network error: {exc}",
                original_error=exc,
            ) from exc
        raise BusinessError(
            f"{context} failed: {exc}",
            original_error=exc,
        ) from exc


# ── Packet 辅助函数 ──


def success_packet(packet: InfoPacket, data: Any) -> InfoPacket:
    """创建成功响应包"""
    if isinstance(data, bytes):
        content = data.decode("utf-8", errors="replace")
    elif isinstance(data, (dict, list)):
        content = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    else:
        content = str(data)
    return packet.create_child(
        sender_id=packet.sender_id,
        content=content,
        packet_type=PacketType.RESPONSE,
        inherit_metadata=False,
    )


def error_packet(packet: InfoPacket, error: AsyncBridgeError) -> InfoPacket:
    """创建错误响应包，包含错误分类信息"""
    error_type = type(error).__name__
    error_message = error.message
    if error.original_error:
        error_message += f" (caused by: {type(error.original_error).__name__}: {error.original_error})"
    return packet.create_child(
        sender_id=packet.sender_id,
        content=f"Error [{error_type}]: {error_message}",
        packet_type=PacketType.ERROR,
        inherit_metadata=False,
    )


def safe_run_async(
    packet: InfoPacket,
    coro,
    timeout: Optional[float] = None,
    context: str = "async operation",
) -> InfoPacket:
    """
    安全运行异步协程，自动处理成功和错误情况

    Args:
        packet: 原始数据包
        coro: 异步协程
        timeout: 超时时间（秒）
        context: 操作上下文

    Returns:
        响应包（成功或错误）
    """
    try:
        result = run_async(coro, timeout=timeout, context=context)
        return success_packet(packet, result)
    except AsyncBridgeError as err:
        return error_packet(packet, err)
