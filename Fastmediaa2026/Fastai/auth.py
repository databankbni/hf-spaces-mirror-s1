import pandas as pd
import gradio as gr
from safety_guard import get_allowed_models_list

CSV_FILE = "users.csv"


def login_user(username, password):
    users = pd.read_csv(
        CSV_FILE,
        dtype=str,
        encoding="utf-8-sig"
    )

    users.columns = users.columns.str.strip()

    user = users[
        (users["اسم المستخدم"].str.strip() == username.strip()) &
        (users["كلمة المرور"].str.strip() == password.strip())
    ]

    if user.empty:
        return (
            "❌ بيانات الدخول غير صحيحة",
            gr.update(visible=False),
            None,
            gr.update(choices=[])
        )

    allowed_models = get_allowed_models_list(
        user.iloc[0]["النماذج المسموحة"]
    )

    user_data = {
        "username": username
    }

    return (
        "✅ تم تسجيل الدخول",
        gr.update(visible=True),
        user_data,
        gr.update(choices=allowed_models)
    )