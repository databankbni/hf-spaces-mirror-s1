import gradio as gr

def create_admin_ui():
    with gr.Column():
        gr.Markdown("## 🔧 لوحة التحكم الإدارية")
        gr.Markdown("هنا يمكنك إدارة الإعدادات، المستخدمين، والإحصائيات.")
        
        with gr.Row():
            gr.Button("تحديث النماذج", variant="primary")
            gr.Button("عرض السجلات")
            gr.Button("إعدادات API")
        
        gr.Textbox(
            label="إحصائيات سريعة", 
            value="عدد الطلبات اليوم: 245\nالنماذج المستخدمة: gpt-4o\nآخر نشاط: قبل 5 دقائق",
            lines=6
        )