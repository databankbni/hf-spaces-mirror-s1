"""
Notification Service
Handles notifications for sync failures and other events.
Supports WebSocket for real-time browser notifications.
"""

from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    SYNC_FAILED = "sync_failed"
    SYNC_SUCCESS = "sync_success"
    VALIDATION_ERROR = "validation_error"
    MAX_RETRIES = "max_retries_exceeded"
    SYSTEM_ERROR = "system_error"


class Notification:
    """Represents a notification"""
    
    def __init__(
        self,
        type: NotificationType,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        severity: str = "info"
    ):
        self.id = f"notif-{datetime.now().timestamp()}"
        self.type = type
        self.message = message
        self.data = data or {}
        self.severity = severity  # info, warning, error
        self.created_at = datetime.now()
        self.read = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "message": self.message,
            "data": self.data,
            "severity": self.severity,
            "created_at": self.created_at.isoformat(),
            "read": self.read
        }


class NotificationService:
    """
    Service for managing notifications.
    Supports in-memory storage and WebSocket broadcasting.
    """
    
    def __init__(self):
        self._notifications: List[Notification] = []
        self._max_notifications = 100
        self._websocket_clients: Set = set()
    
    async def notify(
        self,
        type: NotificationType,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        severity: str = "info"
    ) -> Notification:
        """Create and broadcast a notification"""
        notification = Notification(
            type=type,
            message=message,
            data=data,
            severity=severity
        )
        
        # Store notification
        self._notifications.insert(0, notification)
        
        # Trim old notifications
        if len(self._notifications) > self._max_notifications:
            self._notifications = self._notifications[:self._max_notifications]
        
        # Log
        log_method = logger.error if severity == "error" else (
            logger.warning if severity == "warning" else logger.info
        )
        log_method(f"Notification [{type.value}]: {message}")
        
        # Broadcast to WebSocket clients
        await self._broadcast(notification)
        
        return notification
    
    async def notify_sync_failed(
        self,
        item_id: str,
        error: str,
        retry_count: int
    ) -> Notification:
        """Convenience method for sync failure notifications"""
        return await self.notify(
            type=NotificationType.SYNC_FAILED,
            message=f"Gagal sinkronisasi data (percobaan ke-{retry_count})",
            data={
                "item_id": item_id,
                "error": error,
                "retry_count": retry_count
            },
            severity="warning" if retry_count < 3 else "error"
        )
    
    async def notify_max_retries(self, item_id: str) -> Notification:
        """Notify when max retries exceeded"""
        return await self.notify(
            type=NotificationType.MAX_RETRIES,
            message="Data gagal disinkronkan setelah beberapa percobaan",
            data={"item_id": item_id},
            severity="error"
        )
    
    async def notify_sync_success(self, item_id: str) -> Notification:
        """Notify successful sync"""
        return await self.notify(
            type=NotificationType.SYNC_SUCCESS,
            message="Data berhasil disinkronkan ke server",
            data={"item_id": item_id},
            severity="info"
        )
    
    def get_notifications(
        self,
        limit: int = 20,
        unread_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Get recent notifications"""
        notifications = self._notifications
        if unread_only:
            notifications = [n for n in notifications if not n.read]
        return [n.to_dict() for n in notifications[:limit]]
    
    def mark_as_read(self, notification_id: str) -> bool:
        """Mark a notification as read"""
        for notification in self._notifications:
            if notification.id == notification_id:
                notification.read = True
                return True
        return False
    
    def mark_all_read(self) -> int:
        """Mark all notifications as read"""
        count = 0
        for notification in self._notifications:
            if not notification.read:
                notification.read = True
                count += 1
        return count
    
    def get_unread_count(self) -> int:
        """Get count of unread notifications"""
        return len([n for n in self._notifications if not n.read])
    
    # WebSocket methods
    def register_client(self, websocket) -> None:
        """Register a WebSocket client for notifications"""
        self._websocket_clients.add(websocket)
        logger.info(f"WebSocket client registered. Total: {len(self._websocket_clients)}")
    
    def unregister_client(self, websocket) -> None:
        """Unregister a WebSocket client"""
        self._websocket_clients.discard(websocket)
        logger.info(f"WebSocket client unregistered. Total: {len(self._websocket_clients)}")
    
    async def _broadcast(self, notification: Notification) -> None:
        """Broadcast notification to all connected WebSocket clients"""
        if not self._websocket_clients:
            return
        
        message = notification.to_dict()
        disconnected = set()
        
        for client in self._websocket_clients:
            try:
                await client.send_json(message)
            except Exception:
                disconnected.add(client)
        
        # Clean up disconnected clients
        for client in disconnected:
            self._websocket_clients.discard(client)


# Singleton instance
notification_service = NotificationService()
