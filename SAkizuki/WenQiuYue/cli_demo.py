"""
cli_demo.py
────────────
命令行对话 demo。多轮对话，输入 exit/quit 退出。

API Key 加载优先级（高 → 低）：
  1. 环境变量（DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL / TAVILY_API_KEY）
  2. pipeline_config.yaml 中的 api 字段

用法：
  python cli_demo.py
  python cli_demo.py --verbose
  python cli_demo.py --debug
  python cli_demo.py --config data_pipeline/pipeline_config.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
import yaml
from pathlib import Path


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_api_config() -> tuple[str, str, str, str | None]:
    """返回 (deepseek_api_key, base_url, model, tavily_api_key)，全部从环境变量获取。"""
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url     = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model        = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    tavily_key   = os.environ.get("TAVILY_API_KEY") or None
    return deepseek_key, base_url, model, tavily_key


def print_sources(sources: list[dict]):
    if not sources:
        return
    seen = set()
    print("\n来源：")
    for s in sources:
        url = s.get("url", "")
        if url and url not in seen:
            seen.add(url)
            title = s.get("title", url)
            print(f"  · [{title}]({url})")
    print()


def main():
    parser = argparse.ArgumentParser(description="问秋月 CLI Demo")
    parser.add_argument(
        "--config",
        default="pipeline_config.yaml",
        help="pipeline 配置文件路径",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--debug", "-d", action="store_true")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"[ERROR] 配置文件不存在: {cfg_path}", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(cfg_path)
    project_root = cfg_path.resolve().parent

    # ── API 配置 ──────────────────────────────────────────────────────
    deepseek_key, base_url, model, tavily_key = resolve_api_config()

    if not deepseek_key:
        print(
            "[ERROR] DeepSeek API Key 未配置。请设置环境变量 DEEPSEEK_API_KEY。",
            file=sys.stderr,
        )
        sys.exit(1)

    if not tavily_key:
        print("[WARN] Tavily API Key 未配置，网络搜索功能已禁用。", file=sys.stderr)

    # ── 检索器配置 ────────────────────────────────────────────────────
    chroma_dir      = project_root / cfg.get("chroma_dir", ".chroma")
    model_path      = cfg.get("model_path", "BAAI/bge-m3")
    collection_name = cfg.get("collection_name", "akizuki_blog")
    score_threshold = 0.4
    max_seq_length  = cfg.get("embedding", {}).get("max_seq_length", 512)

    print("初始化检索器...", file=sys.stderr)
    from core.retriever import Retriever
    retriever = Retriever(
        chroma_dir=chroma_dir,
        model_path=model_path,
        collection_name=collection_name,
        score_threshold=score_threshold,
        max_seq_length=max_seq_length,
    )

    from core.agent import Agent
    agent = Agent(
        retriever=retriever,
        deepseek_api_key=deepseek_key,
        base_url=base_url,
        model=model,
        tavily_api_key=tavily_key,
        verbose=args.verbose,
        debug=args.debug,
    )

    print("\n" + "=" * 60)
    print("  问秋月 · 博客知识库问答")
    print("  exit/quit 退出  |  clear 清空历史  |  Ctrl-C 中断")
    print("=" * 60 + "\n")

    history: list[dict] = []

    while True:
        try:
            user_input = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见喵！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("再见喵！")
            break
        if user_input.lower() == "clear":
            history = []
            print("[对话历史已清空]\n")
            continue

        print("思考中...", end="\r", flush=True)

        try:
            result = agent.chat(user_input, history=history)
        except Exception as e:
            print(f"\n[ERROR] {e}")
            continue

        print_sources(result["sources"])

        history.append({"role": "user",      "content": user_input})
        history.append({"role": "assistant", "content": result["answer"]})
        if len(history) > 20:
            history = history[-20:]


if __name__ == "__main__":
    main()