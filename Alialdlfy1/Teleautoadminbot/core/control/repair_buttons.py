from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ControlButton:
    key: str
    label: str
    callback: str

# Additive only: existing button callbacks are not renamed or removed.
REPAIR_BUTTONS = (
    ControlButton("repair_status", "🛠️ حالة الإصلاح التلقائي", "repair:status"),
    ControlButton("repair_pending", "🛡️ الإصلاحات بانتظار الموافقة", "repair:pending"),
    ControlButton("repair_approve", "✅ الموافقة على الإصلاح", "repair:approve"),
    ControlButton("repair_rollback", "↩️ التراجع عن آخر إصلاح", "repair:rollback"),
    ControlButton("repair_disable", "⛔ إيقاف الإصلاح التلقائي", "repair:disable"),
    ControlButton("repair_enable", "▶️ تشغيل الإصلاح التلقائي", "repair:enable"),
)
