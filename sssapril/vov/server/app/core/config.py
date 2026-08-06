"""
应用配置模块

使用Pydantic Settings管理配置，支持从环境变量和.env文件加载。
统一使用 SQLite 作为数据库。
"""

import json
import sys
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


def _default_data_dir() -> Path:
    """获取默认数据目录：~/AgentFlow/data/"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包模式：数据放在用户目录
        data_dir = Path.home() / "AgentFlow" / "data"
    else:
        # 开发模式：数据放在项目目录
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class Settings(BaseSettings):
    """
    应用配置类

    配置优先级：环境变量 > .env文件 > 默认值
    """

    # 应用基础配置
    APP_NAME: str = "AgentFlow"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # API配置
    API_V1_PREFIX: str = "/api/v1"

    # CORS配置
    # 存为 str 让 model_validator 自由解析（支持 JSON 数组 / 逗号分隔 / "*"）
    CORS_ORIGINS: str = ",".join([
        "http://localhost:3000", "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
        "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175",
        "http://0.0.0.0:5173", "http://0.0.0.0:5174",
    ])

    def get_cors_origins(self) -> list[str]:
        """获取 CORS 允许的 origin 列表（已解析）"""
        # 注: assemble_db_url 会在实例化时把 str 解析为 list 写入 _cors_origins_parsed
        parsed = getattr(self, "_cors_origins_parsed", None)
        if parsed is not None:
            return parsed
        # 兜底: 默认逗号分隔解析
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # 内部字段: CORS_ORIGINS 解析后的列表（model_validator 填充）
    _cors_origins_parsed: Optional[list[str]] = None

    # 数据库配置（统一 SQLite）
    DATABASE_URL: Optional[str] = None
    SQLITE_PATH: str = ""  # 空字符串 = 使用默认路径 ~/AgentFlow/data/agentflow.db

    # LLM配置
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: Optional[str] = None
    LLM_API_BASE: Optional[str] = None
    DEFAULT_LLM_MODEL: str = "gpt-4o"

    # OpenAI配置（兼容旧配置）
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None

    # Anthropic配置
    ANTHROPIC_API_KEY: Optional[str] = None

    def get_llm_api_key(self) -> Optional[str]:
        """获取LLM API Key（优先 LLM_API_KEY，其次 OPENAI_API_KEY）"""
        return self.LLM_API_KEY or self.OPENAI_API_KEY

    def get_llm_api_base(self) -> Optional[str]:
        """获取LLM API Base URL（优先 LLM_API_BASE，其次 OPENAI_BASE_URL）"""
        return self.LLM_API_BASE or self.OPENAI_BASE_URL

    @model_validator(mode='before')
    @classmethod
    def assemble_db_url(cls, data: dict) -> dict:
        """组装 SQLite 数据库 URL + 解析 CORS_ORIGINS 环境变量"""
        # 1) 解析 CORS_ORIGINS（支持 JSON 数组 / 逗号分隔 / "*"）
        cors = data.get('CORS_ORIGINS')
        if isinstance(cors, str):
            cors_str = cors.strip()
            if not cors_str:
                data['_cors_origins_parsed'] = []
            elif cors_str.startswith('['):
                # JSON 数组: ["*"] 或 ["https://a.com"]
                data['_cors_origins_parsed'] = json.loads(cors_str)
            else:
                # 逗号分隔 / 单值: "*" 或 https://a.com,https://b.com
                data['_cors_origins_parsed'] = [o.strip() for o in cors_str.split(',') if o.strip()]

        # 2) 组装 SQLite URL
        if data.get('DATABASE_URL'):
            return data

        sqlite_path = data.get('SQLITE_PATH', '')
        if not sqlite_path:
            sqlite_path = str(_default_data_dir() / "agentflow.db")
        data['DATABASE_URL'] = f"sqlite+aiosqlite:///{sqlite_path}"
        return data

    # 允许 extra 字段（用于 model_validator 注入 _cors_origins_parsed）
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )


# 全局配置实例
settings = Settings()
