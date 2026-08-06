#!/usr/bin/env python3
"""Competition quality tiers and metric isolation for football predictions."""
from __future__ import annotations
from typing import Any

TIER_1 = (
    "世界杯", "欧洲杯", "美洲杯", "亚洲杯", "非洲杯", "英超", "西甲", "德甲", "意甲", "法甲",
    "欧冠", "歐冠", "欧联", "歐聯", "欧罗巴", "歐霸", "欧霸", "Europa League",
    "欧协联", "歐協聯", "亚冠", "解放者杯",
)
TIER_2 = (
    "挪超", "瑞典超", "芬超", "丹超", "冰岛超", "巴甲", "阿甲", "智利甲", "乌拉圭甲",
    "日职联", "韩K联", "中超", "澳超",
)
ISOLATED_MARKERS = (
    "友谊", "友誼", "热身", "熱身", "青年", "预备", "預備", "后备", "後備",
    "U23", "U21", "U20", "U19", "U18", "U17", "乙曼",
    "英议南", "英議南", "英议北", "英議北", "业余", "業餘",
)

# competition_stage 关键词：命中任意一个即视为资格赛阶段，强制路由至独立桶
QUALIFYING_STAGE_MARKERS = (
    "qualifying", "QUALIFYING",
    "预选", "资格赛", "预赛", "外围赛", "附加赛",
)


def classify(
    league: str,
    home: str = "",
    away: str = "",
    competition_stage: str = "",
) -> dict[str, Any]:
    """Classify a match into a competition tier for metric isolation.

    Parameters
    ----------
    league : str
        League/competition name.
    home : str
        Home team name (used for ISOLATED_MARKERS scan only).
    away : str
        Away team name (used for ISOLATED_MARKERS scan only).
    competition_stage : str
        Competition stage string from the sport_adapter (e.g. "QUALIFYING",
        "GROUP_STAGE", "FINAL"). When this field signals a qualifying round,
        the match is routed to QUALIFYING_ISOLATED regardless of the league
        tier — preventing resources from contaminating T1/T2 primary stats.
        Pass "" or "NOT_APPLICABLE" when stage is unknown/not applicable.
    """
    # P1 fix: QUALIFYING stage is always isolated, regardless of league tier.
    # This prevents e.g. UCL/UEL qualifying rounds from entering TIER_1/T2 stats.
    stage_text = str(competition_stage).strip()
    if any(m.lower() in stage_text.lower() for m in QUALIFYING_STAGE_MARKERS):
        return {
            "tier": "QUALIFYING_ISOLATED",
            "bucket": "qualifying_round",
            "primary_accuracy_eligible": False,
            "diagnostic_accuracy_eligible": True,
            "separate_bucket_required": True,
            "qualifying_stage_detected": True,
        }

    text = " ".join((str(league), str(home), str(away)))
    if any(marker.lower() in text.lower() for marker in ISOLATED_MARKERS):
        return {
            "tier": "TIER_4_ISOLATED", "bucket": "low_level_youth_reserve_friendly",
            "primary_accuracy_eligible": False, "diagnostic_accuracy_eligible": True,
            "separate_bucket_required": True,
            "qualifying_stage_detected": False,
        }
    if any(marker in text for marker in TIER_1):
        return {
            "tier": "TIER_1", "bucket": "major_or_continental",
            "primary_accuracy_eligible": True, "diagnostic_accuracy_eligible": True,
            "separate_bucket_required": False,
            "qualifying_stage_detected": False,
        }
    if any(marker in text for marker in TIER_2):
        return {
            "tier": "TIER_2", "bucket": "proven_regular_league",
            "primary_accuracy_eligible": True, "diagnostic_accuracy_eligible": True,
            "separate_bucket_required": False,
            "qualifying_stage_detected": False,
        }
    return {
        "tier": "TIER_3_SEPARATE", "bucket": "uncalibrated_or_other",
        "primary_accuracy_eligible": False, "diagnostic_accuracy_eligible": True,
        "separate_bucket_required": True,
        "qualifying_stage_detected": False,
    }
