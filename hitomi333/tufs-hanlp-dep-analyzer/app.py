import time
import traceback
from datetime import datetime

import gradio as gr

from google_utils import (
    read_essays,
    clear_analysis_sheets,
    append_pos_rows,
    append_dep_rows,
    append_grammar_rows,
)
from hanlp_utils import analyze_essay


def check_essay():
    try:
        essays = read_essays()
        if not essays:
            return "Essay 中没有读取到作文。请确认表头是否有「作文原文」。"

        sample = essays[0]
        return (
            f"✅ 读取成功\n\n"
            f"作文数量：{len(essays)}\n\n"
            f"第一篇：\n"
            f"课：{sample['lesson']}\n"
            f"学习者编号：{sample['learner_id']}\n"
            f"作文ID：{sample['essay_id']}\n\n"
            f"作文开头：{sample['essay_text'][:150]}"
        )

    except Exception:
        return "❌ 出错：\n\n" + traceback.format_exc()


def analyze_one_essay(index=0):
    essays = read_essays()
    if not essays:
        return "Essay 中没有读取到作文。"

    if index >= len(essays):
        return f"作文序号超出范围。当前作文数量：{len(essays)}"

    essay = essays[index]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    pos_items, dep_items, grammar_items = analyze_essay(essay["essay_text"])

    pos_rows = []
    dep_rows = []
    grammar_rows = []

    for item in pos_items:
        pos_rows.append([
            now,
            essay["lesson"],
            essay["learner_id"],
            essay["essay_id"],
            item["sentence_id"],
            item["word_id"],
            item["word"],
            item["pos"],
        ])

    for item in dep_items:
        dep_rows.append([
            now,
            essay["lesson"],
            essay["learner_id"],
            essay["essay_id"],
            item["sentence_id"],
            item["word_id"],
            item["word"],
            item["pos"],
            item["head_id"],
            item["head_word"],
            item["relation"],
        ])

    for item in grammar_items:
        grammar_rows.append([
            now,
            essay["lesson"],
            essay["learner_id"],
            essay["essay_id"],
            item["sentence_id"],
            item["grammar_type"],
            item["head_word"],
            item["dep_word"],
            item["expression"],
            item["note"],
        ])

    append_pos_rows(pos_rows)
    append_dep_rows(dep_rows)
    append_grammar_rows(grammar_rows)

    return (
        f"✅ 分析完成\n\n"
        f"作文ID：{essay['essay_id']}\n"
        f"课：{essay['lesson']}\n"
        f"学习者编号：{essay['learner_id']}\n\n"
        f"POS 写入行数：{len(pos_rows)}\n"
        f"DEP 写入行数：{len(dep_rows)}\n"
        f"Grammar 写入行数：{len(grammar_rows)}\n\n"
        f"rcomp 数量：{sum(1 for x in grammar_items if x['grammar_type'] == 'rcomp')}\n"
        f"ba 数量：{sum(1 for x in grammar_items if x['grammar_type'] == 'ba')}\n"
        f"pass 数量：{sum(1 for x in grammar_items if x['grammar_type'] == 'pass')}"
    )


def analyze_first():
    try:
        clear_analysis_sheets()
        return analyze_one_essay(0)
    except Exception:
        return "❌ 出错：\n\n" + traceback.format_exc()


def analyze_all_with_wait():
    try:
        essays = read_essays()
        if not essays:
            return "Essay 中没有读取到作文。"

        clear_analysis_sheets()

        results = []
        total_pos = 0
        total_dep = 0
        total_grammar = 0

        for i, essay in enumerate(essays):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pos_items, dep_items, grammar_items = analyze_essay(essay["essay_text"])

            pos_rows = [
                [
                    now,
                    essay["lesson"],
                    essay["learner_id"],
                    essay["essay_id"],
                    item["sentence_id"],
                    item["word_id"],
                    item["word"],
                    item["pos"],
                ]
                for item in pos_items
            ]

            dep_rows = [
                [
                    now,
                    essay["lesson"],
                    essay["learner_id"],
                    essay["essay_id"],
                    item["sentence_id"],
                    item["word_id"],
                    item["word"],
                    item["pos"],
                    item["head_id"],
                    item["head_word"],
                    item["relation"],
                ]
                for item in dep_items
            ]

            grammar_rows = [
                [
                    now,
                    essay["lesson"],
                    essay["learner_id"],
                    essay["essay_id"],
                    item["sentence_id"],
                    item["grammar_type"],
                    item["head_word"],
                    item["dep_word"],
                    item["expression"],
                    item["note"],
                ]
                for item in grammar_items
            ]

            append_pos_rows(pos_rows)
            append_dep_rows(dep_rows)
            append_grammar_rows(grammar_rows)

            total_pos += len(pos_rows)
            total_dep += len(dep_rows)
            total_grammar += len(grammar_rows)

            results.append(
                f"{i+1}/{len(essays)} 完成：{essay['essay_id']} "
                f"POS={len(pos_rows)}, DEP={len(dep_rows)}, Grammar={len(grammar_rows)}"
            )

            # HanLP 免费API额度有限，等待避免 429
            if i < len(essays) - 1:
                time.sleep(20)

        return (
            "✅ 全部分析完成\n\n"
            f"作文数量：{len(essays)}\n"
            f"POS 总行数：{total_pos}\n"
            f"DEP 总行数：{total_dep}\n"
            f"Grammar 总行数：{total_grammar}\n\n"
            + "\n".join(results[-20:])
        )

    except Exception:
        return "❌ 出错：\n\n" + traceback.format_exc()


with gr.Blocks() as demo:
    gr.Markdown("# TUFS HanLP DEP Analyzer")
    gr.Markdown("Version 2：Essay → POS / DEP / Grammar")

    with gr.Row():
        check_btn = gr.Button("① 测试读取 Essay")
        first_btn = gr.Button("② 分析第一篇作文")
        all_btn = gr.Button("③ 分析全部作文（每篇等待20秒）")

    output = gr.Textbox(label="运行结果", lines=25)

    check_btn.click(check_essay, outputs=output)
    first_btn.click(analyze_first, outputs=output)
    all_btn.click(analyze_all_with_wait, outputs=output)

demo.launch()