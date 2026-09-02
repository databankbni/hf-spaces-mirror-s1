# P29 Global Content Pipeline

كل الأقسام (Blogger / News / Sports / مستقبلًا) تستخدم نفس البوابة قبل أي AI/API:

1. Empty check
2. Global + channel blocked-word check
3. Duplicate check
4. Normalize + fingerprint
5. AI processing (single package request where applicable)
6. Post-AI blocked-word + duplicate check
7. Queue / publish

المحتوى المرفوض في المرحلتين الأولى أو الثانية لا يستهلك أي طلب AI.

## Single AI Request

قسم Blogger يستخدم `SYSTEM_ARTICLE_PACKAGE` لطلب حزمة واحدة تشمل العنوان، النص، الملخص، SEO، الكلمات، الهاشتاكات، الملاحظات، الاستخراج وALT بدل عدة طلبات مستقلة.

## Extensibility

`core/content_pipeline.py` مستقل عن Blogger، لذلك أي Plugin جديد يستطيع استخدام `ContentGate` بدون نسخ منطق الحظر/التكرار.
