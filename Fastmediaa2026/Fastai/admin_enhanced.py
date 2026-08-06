import os
import gradio as gr
import pandas as pd

CSV_FILE = "users.csv"

COLUMNS = [
    "ID",
    "اسم المستخدم",
    "كلمة المرور",
    "النماذج المسموحة",
    "رصيد_الكريدت",
    "إجمالي_الكريدت",
    "التوكنات_لكل_كريدت"
]


def load_users():
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(
                CSV_FILE,
                encoding="utf-8-sig"
            )
        except:
            df = pd.read_csv(CSV_FILE)
    else:
        df = pd.DataFrame(columns=COLUMNS)
        df.to_csv(
            CSV_FILE,
            index=False,
            encoding="utf-8-sig"
        )

    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[COLUMNS]


users_db = load_users()


def save_users_file():
    global users_db
    users_db.to_csv(
        CSV_FILE,
        index=False,
        encoding="utf-8-sig"
    )


def refresh_users():
    return users_db


def save_user(
    username,
    password,
    models,
    credit,
    tokens_per_credit
):
    global users_db

    username = str(username).strip()
    password = str(password).strip()

    if not username or not password:
        return refresh_users(), "❌ أدخل اسم المستخدم وكلمة المرور"

    if username in users_db["اسم المستخدم"].astype(str).values:
        return refresh_users(), "❌ المستخدم موجود بالفعل"

    new_id = (
        int(users_db["ID"].max()) + 1
        if not users_db.empty
        else 1
    )

    credit = int(credit)
    tokens_per_credit = int(tokens_per_credit)

    new_user = pd.DataFrame([{
        "ID": new_id,
        "اسم المستخدم": username,
        "كلمة المرور": password,
        "النماذج المسموحة": ", ".join(models),
        "رصيد_الكريدت": credit,
        "إجمالي_الكريدت": credit,
        "التوكنات_لكل_كريدت": tokens_per_credit
    }])

    users_db = pd.concat(
        [users_db, new_user],
        ignore_index=True
    )

    save_users_file()

    return refresh_users(), f"✅ تم إنشاء المستخدم {username}"


def update_user(
    user_id,
    username,
    password,
    models,
    credit
):
    global users_db

    idx = users_db[
        users_db["ID"] == int(user_id)
    ].index

    if len(idx) == 0:
        return refresh_users(), "❌ المستخدم غير موجود"

    users_db.loc[
        idx,
        [
            "اسم المستخدم",
            "كلمة المرور",
            "النماذج المسموحة",
            "رصيد_الكريدت"
        ]
    ] = [
        username,
        password,
        ", ".join(models),
        int(credit)
    ]

    save_users_file()

    return refresh_users(), "✅ تم التحديث"


def delete_user(user_id):
    global users_db

    users_db = users_db[
        users_db["ID"] != int(user_id)
    ].reset_index(drop=True)

    save_users_file()

    return refresh_users(), "🗑️ تم حذف المستخدم"


def create_enhanced_admin_ui():

    with gr.Blocks(
        title="لوحة إدارة الكريدت"
    ) as demo:

        gr.Markdown(
            "# 🔐 لوحة إدارة المستخدمين - نظام الكريدت"
        )

        table = gr.Dataframe(
            value=refresh_users(),
            headers=COLUMNS,
            interactive=False
        )

        msg = gr.Textbox(
            label="الحالة"
        )


        with gr.Tab(
            "➕ إضافة مستخدم"
        ):

            u = gr.Textbox(
                label="اسم المستخدم"
            )

            p = gr.Textbox(
                label="كلمة المرور"
            )

            models = gr.CheckboxGroup(
                choices=[
                    "gpt-4o",
                    "gpt-4o-mini",
                    "Gemini"
                ],
                label="النماذج المسموحة"
            )

            credit = gr.Number(
                label="رصيد الكريدت",
                value=10000
            )

            tokens = gr.Number(
                label="عدد التوكنات لكل كريدت",
                value=500
            )

            add_btn = gr.Button(
                "إنشاء المستخدم",
                variant="primary"
            )

            add_btn.click(
                save_user,
                [
                    u,
                    p,
                    models,
                    credit,
                    tokens
                ],
                [
                    table,
                    msg
                ]
            )


        with gr.Tab(
            "✏️ تعديل مستخدم"
        ):

            uid = gr.Number(
                label="ID المستخدم"
            )

            u2 = gr.Textbox(
                label="اسم المستخدم"
            )

            p2 = gr.Textbox(
                label="كلمة المرور"
            )

            models2 = gr.CheckboxGroup(
                choices=[
                    "gpt-4o",
                    "gpt-4o-mini",
                    "Gemini"
                ],
                label="النماذج المسموحة"
            )

            credit2 = gr.Number(
                label="رصيد الكريدت الجديد"
            )

            update_btn = gr.Button(
                "تحديث",
                variant="primary"
            )

            update_btn.click(
                update_user,
                [
                    uid,
                    u2,
                    p2,
                    models2,
                    credit2
                ],
                [
                    table,
                    msg
                ]
            )


        with gr.Tab(
            "🗑 حذف مستخدم"
        ):

            delete_id = gr.Number(
                label="ID المستخدم"
            )

            delete_btn = gr.Button(
                "حذف",
                variant="stop"
            )

            delete_btn.click(
                delete_user,
                delete_id,
                [
                    table,
                    msg
                ]
            )

    return demo


if __name__ == "__main__":
    app = create_enhanced_admin_ui()
    app.launch()