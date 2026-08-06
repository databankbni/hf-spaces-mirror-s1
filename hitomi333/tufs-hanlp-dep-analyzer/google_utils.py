import os
import json
import gspread
from google.oauth2.service_account import Credentials

from config import (
    SPREADSHEET_NAME,
    ESSAY_SHEET,
    POS_SHEET,
    DEP_SHEET,
    GRAMMAR_SHEET,
    GOOGLE_SECRET_NAME,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

POS_HEADERS = [
    "时间", "课", "学习者编号", "作文ID",
    "句子编号", "词序号", "词", "POS"
]

DEP_HEADERS = [
    "时间", "课", "学习者编号", "作文ID",
    "句子编号", "词序号", "词", "POS",
    "Head序号", "Head词", "依存关系"
]

GRAMMAR_HEADERS = [
    "时间", "课", "学习者编号", "作文ID",
    "句子编号", "语法类型",
    "中心词", "依存词", "表达式", "说明"
]


def get_spreadsheet():
    info = json.loads(os.environ[GOOGLE_SECRET_NAME])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open(SPREADSHEET_NAME)


def get_or_create_worksheet(sheet_name, headers):
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))

    first_row = ws.row_values(1)
    if first_row != headers:
        ws.clear()
        ws.append_row(headers)

    return ws


def read_essays():
    ws = get_spreadsheet().worksheet(ESSAY_SHEET)
    rows = ws.get_all_records()

    essays = []
    for i, row in enumerate(rows, start=2):
        text = row.get("作文原文") or row.get("作文") or row.get("原文") or ""
        if not str(text).strip():
            continue

        essays.append({
            "row_number": i,
            "essay_id": f"row_{i}",
            "time": row.get("时间", ""),
            "lesson": row.get("课", ""),
            "learner_id": row.get("学习者编号", ""),
            "essay_text": str(text).strip(),
        })

    return essays


def clear_analysis_sheets():
    for sheet_name, headers in [
        (POS_SHEET, POS_HEADERS),
        (DEP_SHEET, DEP_HEADERS),
        (GRAMMAR_SHEET, GRAMMAR_HEADERS),
    ]:
        ws = get_or_create_worksheet(sheet_name, headers)
        ws.clear()
        ws.append_row(headers)


def append_pos_rows(rows):
    ws = get_or_create_worksheet(POS_SHEET, POS_HEADERS)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)


def append_dep_rows(rows):
    ws = get_or_create_worksheet(DEP_SHEET, DEP_HEADERS)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)


def append_grammar_rows(rows):
    ws = get_or_create_worksheet(GRAMMAR_SHEET, GRAMMAR_HEADERS)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)