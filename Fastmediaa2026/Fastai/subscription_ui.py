import gradio as gr
import pandas as pd

from subscription_manager import (
    extend_subscription,
    get_subscription_status
)

CSV_FILE = "users.csv"


def extend_user_subscription(user_id, days):

    try:
        users = pd.read_csv(CSV_FILE, encoding="utf-8-sig")

        idx = users[users["ID"] == int(user_id)].index

        if len(idx) == 0:
            return users, "❌ المستخدم غير موجود"

        i = idx[0]

        current_expiry = users.loc[i, "تاريخ الانتهاء"]

        new_expiry = extend_subscription(
            current_expiry,
            days
        )

        users.loc[i, "تاريخ الانتهاء"] = new_expiry

        users.loc[i, "الحالة"] = get_subscription_status(
            new_expiry
        )

        users.to_csv(
            CSV_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        return (
            users,
            f"✅ تم تمديد الاشتراك حتى {new_expiry}"
        )

    except Exception as e:
        return None, f"❌ {e}"


def stop_subscription(user_id):

    try:
        users = pd.read_csv(CSV_FILE, encoding="utf-8-sig")

        idx = users[users["ID"] == int(user_id)].index

        if len(idx) == 0:
            return users, "❌ المستخدم غير موجود"

        users.loc[idx, "الحالة"] = "موقوف"

        users.to_csv(
            CSV_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        return users, "⛔ تم إيقاف الحساب"

    except Exception as e:
        return None, str(e)


def activate_subscription(user_id):

    try:
        users = pd.read_csv(CSV_FILE, encoding="utf-8-sig")

        idx = users[users["ID"] == int(user_id)].index

        if len(idx) == 0:
            return users, "❌ المستخدم غير موجود"

        expiry = users.loc[idx[0], "تاريخ الانتهاء"]

        users.loc[idx, "الحالة"] = get_subscription_status(
            expiry
        )

        users.to_csv(
            CSV_FILE,
            index=False,
            encoding="utf-8-sig"
        )

        return users, "✅ تم تفعيل الحساب"

    except Exception as e:
        return None, str(e)