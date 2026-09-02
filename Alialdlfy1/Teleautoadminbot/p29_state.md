# حالة P29 — محدثة

## الإنجازات
- patch prepare-ahead في scheduler.py (p28) مكتمل ويُظهر في السجل: "prepared in advance, will publish at its fixed time" ثم نشر عند الوقت الثابت.
- 133/133 وحدة OK، 13/13 سيناريو P28، 13/13 P27، py_compile OK.

## مشكلة harness run_p29_verify.py
- _cycle يعيد None وليس tuple — run_cycles يستخدم `res or (False,"")` → كل دورة "منشورة" تُعد 0 → assertEqual(sum(r[0]),1) تفشل حتى مع النشر الناجح (السجل يؤكد النشر fp_a3، fp_x، fp_s1، fp_p1، fp_c1...).
- الإصلاح المطلوب: في run_cycles استبدل `results.append(res or (False, ""))` بعدّ النجاح عبر pub.posts: عُدّ المنشورات قبل/بعد الدورة (len(self.pub.posts) delta) واستخدمه كـ r[0]. الأسهل: اجعل run_cycles يعيد (عدد منشورات جديدة، "published") لكل دورة.
- ملاحظة أخرى: mock publisher.posts يحتوي (chat_id, fp) — V1 expects pub.posts[0][1]==fp_a3 ✓
- env loop set MIDDLE_CHANNEL="99" (يجب أن يكون truthy) ✓ يعمل الآن.

## خطوات متبقية
1. تعديل run_cycles في run_p29_verify.py لعدّ المنشورات الجديدة (delta len(pub.posts)).
2. إعادة تشغيل: python3 run_p29_verify.py — توقع نجاح V1,V2,V3,V4,V5,V6,V7.
3. إعادة حزمة الملفات: zip يشمل scheduler.py المحدّث + database.py + prompts.py + processor.py من p28/modules/blogger → /home/ubuntu/p28_blogger_modules.zip (تحديث).
4. التقرير العربي النهائي (A-F): البند الوحيد المنفذ فعليًا في هذه المرحلة هو prepare-ahead (prepare candidate قبل وقت slot ثم تثبيته عند الوقت)؛ الباقي كان مُنفذًا مسبقًا في P28 ويتم التحقق منه الآن عبر run_p29_verify.py.
5. تسليم: التقرير + zip + run_p29_verify.py + نتائج 133 + 13+13.
