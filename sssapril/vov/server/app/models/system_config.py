"""
系统配置模型

存储运行时配置项（如 LLM API Key），支持热更新，无需重启。
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class SystemConfig(BaseModel):
    """
    系统配置表

    存储 key-value 配置项，value 为 JSON 字符串。
    用于替代 .env 文件中的业务配置，支持运行时修改。
    """

    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="配置键名，如 llm.api_key, llm.base_url"
    )

    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="配置值（JSON 字符串或纯文本）"
    )

    def __repr__(self) -> str:
        return f"<SystemConfig(key={self.key})>"
