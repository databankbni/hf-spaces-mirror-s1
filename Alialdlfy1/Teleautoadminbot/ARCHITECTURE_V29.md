# P29 Refactor Architecture

## هدف
إعادة الهيكلة تدريجيًا بدون كسر السلوك الحالي، مع إبقاء وحدات `modules/` متاحة أثناء الترحيل.

## الطبقات
- `core/`: بنية تحتية مستقرة: jobs, health, secrets, plugins, events, supervisor, repair, storage.
- `adapters/`: محولات للخدمات الخارجية مثل Telegram/Gemini/Groq/Blogger.
- `modules/`: التنفيذ الحالي؛ يتم ترحيل وظيفة بعد أخرى إلى الخدمات الجديدة.
- `tests/`: اختبارات التوافق والانحدار.

## قواعد مهمة
1. لا تعديل مباشر على الإنتاج بواسطة AI.
2. AI يقترح Patch -> Sandbox -> compile/tests/security -> backup -> apply -> monitor -> rollback.
3. الأسرار لا تدخل logs ولا source code.
4. كل job قابل للاستعادة بعد restart.
5. كل provider قابل للفشل دون إسقاط التطبيق كله.
6. إضافة secret/provider/plugin جديد تتم بالـ registry/metadata وليس بتعديل الـ core.

## خارطة الترحيل
1. JobStore + Health + Supervisor.
2. SecretManager + ProviderRouter.
3. نقل Blogger scheduler إلى jobs.
4. نقل database JSON إلى SQLite عبر adapter ثم إيقاف JSON بعد فترة تحقق.
5. تقسيم `bot_core.py` إلى handlers/services.
6. تفعيل Auto-Repair بعد اكتمال الاختبارات.

## التوافق
النسخة الحالية لا تحذف `bot_core.py` ولا وحدات Blogger؛ هذا مقصود لتقليل خطر الانقطاع أثناء الترحيل.
