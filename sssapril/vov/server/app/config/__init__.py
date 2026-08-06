"""
执行模式服务 (ExecutionModeService)

提供 system_prompt suffix 注入：
- 根据 group.autonomy_level + variant 选对应的执行模式 prompt
- 支持 A/B 测试：通过环境变量 AGENTFLOW_EXEC_VARIANT 全局切换
- 支持项目级 override：group.workflow_config.execution_variant
- 配置热重载：mtime 检测 + 缓存失效

A/B 测试说明：
- 不设 AGENTFLOW_EXEC_VARIANT → 用每种 mode 的 default_variant
- 设 AGENTFLOW_EXEC_VARIANT=full_auto_strict → 全局切到该变体
- 项目级 group.workflow_config.execution_variant 优先级最高

后续优化：
- 跑一段时间后挑出最优变体，把 default_variant 改掉
- 归档非最优的 markdown 文件（用 git diff 对比）
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def _get_execution_modes_path() -> Path:
    """获取 execution_modes.json 路径（支持 frozen 模式）"""
    import sys
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        internal = exe_dir / "_internal"
        if internal.exists():
            return internal / "config" / "execution_modes.json"
        return Path(getattr(sys, '_MEIPASS', exe_dir)) / "config" / "execution_modes.json"
    else:
        return Path(__file__).resolve().parent / "execution_modes.json"


class ExecutionModeService:
    """
    执行模式查询服务（单例 + 线程安全）

    使用方式：
        service = ExecutionModeService.instance()
        suffix = service.get_system_suffix(
            autonomy_level="full_auto",
            variant="balanced",  # 可选
            project_override="strict",  # 可选（项目级优先）
        )
    """
    _instance: Optional["ExecutionModeService"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._config_path = _get_execution_modes_path()
        self._config_mtime: float = 0
        self._config: Dict[str, Any] = {}
        self._load_config()

    @classmethod
    def instance(cls) -> "ExecutionModeService":
        """单例访问"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例（测试用）"""
        with cls._lock:
            cls._instance = None

    def _load_config(self) -> None:
        """加载/重新加载配置文件"""
        if not self._config_path.exists():
            logger.warning("execution_modes.json not found at %s", self._config_path)
            self._config = {"modes": {}}
            self._config_mtime = 0
            return

        try:
            mtime = self._config_path.stat().st_mtime
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            self._config_mtime = mtime
            logger.info(
                "Loaded execution_modes.json (modes=%s, env_override=%s)",
                list(self._config.get("modes", {}).keys()),
                os.environ.get("AGENTFLOW_EXEC_VARIANT", "(none)"),
            )
        except Exception as e:
            logger.error("Failed to load execution_modes.json: %s", e)
            self._config = {"modes": {}}

    def _maybe_reload(self) -> None:
        """检测文件修改，重载（热重载）"""
        if not self._config_path.exists():
            return
        try:
            current_mtime = self._config_path.stat().st_mtime
            if current_mtime > self._config_mtime:
                self._load_config()
        except Exception as e:
            logger.warning("Failed to check mtime: %s", e)

    def get_system_suffix(
        self,
        autonomy_level: str,
        variant: Optional[str] = None,
        project_override: Optional[str] = None,
    ) -> str:
        """
        获取 autonomy_level 对应的 system_prompt suffix

        优先级（从高到低）：
        1. project_override（项目级 workflow_config.execution_variant）
        2. variant 参数（agent 级传入）
        3. AGENTFLOW_EXEC_VARIANT 环境变量（全局 A/B 测试）
        4. mode 的 default_variant

        Args:
            autonomy_level: full_auto / semi_auto / manual
            variant: 可选变体名
            project_override: 项目级覆盖

        Returns:
            要追加到 system_prompt 的字符串（无变体时返回空字符串）
        """
        self._maybe_reload()

        modes = self._config.get("modes", {})
        mode_config = modes.get(autonomy_level)
        if not mode_config:
            logger.debug("No execution mode config for autonomy_level=%s", autonomy_level)
            return ""

        # 优先级 1: 项目级 override
        effective_variant = project_override

        # 优先级 2: 显式传入的 variant
        if not effective_variant:
            effective_variant = variant

        # 优先级 3: 环境变量
        if not effective_variant:
            env_override = os.environ.get("AGENTFLOW_EXEC_VARIANT", "").strip()
            if env_override and env_override != "default":
                # 环境变量支持多种格式：
                # "full_auto_strict" → 只切 full_auto 的 strict
                # "strict" → 切所有 mode 的 strict
                # 优先精确匹配
                if env_override.startswith(f"{autonomy_level}_"):
                    effective_variant = env_override[len(autonomy_level) + 1:]
                elif "_" not in env_override:
                    effective_variant = env_override

        # 优先级 4: 默认变体
        if not effective_variant:
            effective_variant = mode_config.get("default_variant", "balanced")

        variants = mode_config.get("variants", {})
        variant_config = variants.get(effective_variant)

        if not variant_config:
            logger.warning(
                "Variant '%s' not found for mode '%s', falling back to default",
                effective_variant, autonomy_level,
            )
            effective_variant = mode_config.get("default_variant", "balanced")
            variant_config = variants.get(effective_variant)

        if not variant_config:
            return ""

        return variant_config.get("system_suffix", "")

    def get_mode_info(
        self,
        autonomy_level: str,
        variant: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取模式信息（调试/日志用）

        Returns:
            {
                "mode": "full_auto",
                "variant": "balanced",
                "label": "全自动 - 平衡（推荐起步）",
                "intensity": "medium",
            }
        """
        self._maybe_reload()
        modes = self._config.get("modes", {})
        mode_config = modes.get(autonomy_level, {})

        if not variant:
            variant = mode_config.get("default_variant", "balanced")

        variant_config = mode_config.get("variants", {}).get(variant, {})

        return {
            "mode": autonomy_level,
            "variant": variant,
            "label": variant_config.get("label", "?"),
            "intensity": variant_config.get("intensity", "?"),
            "env_override": os.environ.get("AGENTFLOW_EXEC_VARIANT", ""),
        }

    def list_variants(self, autonomy_level: str) -> list[str]:
        """列出某个 mode 的所有变体名"""
        self._maybe_reload()
        modes = self._config.get("modes", {})
        mode_config = modes.get(autonomy_level, {})
        return list(mode_config.get("variants", {}).keys())
