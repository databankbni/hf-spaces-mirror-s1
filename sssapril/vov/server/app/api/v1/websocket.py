"""
WebSocket API模块

提供WebSocket端点，用于实时消息通信。
"""

from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.orchestrator.websocket_manager import ws_manager
from app.orchestrator.message_dispatcher import MessageDispatcher, MessageType
from app.orchestrator.autonomy_controller import AutonomyController
from app.models.group import Group

import json

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/groups/{group_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    group_id: str,
    user_id: Optional[str] = Query(None, description="用户ID"),
    user_name: Optional[str] = Query(None, description="用户名"),
):
    """
    群聊WebSocket端点

    建立WebSocket连接，接收和发送实时消息。

    消息格式：
    ```json
    {
        "type": "send_message" | "stop_agent" | "resume",
        "payload": { ... }
    }
    ```

    Args:
        websocket: WebSocket连接
        group_id: 群聊ID
        user_id: 用户ID（可选）
        user_name: 用户名（可选）
    """
    # 连接
    user_info = {"id": user_id, "name": user_name} if user_id else None
    import logging as _logging
    _log = _logging.getLogger("ws_endpoint")
    _log.info(f"[WS connect] group={group_id[:8]} user={user_name or user_id or '?'}")
    await ws_manager.connect(websocket, group_id, user_info)
    _log.info(f"[WS connect] room count={ws_manager.get_room_count(group_id)} group={group_id[:8]}")

    try:
        # 获取数据库会话
        from app.core.database import async_session_factory
        async for db in get_db():
            dispatcher = MessageDispatcher(async_session_factory)

            # 消息处理循环
            while True:
                # 接收消息
                data = await websocket.receive_text()
                message = json.loads(data)

                msg_type = message.get("type")
                payload = message.get("payload", {})

                # 处理不同类型的消息
                if msg_type == MessageType.SEND_MESSAGE:
                    await handle_send_message(
                        websocket, group_id, payload, dispatcher, db
                    )
                elif msg_type == MessageType.STOP_AGENT:
                    await handle_stop_agent(payload, dispatcher)
                elif msg_type == MessageType.RESUME:
                    await handle_resume(
                        websocket, group_id, payload, dispatcher, db
                    )
                elif msg_type == MessageType.PING:
                    # 客户端心跳：原路回 pong，不进 dispatcher，不污染消息流
                    await ws_manager.send_personal(
                        websocket,
                        {"type": MessageType.PONG, "payload": {"t": message.get("t")}},
                    )
                else:
                    await ws_manager.send_personal(
                        websocket,
                        {
                            "type": MessageType.ERROR,
                            "payload": {"message": f"Unknown message type: {msg_type}"},
                        },
                    )

    except WebSocketDisconnect:
        # 客户端断开连接
        await ws_manager.disconnect(websocket, group_id)
    except Exception as e:
        # 其他错误
        await ws_manager.send_personal(
            websocket,
            {
                "type": MessageType.ERROR,
                "payload": {"message": str(e)},
            },
        )
        await ws_manager.disconnect(websocket, group_id)


async def handle_send_message(
    websocket: WebSocket,
    group_id: str,
    payload: dict,
    dispatcher: MessageDispatcher,
    db: AsyncSession,
) -> None:
    """
    处理发送消息

    Args:
        websocket: WebSocket连接
        group_id: 群聊ID
        payload: 消息负载
        dispatcher: 消息调度器
        db: 数据库会话
    """
    content = payload.get("content")
    chain_id = payload.get("chain_id")

    if not content:
        await ws_manager.send_personal(
            websocket,
            {
                "type": MessageType.ERROR,
                "payload": {"message": "Content is required"},
            },
        )
        return

    if not chain_id:
        await ws_manager.send_personal(
            websocket,
            {
                "type": MessageType.ERROR,
                "payload": {"message": "Chain ID is required"},
            },
        )
        return

    # 广播用户消息
    await ws_manager.broadcast(
        group_id,
        {
            "type": MessageType.AGENT_MESSAGE,
            "payload": {
                "chain_id": chain_id,
                "sender_type": "user",
                "sender_id": payload.get("sender_id"),
                "sender_name": payload.get("sender_name", "User"),
                "content": content,
            },
        },
    )

    # 获取群聊信息以检查自主级别
    from sqlalchemy import select
    query = select(Group).where(Group.id == group_id)
    result = await db.execute(query)
    group = result.scalar_one_or_none()

    if not group:
        return

    # 检查自主级别
    controller = AutonomyController(group)

    if controller.can_auto_speak():
        # 自动触发Agent响应
        async def on_typing(agent_id: str, agent_name: str):
            await ws_manager.broadcast(
                group_id,
                {
                    "type": MessageType.AGENT_TYPING,
                    "payload": {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                    },
                },
            )

        async def on_message(message: dict):
            await ws_manager.broadcast(group_id, message)

        await dispatcher.dispatch(
            chain_id=chain_id,
            user_message=content,
            on_message=on_message,
            on_typing=on_typing,
        )
    else:
        # 手动模式，等待用户触发
        await ws_manager.broadcast(
            group_id,
            {
                "type": MessageType.SYSTEM_MESSAGE,
                "payload": {
                    "event": "waiting_for_approval",
                    "message": controller.get_waiting_reason("speak"),
                },
            },
        )


async def handle_stop_agent(
    payload: dict,
    dispatcher: MessageDispatcher,
) -> None:
    """
    处理停止Agent

    Args:
        payload: 消息负载
        dispatcher: 消息调度器
    """
    chain_id = payload.get("chain_id")
    if chain_id:
        await dispatcher.stop(chain_id)


async def handle_resume(
    websocket: WebSocket,
    group_id: str,
    payload: dict,
    dispatcher: MessageDispatcher,
    db: AsyncSession,
) -> None:
    """
    处理恢复操作

    Args:
        websocket: WebSocket连接
        group_id: 群聊ID
        payload: 消息负载
        dispatcher: 消息调度器
        db: 数据库会话
    """
    chain_id = payload.get("chain_id")

    if not chain_id:
        await ws_manager.send_personal(
            websocket,
            {
                "type": MessageType.ERROR,
                "payload": {"message": "Chain ID is required"},
            },
        )
        return

    # 获取群聊信息
    from sqlalchemy import select
    query = select(Group).where(Group.id == group_id)
    result = await db.execute(query)
    group = result.scalar_one_or_none()

    if not group:
        return

    # 检查自主级别
    controller = AutonomyController(group)

    if controller.can_auto_speak():
        # 自动触发Agent响应
        async def on_typing(agent_id: str, agent_name: str):
            await ws_manager.broadcast(
                group_id,
                {
                    "type": MessageType.AGENT_TYPING,
                    "payload": {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                    },
                },
            )

        async def on_message(message: dict):
            await ws_manager.broadcast(group_id, message)

        await dispatcher.dispatch(
            chain_id=chain_id,
            on_message=on_message,
            on_typing=on_typing,
        )
