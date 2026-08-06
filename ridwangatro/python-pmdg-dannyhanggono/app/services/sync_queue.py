"""
Sync Queue Service
Manages background sync queue with retry logic for failed operations.
Compatible with Railway deployment.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
    DEAD = "dead"  # Max retries exceeded


class SyncItem:
    """Represents an item in the sync queue"""
    
    def __init__(
        self,
        id: str,
        data: Dict[str, Any],
        entity_type: str = "patient",
        operation: str = "create"
    ):
        self.id = id
        self.data = data
        self.entity_type = entity_type
        self.operation = operation
        self.status = SyncStatus.PENDING
        self.retry_count = 0
        self.max_retries = 3
        self.created_at = datetime.now()
        self.last_attempt = None
        self.error_message = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "data": self.data,
            "entity_type": self.entity_type,
            "operation": self.operation,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "error_message": self.error_message
        }


class SyncQueueService:
    """
    In-memory sync queue with background processing.
    Can be upgraded to Redis for production scale.
    """
    
    def __init__(self):
        self._queue: Dict[str, SyncItem] = {}
        self._dead_letter: Dict[str, SyncItem] = {}
        self._processing = False
        self._process_interval = 10  # seconds
    
    async def add_to_queue(
        self,
        item_id: str,
        data: Dict[str, Any],
        entity_type: str = "patient",
        operation: str = "create"
    ) -> SyncItem:
        """Add item to sync queue"""
        item = SyncItem(
            id=item_id,
            data=data,
            entity_type=entity_type,
            operation=operation
        )
        self._queue[item_id] = item
        logger.info(f"Added to sync queue: {item_id}")
        return item
    
    def get_item(self, item_id: str) -> Optional[SyncItem]:
        """Get item from queue by ID"""
        return self._queue.get(item_id) or self._dead_letter.get(item_id)
    
    def get_pending_items(self) -> List[SyncItem]:
        """Get all pending items"""
        return [
            item for item in self._queue.values()
            if item.status in [SyncStatus.PENDING, SyncStatus.FAILED]
        ]
    
    def get_all_items(self) -> Dict[str, List[Dict]]:
        """Get all items grouped by status"""
        return {
            "queue": [item.to_dict() for item in self._queue.values()],
            "dead_letter": [item.to_dict() for item in self._dead_letter.values()]
        }
    
    async def mark_success(self, item_id: str) -> None:
        """Mark item as successfully synced and remove from queue"""
        if item_id in self._queue:
            del self._queue[item_id]
            logger.info(f"Sync success, removed from queue: {item_id}")
    
    async def mark_failed(self, item_id: str, error: str) -> None:
        """Mark item as failed, increment retry count"""
        item = self._queue.get(item_id)
        if not item:
            return
        
        item.status = SyncStatus.FAILED
        item.retry_count += 1
        item.last_attempt = datetime.now()
        item.error_message = error
        
        # Move to dead letter if max retries exceeded
        if item.retry_count >= item.max_retries:
            item.status = SyncStatus.DEAD
            self._dead_letter[item_id] = item
            del self._queue[item_id]
            logger.warning(f"Max retries exceeded, moved to dead letter: {item_id}")
        else:
            logger.info(f"Sync failed (attempt {item.retry_count}): {item_id}")
    
    async def retry_item(self, item_id: str) -> Optional[SyncItem]:
        """Manually retry a specific item (including from dead letter)"""
        item = self._dead_letter.get(item_id)
        if item:
            # Move back from dead letter to queue
            item.status = SyncStatus.PENDING
            item.retry_count = 0
            self._queue[item_id] = item
            del self._dead_letter[item_id]
            logger.info(f"Moved from dead letter back to queue: {item_id}")
            return item
        
        item = self._queue.get(item_id)
        if item:
            item.status = SyncStatus.PENDING
            return item
        
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        queue_items = list(self._queue.values())
        return {
            "total_in_queue": len(queue_items),
            "pending": len([i for i in queue_items if i.status == SyncStatus.PENDING]),
            "failed": len([i for i in queue_items if i.status == SyncStatus.FAILED]),
            "dead_letter_count": len(self._dead_letter),
            "is_processing": self._processing
        }


# Singleton instance
sync_queue = SyncQueueService()
