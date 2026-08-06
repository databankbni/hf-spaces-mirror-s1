import os
import asyncio
import json
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from gradio_client import Client

app = FastAPI(title="ONYX Engine")

# تهيئة عميل Gradio للاتصال بـ qwen-onnx-chat مع التوكن الصحيح
client = Client("ONYX-APP/qwen-onnx-chat", token=os.getenv("HF_TOKEN"))

@app.get("/")
async def root():
    return {"status": "ONYX Engine is running", "model": "google/gemma-4-E2B-it"}

@app.post("/predict")
async def generate(request: Request):
    data = await request.json()
    messages = data.get("messages", [])
    
    # 1. استخراج الـ system_prompt الأساسي، وتجميع باقي الرسائل
    system_prompt = ""
    filtered_chat = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            if system_prompt:
                system_prompt += "\n" + content
            else:
                system_prompt = content
        else:
            filtered_chat.append(msg)
                
    # 2. تحديد رسالة المستخدم الأخيرة وتاريخ المحادثة وقبلهما
    user_message = ""
    history_msgs = []
    if filtered_chat:
        user_message = filtered_chat[-1].get("content", "")
        history_msgs = filtered_chat[:-1]
                    
    # 3. بناء الـ history بشكل أزواج متتالية [ [user, assistant], [user, assistant], ... ]
    history = []
    i = 0
    while i < len(history_msgs):
        if history_msgs[i].get("role") == "user":
            u_content = history_msgs[i].get("content", "")
            a_content = ""
            if i + 1 < len(history_msgs) and history_msgs[i+1].get("role") == "assistant":
                a_content = history_msgs[i+1].get("content", "")
                i += 1
            history.append([u_content, a_content])
        i += 1

    async def generate_chunks():
        try:
            def run_client():
                # [تعديل] تمرير المعاملات بالترتيب (Positional) حصراً لأن السبيس لا يدعم الـ keyword arguments
                return client.predict(
                    user_message,
                    history,
                    system_prompt
                )
                                    
            response_text = await asyncio.to_thread(run_client)
                                    
            # إرسال النص الناتج على دفعات متتالية لتوافق الـ StreamingResponse
            for char in str(response_text):
                yield char
                await asyncio.sleep(0.01)
                                
        except Exception as e:
            yield f" بعتذر منك بس فيك تشغل التطبيق بكرة لانو المودل الاساسي قيد التطوير "

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(generate_chunks(), headers=headers)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)