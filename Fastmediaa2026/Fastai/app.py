import gradio as gr
print("APP FILE LOADED")

# فك الكومنت عن السطور دي لما تخلص تجربة إن الموقع فتح
from auth import login_user
from enhanced_user_ui import create_enhanced_user_ui
from admin_enhanced import create_enhanced_admin_ui

print("APP STARTED")
ADMIN_USERNAME = "Ahmed"
ADMIN_PASSWORD = "Mamalolo"

def admin_login(username, password):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return "✅ تم تسجيل دخول الأدمن", gr.update(visible=True)
    return "❌ بيانات الأدمن غير صحيحة", gr.update(visible=False)

with gr.Blocks(theme=gr.themes.Soft(primary_hue="orange")) as demo:
    try:
        gr.Image("logo.jpg", width=200, show_label=False)
    except:
        gr.Markdown("# 🚀 Fast Media AI")

    with gr.Tabs():
        # =====================
        # دخول المستخدم
        # =====================
        with gr.TabItem("👤 دخول المستخدم"):
            create_enhanced_user_ui()

        # =====================
        # دخول الإدارة
        # =====================
        with gr.TabItem("🔧 دخول الإدارة"):
            gr.Markdown("## 🔐 تسجيل دخول الأدمن")
            admin_username = gr.Textbox(label="اسم المستخدم")
            admin_password = gr.Textbox(label="كلمة المرور", type="password")
            admin_login_btn = gr.Button("تسجيل الدخول", variant="primary")
            admin_status = gr.Textbox(label="الحالة")
            
            with gr.Column(visible=False) as admin_panel:
                create_enhanced_admin_ui()

            admin_login_btn.click(
                admin_login,
                [admin_username, admin_password],
                [admin_status, admin_panel]
            )

if __name__ == "__main__":
    print("BEFORE LAUNCH")
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
    print("AFTER LAUNCH")