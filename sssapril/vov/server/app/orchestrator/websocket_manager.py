"""
WebSocket管理器模块

负责管理WebSocket连接、房间和消息广播。
"""

from typing import Dict, Set, Optional, Any
from fastapi import WebSocket
import json
import asyncio


class WebSocketManager:
    """
    WebSocket连接管理器

    管理所有WebSocket连接，支持：
    - 群聊房间管理
    - 消息广播
    - 连接状态跟踪

    Example:
        manager = WebSocketManager()

        # 连接处理
        await manager.connect(websocket, group_id)

        # 广播消息
        await manager.broadcast(group_id, {"type": "message", "content": "..."})

        # 断开连接
        await manager.disconnect(websocket, group_id)
    """

    def __init__(self):
        """初始化WebSocket管理器"""
        # group_id -> set of websockets
        self._rooms: Dict[str, Set[WebSocket]] = {}
        # websocket -> group_id
        self._connections: Dict[WebSocket, str] = {}
        # websocket -> user info
        self._user_info: Dict[WebSocket, Dict[str, Any]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        group_id: str,
        user_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        建立WebSocket连接

        将连接加入指定群聊房间。

        Args:
            websocket: WebSocket连接
            group_id: 群聊ID
            user_info: 用户信息（可选）
        """
        await websocket.accept()

        # 添加到房间
        if group_id not in self._rooms:
            self._rooms[group_id] = set()
        self._rooms[group_id].add(websocket)

        # 记录连接
        self._connections[websocket] = group_id

        # 记录用户信息
        if user_info:
            self._user_info[websocket] = user_info

        # 通知房间内其他用户
        await self.broadcast(
            group_id,
            {
                "type": "user_joined",
                "payload": {
                    "user_info": user_info,
                    "online_count": len(self._rooms[group_id]),
                },
            },
            exclude=websocket,
        )

    async def disconnect(
        self,
        websocket: WebSocket,
        group_id: Optional[str] = None,
    ) -> None:
        """
        断开WebSocket连接

        从房间中移除连接。

        Args:
            websocket: WebSocket连接
            group_id: 群聊ID（可选，如果不提供则自动查找）
        """
        # 查找群聊ID
        if not group_id:
            group_id = self._connections.get(websocket)

        if group_id and group_id in self._rooms:
            self._rooms[group_id].discard(websocket)

            # 如果房间为空，删除房间
            if not self._rooms[group_id]:
                del self._rooms[group_id]

            # 通知房间内其他用户
            user_info = self._user_info.get(websocket)
            await self.broadcast(
                group_id,
                {
                    "type": "user_left",
                    "payload": {
                        "user_info": user_info,
                        "online_count": len(self._rooms.get(group_id, set())),
                    },
                },
            )

        # 清理连接记录
        self._connections.pop(websocket, None)
        self._user_info.pop(websocket, None)

    async def broadcast(
        self,
        group_id: str,
        message: Dict[str, Any],
        exclude: Optional[WebSocket] = None,
    ) -> None:
        """
        向房间内所有连接广播消息

        Args:
            group_id: 群聊ID
            message: 消息内容
            exclude: 排除的连接（可选）
        """
        import logging as _logging
        _log = _logging.getLogger("websocket_manager")
        msg_type = message.get("type", "?")
        if group_id not in self._rooms:
            _log.warning(f"[broadcast] DROP type={msg_type}: room not found group={group_id[:8]} (rooms={list(self._rooms.keys())[:3]})")
            return

        room = self._rooms[group_id]
        message_str = json.dumps(message)
        disconnected = set()
        sent = 0

        for websocket in room:
            if websocket == exclude:
                continue

            try:
                await websocket.send_text(message_str)
                sent += 1
            except Exception as e:
                # 连接已断开，标记为需要清理
                _log.warning(f"[broadcast] send_text FAILED type={msg_type}: {e}")
                disconnected.add(websocket)

        if sent == 0 and msg_type == "token":
            _log.warning(f"[broadcast] room EMPTY after send type={msg_type} group={group_id[:8]} room_size={len(room)}")

        # 清理断开的连接
        for websocket in disconnected:
            await self.disconnect(websocket, group_id)

    async def send_personal(
        self,
        websocket: WebSocket,
        message: Dict[str, Any],
    ) -> None:
        """
        向单个连接发送消息

        Args:
            websocket: WebSocket连接
            message: 消息内容
        """
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            # 连接已断开，清理
            group_id = self._connections.get(websocket)
            if group_id:
                await self.disconnect(websocket, group_id)

    def get_room_count(self, group_id: str) -> int:
        """
        获取房间内连接数

        Args:
            group_id: 群聊ID

        Returns:
            int: 连接数
        """
        return len(self._rooms.get(group_id, set()))

    def get_all_rooms(self) -> Dict[str, int]:
        """
        获取所有房间信息

        Returns:
            Dict[str, int]: 房间ID到连接数的映射
        """
        return {group_id: len(conns) for group_id, conns in self._rooms.items()}

    def is_connected(self, websocket: WebSocket) -> bool:
        """
        检查连接是否仍然有效

        Args:
            websocket: WebSocket连接

        Returns:
            bool: 是否连接
        """
        return websocket in self._connections


# 全局WebSocket管理器实例
ws_manager = WebSocketManager()
