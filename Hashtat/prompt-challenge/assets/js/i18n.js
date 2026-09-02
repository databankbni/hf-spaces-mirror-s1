// ---------------- i18n ----------------
const I18N_STORAGE_KEY = "promptChallenge.lang";

const I18N = {
  en: {
    brand: "Prompt Challenge",
    nav_challenges: "Challenges",
    nav_progress: "Progress",
    nav_about: "About",
    hero_title: "Learn to Prompt.<br>One Challenge at a Time.",
    hero_sub: "Practice writing prompts, get instant feedback, and learn what makes AI understand you better.",
    btn_start_challenge: "Start Challenge",
    btn_random_challenge: "Try a Random Challenge",
    benefit1_title: "Practice with real tasks",
    benefit1_body: "Every challenge is a task you'll actually use AI for — emails, images, plans, and more.",
    benefit2_title: "Get instant AI feedback",
    benefit2_body: "See exactly what your prompt is missing, in plain language — no jargon required.",
    benefit3_title: "Improve your prompting skills",
    benefit3_body: "Try again, track your scores, and build a habit that makes every AI tool work better for you.",
    no_challenges: "No challenges available right now.",
    loading_challenge: "Loading a challenge…",
    prompt_label: "Your prompt",
    prompt_placeholder: "Write your prompt here…",
    btn_evaluate: "Evaluate My Prompt",
    btn_hint: "Give Me a Hint",
    btn_new_challenge: "New Challenge",
    hint_title: "Hint",
    evaluating_text: "Reading your prompt and preparing feedback…",
    btn_try_again: "Try Again",
    score_out_of: "/ 100",
    what_you_did_well: "What you did well",
    whats_missing: "What's missing",
    try_improving: "Try improving",
    btn_show_example: "Show Me an Example",
    btn_next_challenge: "Next Challenge",
    your_prompt: "Your prompt",
    stronger_example: "Example of a stronger prompt",
    why_better: "Why it's better",
    your_progress: "Your Progress",
    no_attempts_yet: "You haven't completed any challenges yet.",
    btn_start_first: "Start Your First Challenge",
    stat_challenges: "Challenges",
    stat_average: "Average Score",
    stat_best: "Best Score",
    stat_streak: "Current Streak",
    categories_practiced: "Categories Practiced",
    recent_attempts: "Recent Attempts",
    about_title: "About Prompt Challenge",
    about_p1: "Prompt Challenge is a beginner-friendly way to practice writing prompts for AI tools. You don't need any prior knowledge of prompt engineering — just pick a challenge, write your best attempt, and get instant, friendly feedback.",
    about_p2: "Every challenge is based on something people actually use AI for: writing emails, generating images, planning a trip, describing a product, and more. Instead of handing you a perfect prompt, we explain why certain details make a prompt work better, so the skill sticks with you.",
    about_loop: "Challenge → Write Prompt → Get Score → Understand What's Missing → Improve → Try Again → Master the Skill",
    about_p3: "Your progress is saved locally in your browser, so you can track your average score, best score, and streak over time.",
    challenge_number: (n) => `CHALLENGE #${String(n).padStart(2, "0")}`,
    no_more_hints: "No more hints — you've got everything you need. Give it your best shot!",
    write_prompt_alert: "Write a prompt before evaluating.",
    category_names: {
      text: "Text", image: "Image", video: "Video", business: "Business", general: "General AI",
    },
    difficulty_names: {
      beginner: "Beginner", intermediate: "Intermediate", challenge: "Challenge",
    },
    empty_strengths: "Keep going — your next attempt will show more strengths here.",
    empty_missing: "Nothing major missing — nice work!",
    empty_suggestions: "Try adding more detail next time.",
    level_names: {
      "Excellent": "Excellent",
      "Strong": "Strong",
      "Good Start": "Good Start",
      "Needs More Detail": "Needs More Detail",
      "Let's Build It Together": "Let's Build It Together",
    },
  },
  ar: {
    brand: "تحدي البرومبت",
    nav_challenges: "التحديات",
    nav_progress: "التقدم",
    nav_about: "حول",
    hero_title: "تعلّم كتابة البرومبت.<br>تحدٍ واحد في كل مرة.",
    hero_sub: "تدرّب على كتابة البرومبت، واحصل على تقييم فوري، وتعلّم ما الذي يجعل الذكاء الاصطناعي يفهمك بشكل أفضل.",
    btn_start_challenge: "ابدأ التحدي",
    btn_random_challenge: "جرّب تحدياً عشوائياً",
    benefit1_title: "تدرّب على مهام حقيقية",
    benefit1_body: "كل تحدٍ هو مهمة ستستخدم فيها الذكاء الاصطناعي فعلياً — رسائل، صور، خطط، وأكثر.",
    benefit2_title: "احصل على تقييم فوري",
    benefit2_body: "شاهد بالضبط ما الذي ينقص برومبتك، بلغة بسيطة دون مصطلحات معقدة.",
    benefit3_title: "طوّر مهاراتك في كتابة البرومبت",
    benefit3_body: "أعد المحاولة، وتابع نتائجك، وابنِ عادة تجعل كل أداة ذكاء اصطناعي تعمل بشكل أفضل من أجلك.",
    no_challenges: "لا توجد تحديات متاحة حالياً.",
    loading_challenge: "جارٍ تحميل تحدٍ…",
    prompt_label: "برومبتك",
    prompt_placeholder: "اكتب برومبتك هنا…",
    btn_evaluate: "قيّم برومبتي",
    btn_hint: "أعطني تلميحاً",
    btn_new_challenge: "تحدٍ جديد",
    hint_title: "تلميح",
    evaluating_text: "جارٍ قراءة برومبتك وتحضير التقييم…",
    btn_try_again: "أعد المحاولة",
    score_out_of: "/ 100",
    what_you_did_well: "ما الذي أحسنت فيه",
    whats_missing: "ما الذي ينقص",
    try_improving: "حاول التحسين",
    btn_show_example: "أرني مثالاً",
    btn_next_challenge: "التحدي التالي",
    your_prompt: "برومبتك",
    stronger_example: "مثال على برومبت أقوى",
    why_better: "لماذا هو أفضل",
    your_progress: "تقدّمك",
    no_attempts_yet: "لم تكمل أي تحديات بعد.",
    btn_start_first: "ابدأ تحديك الأول",
    stat_challenges: "التحديات",
    stat_average: "متوسط النتيجة",
    stat_best: "أفضل نتيجة",
    stat_streak: "السلسلة الحالية",
    categories_practiced: "التصنيفات التي تدربت عليها",
    recent_attempts: "المحاولات الأخيرة",
    about_title: "حول تحدي البرومبت",
    about_p1: "تحدي البرومبت هو وسيلة سهلة للمبتدئين للتدرب على كتابة البرومبت لأدوات الذكاء الاصطناعي. لست بحاجة لأي معرفة مسبقة بهندسة البرومبت — فقط اختر تحدياً، واكتب أفضل محاولة لديك، واحصل على تقييم فوري وودود.",
    about_p2: "كل تحدٍ مبني على شيء يستخدمه الناس فعلياً مع الذكاء الاصطناعي: كتابة الرسائل، توليد الصور، تخطيط رحلة، وصف منتج، وأكثر. بدلاً من إعطائك برومبتاً مثالياً جاهزاً، نشرح لك لماذا تجعل تفاصيل معينة البرومبت أفضل، لتبقى المهارة معك.",
    about_loop: "التحدي ← اكتب البرومبت ← احصل على النتيجة ← افهم ما ينقص ← حسّن ← أعد المحاولة ← أتقن المهارة",
    about_p3: "يُحفظ تقدّمك محلياً في متصفحك، حتى تتمكن من متابعة متوسط نتيجتك وأفضل نتيجة وسلسلة محاولاتك مع مرور الوقت.",
    challenge_number: (n) => `التحدي رقم ${String(n).padStart(2, "0")}`,
    no_more_hints: "لا مزيد من التلميحات — لديك كل ما تحتاجه. حاول الآن بأفضل ما لديك!",
    write_prompt_alert: "اكتب برومبتاً قبل التقييم.",
    category_names: {
      text: "نصوص", image: "صور", video: "فيديو", business: "أعمال", general: "ذكاء اصطناعي عام",
    },
    difficulty_names: {
      beginner: "مبتدئ", intermediate: "متوسط", challenge: "تحدٍ",
    },
    empty_strengths: "استمر — محاولتك القادمة ستُظهر نقاط قوة أكثر هنا.",
    empty_missing: "لا شيء أساسي ينقص — عمل رائع!",
    empty_suggestions: "حاول إضافة المزيد من التفاصيل في المرة القادمة.",
    level_names: {
      "Excellent": "ممتاز",
      "Strong": "قوي",
      "Good Start": "بداية جيدة",
      "Needs More Detail": "يحتاج تفاصيل أكثر",
      "Let's Build It Together": "لنبنِها معاً",
    },
  },
};

function getLang() {
  return localStorage.getItem(I18N_STORAGE_KEY) === "ar" ? "ar" : "en";
}

function t(key) {
  const dict = I18N[getLang()];
  return (dict && dict[key] !== undefined) ? dict[key] : (I18N.en[key] ?? key);
}

function applyStaticTranslations() {
  const lang = getLang();
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const value = t(key);
    if (typeof value === "string") el.innerHTML = value;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });

  const toggleBtn = document.getElementById("btn-lang-toggle");
  if (toggleBtn) toggleBtn.textContent = lang === "ar" ? "English" : "عربي";
}

function setLang(lang) {
  localStorage.setItem(I18N_STORAGE_KEY, lang === "ar" ? "ar" : "en");
  applyStaticTranslations();
  if (typeof onLangChanged === "function") onLangChanged();
}

document.addEventListener("DOMContentLoaded", () => {
  applyStaticTranslations();
  document.getElementById("btn-lang-toggle")?.addEventListener("click", () => {
    setLang(getLang() === "ar" ? "en" : "ar");
  });
});
