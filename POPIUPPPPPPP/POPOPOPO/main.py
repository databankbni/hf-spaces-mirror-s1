#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בדיקת תקינות אוטומטית לכל מפתחות ה-API של Gemini.
פשוט מריצים: python3 check_all_gemini_keys.py
לא צריך להדביק כלום - הכל כבר בפנים.
"""

import json
import time
import urllib.request
import urllib.error

# שנה כאן את המודל אם צריך (למשל אם gemini-2.0-flash גם לא זמין)
MODEL = "gemini-2.0-flash"

KEYS = [
    "AQ.Ab8RN6Iked3sp7LugEzyDPMCqBHr4CI6YIPnwoI5H9zL7hBbkg",
    "AQ.Ab8RN6IG4uBPWcziGLq8fnkVDI_lpnyK6mX22K5Q28pZ-LvDxg",
    "AQ.Ab8RN6IgljlrHBsuhov2snQIOaGl3Kt63zGitaOJeLrvZ5jrYA",
    "AQ.Ab8RN6KKLKGj7XLnJousANP4CLt_SUv8pJZ40XxmQgGxaqKy0g",
    "AQ.Ab8RN6KaCwaTtpbiL7lviSZ3nmxm1O9Yk5dNIq3m8ee0VYGjqw",
    "AQ.Ab8RN6Ko_NsGtypMQOBK9napXjebKG9ekJefzkRDMnOb2ch83g",
    "AQ.Ab8RN6L1-vbsoUMIDnZOO9ZWFawFboa5NHjtHInqCS4B3ckDPg",
    "AQ.Ab8RN6JX2eGbOyZ2g3ZuyMWHpIpwIcX8rQywel_wnLdBxNtPLw",
    "AQ.Ab8RN6JHSn1TzDwKkzeIjo5fee-Vg9HXHdFGizGkzfcPX-pdpw",
    "AQ.Ab8RN6KMgzV1GgvolPbf8ahuh2QUYEtnEbPF_nHmg2nnvAp5Zg",
    "AQ.Ab8RN6I4ZJR-LyyR8eU0NselTScxEp_Yi-DW95fMa-LhC4dXzw",
    "AQ.Ab8RN6KsaIdEXVgIVjoQqd22ftGHWGdWCoprAIdsowa-54St4w",
    "AQ.Ab8RN6KoOyvIoP4w4NC9AACrEdYF123TQFcGFI5yY2Q454tPlA",
    "AQ.Ab8RN6IA8EFkg1eszBj4dOGEDlh4AaEz42dKI5hKGQrZ8grLTQ",
    "AQ.Ab8RN6Lp8PJoK26i_-ZGL2cMHtt6X5FLMahwR-2-HatvM4CSFg",
    "AQ.Ab8RN6J_J3gqBcCGaMybCNneIqeVBY6TvU6WtWk8O3R8N4xNGA",
    "AQ.Ab8RN6JFcdkf2_zsxny_W2CaELMurO0WSmF5F3z2n0KrKXIIIw",
    "AQ.Ab8RN6JR8z4t_Hfevu99wGyqDIHWqwIuqQx0S298DHzhyVTFFQ",
    "AQ.Ab8RN6KWD77aC6_-IpkTemQBYx5ieK4lbFg_YQomINWttAEmsw",
    "AQ.Ab8RN6J5X1Dwpdwv1gKmD1K3mqxYOhyTabvfwRtN8zPNxpbBbA",
    "AQ.Ab8RN6J5X1Dwpdwv1gKmD1K3mqxYOhyTabvfwRtN8lbAPNx",
    "AQ.Ab8RN6JARdrzB1hBDTlulso0zZXa5FWOJ0zSOj-FYNepgnoTAQ",
    "AQ.Ab8RN6Jkne4kIQvDAL7wL72LnpCGsV2Au51cqggyMxNfUQU5Vw",
    "AQ.Ab8RN6IoiMrTIDFu8nVq3pyDNAm_s-OnuLlRAEbsK1cmqjLYTQ",
    "AQ.Ab8RN6Iry330mMsCI3V_QvBrCghSmOf2O6ZyVvhQ8-TORQr7-g",
    "AQ.Ab8RN6I6k1r8MxTsBW0lZqjgAdleOwELMQWI-NkJ_gdsp0PdhQ",
    "AQ.Ab8RN6JzjmIiL9M4yT13BKlyV0wPOwtfp1urV55qv3cSz77t9A",
    "AQ.Ab8RN6KRWEMQJ-frZdFJGSwu9xyO1Ch37zm4czphuHrDPbBGog",
    "AQ.Ab8RN6JZ_dix8yZaeqhIilm-My8D2y3azKT115ZFPMlzLnaRcA",
    "AQ.Ab8RN6IWzUryavQHIUyO1tCiZmAn5HP6FHE12T_-7CfAeX10yA",
    "AQ.Ab8RN6IHEVG9Qppqzl9Ug4ECRNxuUGUh1g4As-40tEWJ6UlYiQ",
    "AQ.Ab8RN6IgDQu95SOoeNPelzSpRXr92q82-rE96ccx0NikYVeAAA",
    "AQ.Ab8RN6LUWxnezUcEcRNN8lIgxcVx4LQ2KEzTTEsdXwE23R01Jg",
    "AQ.Ab8RN6IM09ooz-98mvR5CIPm2g7kj5s3VbqF2LnQkQ6y7TyXqA",
    "AQ.Ab8RN6KPfkM2QtW-548tBJwInkL0wm3nqO5sYac-_FXalGHiHQ",
    "AQ.Ab8RN6Kwurgo7coae_EmYFTnqTYKiRbAIg0I6zxTQPiJeIpxSQ",
    "AQ.Ab8RN6IPqnlZ1rR06GVKvXlkqVifXaw2FX-zwAu_3h7SXg-V8g",
    "AQ.Ab8RN6INO3U9E8W0DO3gXxZ4S4hCSyfUEggOHOT0UfyChRVWUw",
    "AQ.Ab8RN6J6CKrqaZ7Xl-tD6UjMx8R2hMtcsk6EB4nkNrXUd8YE4w",
    "AQ.Ab8RN6LWJ-WFvIXdDV7WnEMauM_6XcrwFidZNpFFzUvva29J7Q",
    "AQ.Ab8RN6J7epClk7iRIrhTjTHCt7hlYI5B8KLb2nDwVDbs36POBA",
    "AQ.Ab8RN6KFkO36kPFZpkNoaAeyWvwezaEG84E0l4L3L-VWl5ahtA",
]

URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def check_key(key: str) -> str:
    """שולח בקשה קטנה ומחזיר קטגוריית תוצאה בעברית."""
    url = URL_TMPL.format(model=MODEL, key=key)
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": "בדיקה"}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 5},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
            return "OK", "✅ תקין ועובד"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        if "CONSUMER_SUSPENDED" in body:
            return "SUSPENDED", "☠️ מושעה לצמיתות (CONSUMER_SUSPENDED)"
        if "UNAUTHENTICATED" in body:
            return "UNAUTH", "❌ לא מזוהה כלל (401 UNAUTHENTICATED)"
        if "no longer available" in body:
            return "MODEL_GONE", f"❌ המודל {MODEL} הוצא משימוש (לא בעיה במפתח)"
        if "PERMISSION_DENIED" in body:
            return "PERM_DENIED", "⚠️ הרשאה נדחתה (403)"
        if "RESOURCE_EXHAUSTED" in body:
            return "RATE_LIMIT", "⏳ תקין, אבל חריגת מכסה כרגע (429)"
        return "OTHER", f"❓ סטטוס {e.code} - {body[:150]}"
    except urllib.error.URLError as e:
        return "NETERR", f"🌐 שגיאת רשת: {e.reason}"
    except Exception as e:
        return "OTHER", f"❓ שגיאה לא צפויה: {e}"


def main():
    print(f"בודק {len(KEYS)} מפתחות מול המודל {MODEL}...\n")
    counts = {}
    for i, key in enumerate(KEYS, start=1):
        short = f"{key[:18]}...{key[-6:]}"
        category, message = check_key(key)
        counts[category] = counts.get(category, 0) + 1
        print(f"[{i:2d}/{len(KEYS)}] {short} -> {message}")
        time.sleep(0.3)  # לא להציף את גוגל בבת אחת

    print("\n===== סיכום =====")
    labels = {
        "OK": "✅ תקינים",
        "SUSPENDED": "☠️ מושעים לצמיתות",
        "UNAUTH": "❌ לא מזוהים (401)",
        "MODEL_GONE": "❌ מודל לא זמין (לא קשור למפתח)",
        "PERM_DENIED": "⚠️ הרשאה נדחתה (403)",
        "RATE_LIMIT": "⏳ חריגת מכסה (429)",
        "NETERR": "🌐 שגיאת רשת",
        "OTHER": "❓ אחר/לא ברור",
    }
    for key, label in labels.items():
        if key in counts:
            print(f"{label}: {counts[key]}")
    print(f"סה\"כ נבדקו: {len(KEYS)}")


if __name__ == "__main__":
    main()