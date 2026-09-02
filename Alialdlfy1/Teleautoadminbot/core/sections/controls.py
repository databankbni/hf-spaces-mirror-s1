from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SectionButton:
    key: str
    label: str
    callback: str

COMMON_SECTION_BUTTONS = (
    SectionButton("settings", "⚙️ الإعدادات", "{section}:settings"),
    SectionButton("sources", "📡 المصادر", "{section}:sources"),
    SectionButton("blocked", "🚫 الكلمات المحظورة", "{section}:blocked"),
    SectionButton("duplicates", "♻️ منع التكرار", "{section}:duplicates"),
    SectionButton("ai", "🤖 إعدادات الذكاء الاصطناعي", "{section}:ai"),
    SectionButton("queue", "📋 الطابور", "{section}:queue"),
    SectionButton("metrics", "📈 الإحصائيات", "{section}:metrics"),
    SectionButton("health", "🩺 الصحة", "{section}:health"),
    SectionButton("dead", "☠️ المهام الفاشلة", "{section}:dead"),
    SectionButton("status", "📊 الحالة", "{section}:status"),
    SectionButton("enable", "▶️ تشغيل القسم", "{section}:enable"),
    SectionButton("disable", "⛔ إيقاف القسم", "{section}:disable"),
    SectionButton("repair", "🛠️ الإصلاح التلقائي", "{section}:repair"),
)

def build_section_buttons(section: str):
    return tuple(
        SectionButton(x.key, x.label, x.callback.format(section=section))
        for x in COMMON_SECTION_BUTTONS
    )
