import gradio as gr
from PIL import Image
import io

def process_uploaded_file(file, prompt):
    """معالجة الملف المرفوع (صورة أو فيديو)"""
    if file is None:
        return prompt, None
    
    try:
        if file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            # معالجة الصور
            img = Image.open(file.name)
            # يمكن إضافة تحسينات هنا (resize, etc.)
            return f"{prompt}\n\n[صورة مرفوعة: {file.name.split('/')[-1]}]", img
        else:
            return f"{prompt}\n\n[ملف مرفوع: {file.name.split('/')[-1]}]", None
    except Exception as e:
        return f"{prompt}\n\n[خطأ في معالجة الملف: {str(e)}]", None

def create_media_interface():
    """واجهة معالجة الميديا المنفصلة"""
    with gr.Blocks() as media_demo:
        gr.Markdown("## 🎥 Media Handler")
        
        with gr.Row():
            with gr.Column(scale=2):
                prompt = gr.Textbox(label="الوصف", lines=3, placeholder="اكتب وصف المحتوى...")
                file_input = gr.File(label="رفع صورة أو ملف")
                preview = gr.Image(label="المعاينة", height=300)
            
            with gr.Column(scale=1):
                quality = gr.Radio(["720p", "1080p", "4K"], value="1080p", label="الجودة")
                duration = gr.Radio(["4s", "6s", "8s"], value="4s", label="المدة")
                model = gr.Dropdown(["gpt-4o", "Gemini 1.5 Pro"], value="gpt-4o", label="النموذج")
                generate_btn = gr.Button("إنشاء", variant="primary")
        
        output = gr.Textbox(label="النتيجة", lines=8)
        
        file_input.change(
            lambda f: f, 
            inputs=file_input, 
            outputs=preview
        )
        
        generate_btn.click(
            process_uploaded_file,
            inputs=[file_input, prompt],
            outputs=[output, preview]  # يمكن تعديل حسب الحاجة
        )
    
    return media_demo

# للاختبار المستقل
if __name__ == "__main__":
    create_media_interface().launch()