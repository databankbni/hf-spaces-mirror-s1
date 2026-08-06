"""
启动初始化

首次运行时：
1. 从 default_presets/presets.json 加载默认 Skills 和 Agents 到数据库
2. 从配置文件加载默认 LLM 配置到数据库
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _get_default_config_path() -> Path:
    """获取默认配置文件路径"""
    import sys
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        internal = exe_dir / "_internal"
        if internal.exists():
            return internal / "default_config.json"
        return Path(getattr(sys, '_MEIPASS', exe_dir)) / "default_config.json"
    else:
        return Path(__file__).resolve().parent.parent / "default_config.json"


def _get_presets_path() -> Path:
    """获取预设文件路径"""
    import sys
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        internal = exe_dir / "_internal"
        if internal.exists():
            return internal / "default_presets" / "presets.json"
        return Path(getattr(sys, '_MEIPASS', exe_dir)) / "default_presets" / "presets.json"
    else:
        return Path(__file__).resolve().parent.parent / "default_presets" / "presets.json"


def _read_config_file() -> dict:
    """读取配置文件"""
    config_path = _get_default_config_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to read config file %s: %s", config_path, e)
        return {}


def _read_presets_file() -> List[Dict[str, Any]]:
    """读取预设文件，返回 items 列表"""
    presets_path = _get_presets_path()
    if not presets_path.exists():
        logger.warning("Presets file not found: %s", presets_path)
        return []
    try:
        with open(presets_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except Exception as e:
        logger.warning("Failed to read presets file %s: %s", presets_path, e)
        return []


async def init_default_skills(session_factory) -> None:
    """首次运行时从预设文件创建默认 Skills"""
    from sqlalchemy import select, func
    from app.models.agent import Skill

    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(Skill))
        count = result.scalar() or 0

    if count > 0:
        return  # 已有 skills，跳过

    items = _read_presets_file()
    skills = [item for item in items if item.get("type") == "skill"]

    if not skills:
        logger.info("No default skills found in presets")
        return

    async with session_factory() as session:
        for s in skills:
            skill = Skill(
                name=s["name"],
                description=s.get("description"),
                skill_type=s.get("skill_type", "prompt"),
                content=s.get("content", ""),
                config=s.get("config", {}),
                files=s.get("files", {}),
            )
            session.add(skill)

        await session.commit()

    logger.info("Default skills created: %s", [s["name"] for s in skills])


async def init_default_agents(session_factory) -> None:
    """首次运行时从预设文件创建默认 Agents"""
    from sqlalchemy import select, func
    from app.models.agent import Agent, AgentSkill, AgentTool, Skill

    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(Agent))
        count = result.scalar() or 0

    if count > 0:
        return  # 已有 agents，跳过

    items = _read_presets_file()
    agents = [item for item in items if item.get("type") == "agent"]

    if not agents:
        logger.info("No default agents found in presets")
        return

    # 获取已创建的 skills 映射
    async with session_factory() as session:
        skills_result = await session.execute(select(Skill))
        skill_map = {s.name: s.id for s in skills_result.scalars().all()}

    async with session_factory() as session:
        for a in agents:
            agent = Agent(
                name=a["name"],
                avatar=a.get("avatar"),
                description=a.get("description"),
                system_prompt=a.get("system_prompt", ""),
                llm_config=a.get("llm_config", {}),
                capabilities=a.get("capabilities", []),
            )
            session.add(agent)
            await session.flush()

            # 绑定工具
            for tool_data in a.get("tools", []):
                session.add(AgentTool(
                    agent_id=agent.id,
                    name=tool_data["name"],
                    kind=tool_data.get("kind", tool_data["name"]),
                    tool_type=tool_data.get("tool_type", "builtin"),
                    description=tool_data.get("description"),
                    config=tool_data.get("config", {}),
                ))

            # 绑定 Skills
            for skill_name in a.get("skill_refs", []):
                if skill_name in skill_map:
                    session.add(AgentSkill(
                        agent_id=agent.id,
                        skill_id=skill_map[skill_name],
                    ))

        await session.commit()

    logger.info("Default agents created: %s", [a["name"] for a in agents])


async def init_llm_config(session_factory) -> None:
    """
    初始化 LLM 配置（首次运行时）

    优先级：DB 中已有的值 > 配置文件 > 环境变量
    只在 DB 中没有对应 key 时才写入。
    """
    from sqlalchemy import select, func
    from app.models.system_config import SystemConfig

    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(SystemConfig).where(
                SystemConfig.key.in_(["llm.api_key", "llm.base_url", "llm.default_model"])
            )
        )
        count = result.scalar() or 0

    if count > 0:
        logger.info("LLM config already in DB (%d keys), skipping init", count)
        return

    file_config = _read_config_file().get("llm", {})

    defaults = {
        "llm.api_key": file_config.get("api_key", "") or _get_env_fallback("OPENAI_API_KEY", ""),
        "llm.base_url": file_config.get("base_url", "") or _get_env_fallback("OPENAI_BASE_URL", ""),
        "llm.default_model": file_config.get("default_model", "") or _get_env_fallback("DEFAULT_LLM_MODEL", ""),
    }

    to_write = {k: v for k, v in defaults.items() if v}
    if not to_write:
        logger.info("No default LLM config found (file or env)")
        return

    async with session_factory() as session:
        for key, value in to_write.items():
            session.add(SystemConfig(key=key, value=value))
        await session.commit()

    logger.info("LLM config initialized from defaults: %s", list(to_write.keys()))


def _get_env_fallback(key: str, default: str = "") -> str:
    """从环境变量或 .env 文件获取值"""
    import os
    value = os.environ.get(key, "")
    if value:
        return value
    try:
        from dotenv import dotenv_values
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            env_values = dotenv_values(env_path)
            return env_values.get(key) or default
    except ImportError:
        pass
    return default
