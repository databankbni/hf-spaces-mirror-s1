import gradio as gr
import pandas as pd
import os
from datetime import datetime, timedelta

CSV_FILE = "users.csv"

columns = [
    "ID",
    "اسم المستخدم",
    "كلمة المرور",
    "البريد الإلكتروني",
    "تاريخ الانتهاء",
    "النماذج المسموحة",
    "الحالة"
]


def load_users():
    if os.path.exists(CSV_FILE):
        return pd.read_csv(CSV_FILE)

    df = pd.DataFrame(columns=columns)
    df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    return df


users_db = load_users()


def save_csv():
    users_db.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")


def save_user(name, password, email, expiry_days, models):
    global users_db

    if str(name).strip() == "" or str(password).strip() == "":
        return users_db, "❌ أدخل اسم المستخدم وكلمة المرور"

    new_id = 1 if len(users_db) == 0 else users_db["ID"].max() + 1

    expiry = (
        datetime.now() + timedelta(days=int(expiry_days))
    ).strftime("%Y-%m-%d")

    new_row = pd.DataFrame({
        "ID": [new_id],
        "اسم المستخدم": [name],
        "كلمة المرور": [password],
        "البريد الإلكتروني": [email],
        "تاريخ الانتهاء": [expiry],
        "النماذج المسموحة": [", ".join(models)],
        "الحالة": ["نشط"]
    })

    users_db = pd.concat([users_db, new_row], ignore_index=True)

    save_csv()

    return users_db, "✅ تم إضافة المستخدم بنجاح"


def update_user(user_id, name, password, email, expiry, models):
    global users_db

    idx = users_db[users_db["ID"] == int(user_id)].index

    if len(idx) == 0:
        return users_db, "❌ المستخدم غير موجود"

    i = idx[0]

    users_db.at[i, "اسم المستخدم"] = name
    users_db.at[i, "كلمة المرور"] = password
    users_db.at[i, "البريد الإلكتروني"] = email
    users_db.at[i, "تاريخ الانتهاء"] = expiry
    users_db.at[i, "النماذج المسموحة"] = models

    save_csv()

    return users_db, "✅ تم التعديل بنجاح"


def delete_user(user_id):
    global users_db

    users_db = users_db[
        users_db["ID"] != int(user_id)
    ].reset_index(drop=True)

    save_csv()

    return users_db, "🗑️ تم حذف المستخدم"


def create_advanced_admin_ui():

    with gr.Column():

        gr.Markdown("# 👥 إدارة المستخدمين")

        with gr.TabItem("➕ إضافة مستخدم"):

            name = gr.Textbox(label="اسم المستخدم")

            password = gr.Textbox(
                label="كلمة المرور",
                type="password"
            )

            email = gr.Textbox(label="البريد الإلكتروني")

            expiry = gr.Number(
                label="مدة الاشتراك بالأيام",
                value=30
            )

            # استبدل الـ 4 خيارات القدام بهذا الكود فقط
models_selection = gr.CheckboxGroup(
    choices=["gpt-4o", "gpt-4o-mini"], 
    label="النماذج المتاحة للعميل"
)
                ],
                value=["gpt-4o"]
            )

            add_btn = gr.Button("إضافة")

            status = gr.Textbox(label="الحالة")

        table = gr.Dataframe(
            value=users_db,
            interactive=False
        )

        gr.Markdown("## ✏️ تعديل مستخدم")

        user_id = gr.Number(label="ID")

        edit_name = gr.Textbox(label="اسم المستخدم")

        edit_password = gr.Textbox(
            label="كلمة المرور",
            type="password"
        )

        edit_email = gr.Textbox(label="البريد الإلكتروني")

        edit_expiry = gr.Textbox(
            label="تاريخ الانتهاء YYYY-MM-DD"
        )

        edit_models = gr.Textbox(
            label="النماذج"
        )

        update_btn = gr.Button("حفظ التعديل")

        update_status = gr.Textbox()

        delete_btn = gr.Button("حذف المستخدم")

        delete_status = gr.Textbox()

        add_btn.click(
            save_user,
            [name, password, email, expiry, models],
            [table, status]
        )

        update_btn.click(
            update_user,
            [
                user_id,
                edit_name,
                edit_password,
                edit_email,
                edit_expiry,
                edit_models
            ],
            [table, update_status]
        )

        delete_btn.click(
            delete_user,
            [user_id],
            [table, delete_status]
        )

    return gr.Markdown("تم تحميل لوحة الإدارة")


if __name__ == "__main__":
    with gr.Blocks() as demo:
        create_advanced_admin_ui()

    demo.launch()