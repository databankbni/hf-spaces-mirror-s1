import os
from hanlp_restful import HanLPClient
from config import HANLP_SECRET_NAME

HanLP = HanLPClient(
    "https://www.hanlp.com/api",
    auth=os.environ[HANLP_SECRET_NAME],
    language="zh"
)


def analyze_essay(text):
    text = str(text).strip()
    if not text:
        return [], [], []

    doc = HanLP(text, tasks=["tok/fine", "pos/ctb", "dep"])

    tokens_sents = doc["tok/fine"]
    pos_sents = doc["pos/ctb"]
    dep_sents = doc["dep"]

    pos_items = []
    dep_items = []
    grammar_items = []

    for sent_id, (tokens, pos_tags, deps) in enumerate(
        zip(tokens_sents, pos_sents, dep_sents),
        start=1
    ):
        # POS
        for word_id, (word, pos) in enumerate(zip(tokens, pos_tags), start=1):
            pos_items.append({
                "sentence_id": sent_id,
                "word_id": word_id,
                "word": word,
                "pos": pos,
            })

        # DEP
        for word_id, (word, pos, dep_item) in enumerate(
            zip(tokens, pos_tags, deps),
            start=1
        ):
            head_id, relation = dep_item
            relation = str(relation).strip()

            if head_id == 0:
                head_word = "ROOT"
            elif 1 <= head_id <= len(tokens):
                head_word = tokens[head_id - 1]
            else:
                head_word = ""

            dep_items.append({
                "sentence_id": sent_id,
                "word_id": word_id,
                "word": word,
                "pos": pos,
                "head_id": head_id,
                "head_word": head_word,
                "relation": relation,
            })

            # Grammar extraction
            if "rcomp" in relation:
                grammar_items.append({
                    "sentence_id": sent_id,
                    "grammar_type": "rcomp",
                    "head_word": head_word,
                    "dep_word": word,
                    "expression": f"{head_word}{word}",
                    "note": "结果补语",
                })

            elif relation == "ba" or relation.endswith(":ba"):
                grammar_items.append({
                    "sentence_id": sent_id,
                    "grammar_type": "ba",
                    "head_word": head_word,
                    "dep_word": word,
                    "expression": f"{word} → {head_word}",
                    "note": "把字句",
                })

            elif relation == "pass" or relation.endswith(":pass"):
                grammar_items.append({
                    "sentence_id": sent_id,
                    "grammar_type": "pass",
                    "head_word": head_word,
                    "dep_word": word,
                    "expression": f"{word} → {head_word}",
                    "note": "被字句",
                })

    return pos_items, dep_items, grammar_items