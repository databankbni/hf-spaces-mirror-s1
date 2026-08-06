"""
链交接服务模块

当对话历史超出上下文窗口的70%时，触发"交接仪式"：
1. 引导LLM总结当前需求和进度
2. 将旧链标记为completed
3. 创建新链，以总结作为链头
4. 支持跨链记忆查询
"""

import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.config import settings
from app.models.chain import Chain, Packet


class ChainRolloverService:

    TRIGGER_RATIO = 0.7
    DEFAULT_MAX_CONTEXT_CHARS = 400_000

    def __init__(self, db: AsyncSession):
        self.db = db

    def get_max_context_chars(self, agent_llm_config: Optional[Dict] = None) -> int:
        if agent_llm_config and "max_context_tokens" in agent_llm_config:
            return int(agent_llm_config["max_context_tokens"]) * 4
        return self.DEFAULT_MAX_CONTEXT_CHARS

    async def get_chain_history_chars(self, chain_id: str) -> int:
        chain_ids = [chain_id]
        sub_chain_result = await self.db.execute(
            select(Chain.id)
            .where(and_(Chain.parent_chain_id == chain_id, Chain.deleted_at.is_(None)))
        )
        chain_ids.extend([row[0] for row in sub_chain_result.all()])

        result = await self.db.execute(
            select(func.coalesce(func.sum(func.length(Packet.content)), 0))
            .where(Packet.chain_id.in_(chain_ids))
            .where(Packet.deleted_at.is_(None))
        )
        return int(result.scalar() or 0)

    async def should_rollover(self, chain_id: str, agent_llm_config: Optional[Dict] = None) -> bool:
        max_chars = self.get_max_context_chars(agent_llm_config)
        current_chars = await self.get_chain_history_chars(chain_id)
        return current_chars >= int(max_chars * self.TRIGGER_RATIO)

    async def execute_rollover(
        self,
        chain: Chain,
        agent_name: str = "system",
        agent_llm_config: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        packets = await self._load_chain_packets(chain.id)
        if not packets:
            return {"new_chain_id": chain.id, "summary": "", "old_chain_id": chain.id}

        summary = await self._generate_summary(packets, agent_name, agent_llm_config)

        chain.status = "completed"
        chain.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

        new_chain = Chain(
            task_id=chain.task_id,
            group_id=chain.group_id,
            status="active",
            chain_type=chain.chain_type,
            parent_chain_id=chain.parent_chain_id,
            rollover_from_chain_id=chain.id,
            rollover_summary=summary,
        )
        self.db.add(new_chain)
        await self.db.flush()

        return {
            "new_chain_id": new_chain.id,
            "summary": summary,
            "old_chain_id": chain.id,
        }

    async def _load_chain_packets(self, chain_id: str) -> List[Packet]:
        chain_ids = [chain_id]
        sub_chain_result = await self.db.execute(
            select(Chain.id)
            .where(and_(Chain.parent_chain_id == chain_id, Chain.deleted_at.is_(None)))
        )
        chain_ids.extend([row[0] for row in sub_chain_result.all()])

        result = await self.db.execute(
            select(Packet)
            .where(Packet.chain_id.in_(chain_ids))
            .where(Packet.deleted_at.is_(None))
            .order_by(Packet.created_at.asc())
        )
        return list(result.scalars().all())

    async def _generate_summary(
        self,
        packets: List[Packet],
        agent_name: str,
        agent_llm_config: Optional[Dict] = None,
    ) -> str:
        transcript_lines = []
        for pkt in packets:
            if pkt.packet_type == "user_input":
                transcript_lines.append(f"用户: {pkt.content}")
            elif pkt.packet_type == "agent_text":
                clean = self._strip_think_blocks(pkt.content)
                if clean:
                    transcript_lines.append(f"{pkt.sender_name}: {clean}")
            elif pkt.packet_type == "system":
                transcript_lines.append(f"系统: {pkt.content}")
        transcript = "\n".join(transcript_lines)

        max_transcript_chars = 50_000
        if len(transcript) > max_transcript_chars:
            transcript = transcript[-max_transcript_chars:]

        summary_prompt = (
            f"你正在为 {agent_name} 做对话交接总结。\n"
            f"请总结当前对话的需求、进度和关键决策，以便在新对话中继续工作。\n"
            f"要求：\n"
            f"1. 概述用户的核心需求\n"
            f"2. 列出已完成的工作\n"
            f"3. 列出待完成的工作\n"
            f"4. 记录关键决策和约束\n"
            f"5. 简洁明了，不超过500字"
        )

        try:
            summary = await self._call_llm_for_summary(
                system_prompt=summary_prompt,
                transcript=transcript,
                agent_llm_config=agent_llm_config,
            )
            if summary and summary.strip():
                return summary.strip()
        except Exception:
            pass

        return f"[自动摘要] 对话历史过长，以下是最近内容：\n{transcript[-2000:]}"

    async def _call_llm_for_summary(
        self,
        system_prompt: str,
        transcript: str,
        agent_llm_config: Optional[Dict] = None,
    ) -> str:
        from openai import AsyncOpenAI

        api_key = settings.get_llm_api_key()
        api_base = settings.get_llm_api_base()
        model = (agent_llm_config or {}).get("model") or settings.DEFAULT_LLM_MODEL

        if not api_key:
            raise RuntimeError("LLM API Key 未配置")

        client = AsyncOpenAI(api_key=api_key, base_url=api_base)

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        return response.choices[0].message.content or ""

    async def query_chain_memory(
        self,
        chain_id: str,
        question: str,
        agent_name: str = "system",
        agent_llm_config: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        result = await self.db.execute(
            select(Chain)
            .where(Chain.id == chain_id)
            .where(Chain.deleted_at.is_(None))
        )
        chain = result.scalar_one_or_none()
        if not chain:
            return {"chain_id": chain_id, "question": question, "answer": f"链 {chain_id} 不存在"}

        packets = await self._load_chain_packets(chain_id)

        context_parts = []
        if chain.rollover_summary:
            context_parts.append(f"[前链总结]\n{chain.rollover_summary}")
            if chain.rollover_from_chain_id:
                context_parts.append(f"(来源链ID: {chain.rollover_from_chain_id})")

        for pkt in packets:
            if pkt.packet_type == "user_input":
                context_parts.append(f"用户: {pkt.content}")
            elif pkt.packet_type == "agent_text":
                clean = self._strip_think_blocks(pkt.content)
                if clean:
                    context_parts.append(f"{pkt.sender_name}: {clean}")

        context_text = "\n".join(context_parts)

        max_chars = 50_000
        if len(context_text) > max_chars:
            context_text = context_text[-max_chars:]

        answer_prompt = (
            f"你正在帮助 {agent_name} 查询历史对话记忆。\n"
            f"以下是链 {chain_id} 的对话记录，请根据这些内容回答问题。\n"
            f"如果信息不足，请如实说明。\n\n"
            f"问题：{question}"
        )

        try:
            answer = await self._call_llm_for_summary(
                system_prompt=answer_prompt,
                transcript=context_text,
                agent_llm_config=agent_llm_config,
            )
            if answer and answer.strip():
                return {"chain_id": chain_id, "question": question, "answer": answer.strip()}
        except Exception:
            pass

        recent = context_text[-3000:] if len(context_text) > 3000 else context_text
        return {
            "chain_id": chain_id,
            "question": question,
            "answer": f"[降级模式] 无法调用LLM，以下是链的最近内容：\n{recent}",
        }

    @staticmethod
    def _strip_think_blocks(content: str) -> str:
        sanitized = re.sub(r"思考.*?回答", "", content, flags=re.DOTALL | re.IGNORECASE)
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
        return sanitized.strip()
