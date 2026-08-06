import gradio as gr
from services import get_openai_response, get_gemini_response

def chat_logic(message, history, model):
    if history is None:
        history = []
    
    # تحويل التنسيق القديم إلى الجديد إذا وجد
    if history and isinstance(history[0], list) if history else False:
        new_history = []
        for turn in history:
            if len(turn) > 0 and turn[0]:
                new_history.append({"role": "user", "content": turn[0]})
            if len(turn) > 1 and turn[1]:
                new_history.append({"role": "assistant", "content": turn[1]})
        history = new_history

    # إضافة رسالة المستخدم
    history.append({"role": "user", "content": message})
    
    try:
        if model == "Gemini 1.5 Pro":
            response = get_gemini_response(message)
        else:
            response = get_openai_response(message, model)
    except Exception as e:
        response = f"خطأ: {str(e)}"
    
    # إضافة رد النموذج
    history.append({"role": "assistant", "content": response})
    
    return "", history

def create_user_ui():
    with gr.Column():
        gr.Markdown("# 🚀 Fast Media AI")
        
        with gr.Row():
            model = gr.Dropdown(
                choices=["gpt-4o", "gpt-4o-mini", "Gemini 1.5 Pro"], 
                value="gpt-4o", 
                label="اختر النموذج"
            )
        
        prompt = gr.Textbox(
            label="وصف طلبك", 
            placeholder="اكتب ما تريد إنشاءه...",
            lines=3
        )
        
        upload = gr.File(label="رفع صورة أو ملف")
        
        with gr.Row():
            quality = gr.Radio(["720p", "1080p", "4K"], value="1080p", label="الجودة")
            duration = gr.Radio(["4s", "6s", "8s"], value="4s", label="المدة")
        
        chatbot = gr.Chatbot(label="النتائج", height=400)
        
        generate_btn = gr.Button("✨ إنشاء", variant="primary")
        
        generate_btn.click(
            chat_logic, 
            inputs=[prompt, chatbot, model], 
            outputs=[prompt, chatbot]
        )