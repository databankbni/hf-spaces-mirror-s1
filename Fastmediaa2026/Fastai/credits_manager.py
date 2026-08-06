import pandas as pd
import math

CSV_FILE = "users.csv"


def get_user_credit(username):
    users = pd.read_csv(CSV_FILE, dtype=str)

    user = users[users["اسم المستخدم"].str.strip() == username.strip()]

    if user.empty:
        return 0

    return int(user.iloc[0]["رصيد_الكريدت"])


def deduct_credit(username, total_tokens):
    users = pd.read_csv(CSV_FILE, dtype=str)

    index = users[
        users["اسم المستخدم"].str.strip() == username.strip()
    ].index

    if len(index) == 0:
        return 0

    row = index[0]

    current_credit = int(users.loc[row, "رصيد_الكريدت"])

    credits_used = math.ceil(total_tokens / 500)

    current_credit -= credits_used

    if current_credit < 0:
        current_credit = 0

    users.loc[row, "رصيد_الكريدت"] = current_credit

    users.to_csv(CSV_FILE, index=False)

    return {
    "remaining_credit": current_credit,
    "credits_used": credits_used,
    "total_tokens": total_tokens
}