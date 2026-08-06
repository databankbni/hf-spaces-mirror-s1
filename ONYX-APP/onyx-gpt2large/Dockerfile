# استخدام إصدار 3.11 لتفادي تحذيرات جوجل وللتوافقية
FROM python:3.11

WORKDIR /code

# ننسخ ملف المتطلبات أولاً لتحسين الـ Caching
COPY ./requirements.txt /code/requirements.txt

# تنصيب المكتبات الأساسية
# ملاحظة: استخدمنا --extra-index-url لجلب نسخة llama-cpp-python جاهزة (Wheels) 
# وهذا بيمنع استهلاك الرام العالي أثناء الـ Build (حل مشكلة Exit Code 137)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/charts

# نسخ باقي ملفات المشروع
COPY . .

# تشغيل FastAPI باستخدام uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]