import gradio as gr
from subscription_ui import (
    extend_user_subscription,
    stop_subscription,
    activate_subscription
)


def create_subscription_widgets(user_table):

    gr.Markdown("## 💳 إدارة الاشتراكات")

    with gr.Row():

        user_id = gr.Number(
            label="ID المستخدم",
            precision=0
        )

        days = gr.Dropdown(
            choices=[30, 90, 180, 365],
            value=30,
            label="مدة التمديد"
        )

    with gr.Row():

        extend_btn = gr.Button(
            "➕ تمديد الاشتراك",
            variant="primary"
        )

        stop_btn = gr.Button(
            "⛔ إيقاف الحساب",
            variant="stop"
        )

        activate_btn = gr.Button(
            "✅ إعادة التفعيل"
        )

    result = gr.Textbox(
        label="النتيجة"
    )

    extend_btn.click(
        extend_user_subscription,
        inputs=[user_id, days],
        outputs=[user_table, result]
    )

    stop_btn.click(
        stop_subscription,
        inputs=[user_id],
        outputs=[user_table, result]
    )

    activate_btn.click(
        activate_subscription,
        inputs=[user_id],
        outputs=[user_table, result]
    )