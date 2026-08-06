import pandas as pd
from datetime import datetime

CSV_FILE = "users.csv"


def get_subscription_info(username):
    """
    يرجع بيانات اشتراك المستخدم كاملة
    """

    try:
        users = pd.read_csv(CSV_FILE, encoding="utf-8-sig")

        users["اسم المستخدم"] = users["اسم المستخدم"].astype(str).str.strip()

        username = str(username).strip()

        user = users[
            users["اسم المستخدم"] == username
        ]

        if user.empty:
            return None

        user = user.iloc[0]

        expiry = pd.to_datetime(
            user["تاريخ الانتهاء"]
        ).date()

        today = datetime.now().date()

        remaining = (expiry - today).days

        return {
            "username": user["اسم المستخدم"],
            "package": user["نوع الباقة"],
            "start": user["تاريخ البداية"],
            "expiry": user["تاريخ الانتهاء"],
            "status": user["الحالة"],
            "remaining_days": remaining
        }

    except Exception as e:
        print(e)
        return None