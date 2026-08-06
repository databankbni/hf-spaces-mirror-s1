import gradio as gr
import pandas as pd
from datetime import datetime
from safety_guard import get_allowed_models_list, check_model_access
import os
import traceback
from services import get_openai_response, get_gemini_response
from video_generator import create_video_ui
from subscription_info import get_subscription_info

CSV_FILE = "users.csv"
import math

def get_user_credit(username):
    users = pd.read_csv(CSV_FILE, dtype=str)
    users.columns = users.columns.str.strip()

    user = users[
        users["اسم المستخدم"].str.strip() == username.strip()
    ]

    if user.empty:
        return 0, 500

    credit = int(user.iloc[0]["رصيد_الكريدت"])
    tokens_per_credit = int(user.iloc[0]["التوكنات_لكل_كريدت"])

    return credit, tokens_per_credit


def save_user_credit(username, new_credit):
    users = pd.read_csv(CSV_FILE, dtype=str)
    users.columns = users.columns.str.strip()

    index = users[
        users["اسم المستخدم"].str.strip() == username.strip()
    ].index

    if len(index) == 0:
        return

    users.loc[index[0], "رصيد_الكريدت"] = str(new_credit)

    users.to_csv(CSV_FILE, index=False)
def login_user(username, password):
    try:
        users = pd.read_csv(CSV_FILE, dtype=str)
        users.columns = users.columns.str.strip()

        user = users[
            (users["اسم المستخدم"].str.strip() == username.strip()) &
            (users["كلمة المرور"].str.strip() == password.strip())
        ]

        if user.empty:
            return "❌ خطأ في البيانات", gr.update(visible=False), None, gr.update()

        allowed_models_str = user.iloc[0].get(
            "النماذج المسموحة",
            "gpt-4o-mini"
        )

        allowed_list = get_allowed_models_list(
            allowed_models_str
        )

        credit = user.iloc[0]["رصيد_الكريدت"]

        return (
            f"✅ تم تسجيل الدخول | 💳 رصيدك: {credit} كريدت",
            gr.update(visible=True),
            {
                "username": username,
                "credit": credit
            },
            gr.update(
                choices=allowed_list,
                value=allowed_list[0]
            )
        )

    except Exception as e:
        return f"❌ خطأ: {str(e)}", gr.update(visible=False), None, gr.update()

def general_chat_logic(message, history, model, user_data):
    if history is None:
        history = []

    history.append({
        "role": "user",
        "content": message
    })

    try:
        username = user_data["username"]

        # فحص الرصيد قبل الإرسال
        credit, tokens_per_credit = get_user_credit(username)

        if credit <= 0:
            response = "❌ رصيدك انتهى، يرجى شحن الكريدت."

        else:
            if "Gemini" in model:
                result = get_gemini_response(message, username)
            else:
                result = get_openai_response(
                    message,
                    username,
                    model
                )

            response = result["content"]
            total_tokens = result.get(
                "total_tokens",
                0
            )

            # حساب الخصم
            used_credit = math.ceil(
                total_tokens / tokens_per_credit
            )

            new_credit = credit - used_credit

            if new_credit < 0:
                new_credit = 0

            save_user_credit(
                username,
                new_credit
            )

            response += (
                f"\n\n💳 الرصيد المتبقي: {new_credit} كريدت"
            )

    except Exception as e:
        response = f"❌ خطأ: {str(e)}"

    history.append({
        "role": "assistant",
        "content": response
    })

    return "", history

def create_enhanced_user_ui():
    dashboard_state = gr.State()
    with gr.Column():
        gr.Markdown("# 🔐 تسجيل الدخول")
        username = gr.Textbox(label="اسم المستخدم")
        password = gr.Textbox(label="كلمة المرور", type="password")
        login_btn = gr.Button("تسجيل الدخول", variant="primary")
        login_status = gr.Textbox(label="الحالة")

        with gr.Column(visible=False) as app_content:
            gr.Markdown("# 🚀 Fast Media AI")
            with gr.Tabs():
                with gr.TabItem("💬 شات عام"):
                    model_dropdown = gr.Dropdown(choices=[], label="اختر النموذج")
                    prompt = gr.Textbox(label="اكتب رسالتك", lines=3)
                    chatbot = gr.Chatbot(label="المحادثة", height=450)
                    send_btn = gr.Button("إرسال", variant="primary")
                    send_btn.click(
    general_chat_logic,
    [
        prompt,
        chatbot,
        model_dropdown,
        dashboard_state
    ],
    [
        prompt,
        chatbot
    ]
)

                with gr.TabItem("🎬 إنشاء فيديو"):
                    create_video_ui()

                with gr.TabItem("🖼️ إنشاء صور"):
                    image_prompt = gr.Textbox(label="وصف الصورة", lines=4)
                    image_model = gr.Dropdown(choices=["DALL·E 3", "Flux.1", "Ideogram v2", "Stable Diffusion 3"], value="DALL·E 3", label="النموذج")
                    generate_image_btn = gr.Button("🖼️ توليد الصورة")
                    image_output = gr.Image(label="الصورة الناتجة")
                    generate_image_btn.click(lambda x: None, image_prompt, image_output)

        login_btn.click(login_user, [username, password], [login_status, app_content, dashboard_state, model_dropdown])
    return app_content

if __name__ == "__main__":
    with gr.Blocks(theme=gr.themes.Soft(primary_hue="orange")) as demo:
        create_enhanced_user_ui()
    demo.launch()