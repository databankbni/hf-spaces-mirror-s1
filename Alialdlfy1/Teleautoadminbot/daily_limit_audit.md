## التدقيق الأولي لعداد النشر اليومي

النسخة المفحوصة: `/home/ubuntu/p28`، ونسخة `bot_latest_release` تحتوي نفس منطق Blogger في الملفات ذات الصلة.

### مسارات التحكم الفعلية

- عداد النشر: `modules/blogger/database.py::increment_daily_count(section)`، يُستدعى بعد نجاح Blogger من `modules/blogger/scheduler.py` في المسارين generic وfixed slots.
- قراءة العداد: `modules/blogger/scheduler.py::_today_published_count()` يقرأ `db.get_stats()['daily'][today]`.
- فترة الحساب الحالية: مفتاح تقويمي واحد بصيغة `%Y-%m-%d` من `datetime.now().date()` في scheduler، بينما الزيادة تستخدم `time.strftime('%Y-%m-%d')` في database؛ ليست نافذة rolling لآخر 24 ساعة.
- نطاق العداد: حسب `section`، والحد يؤخذ من إعداد القناة المرتبط بالقسم؛ لا يوجد حساب مركزي لمقالات المدونة خلال 24 ساعة.
- الطابور: `BloggerScheduler._queue`، ويُحمّل من `db.get_articles_by_status('queued')`; اختيار generic هو `queue[0]`، واختيار وظائف fixed-slot هو `_slot_candidates()` بالأحدث حسب Telegram message id.
- تحديث الحالة: `db.update_article_status()` يغير الحالة في `articles` فقط، ولا يزيل من الطابور الذاكراتي.
- إزالة من الطابور: generic يحذف المقال من `_queue` حتى عند فشل `publish_article`؛ fixed-slot يحذف المقال أيضًا عند الفشل. هذا يخالف شرط الإبقاء عند فشل النشر.
- النجاح: عند نجاح النشر فقط يُكتب status=`published` ويُزاد daily count؛ عند الفشل تُكتب status=`failed` ولا يُزاد العداد، لكن الإزالة الحالية تمنع retry.
- منع تجاوز الحد: المقارنة `section_today >= daily_limit` قبل generic publish وقبل fixed-slot publish.

### سبب الاختلاف المؤكد قبل الإصلاح

العداد الداخلي لا يمثل «المقالات الظاهرة في Blogger خلال آخر 24 ساعة». إنه عداد تراكم يوم تقويمي محلي/بيئي حسب القسم، ويزاد فقط بعد نجاح المسار الذي يمر عبر scheduler. لذلك أي مقارنة بواجهة المدونة لآخر 24 ساعة أو بإجمالي منشورات كل الأقسام ليست مقارنة لنفس المجموعة الزمنية/النطاق. كما أن وقت الزيادة في database ووقت القراءة في scheduler يستخدمان طريقتين مختلفتين (`time.strftime` مقابل `datetime.now`)، ما قد يسبب اختلاف يوم عند حدود منتصف الليل/المنطقة الزمنية.

### خلل سلوكي مستقل مؤكد

المقال يُزال من `_queue` بعد فشل النشر في المسارين generic وfixed-slot، رغم أن المطلوب إبقاؤه حتى نجاح فعلي. هذا إصلاح مباشر داخل scheduler فقط.

### حالة التعديل السابق

تعديل P29 الخاص بالتجهيز المسبق موجود فعلًا في `scheduler.py` (`prepared in advance` و`candidates` للـslot القادم). لا يوجد منطق rolling 24-hour count في النسخة الحالية.
