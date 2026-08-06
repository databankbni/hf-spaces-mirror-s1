import gradio as gr

# =====================================================================
# ALOS - Sovereign Legal Operating System
# تم إضافة الشعار في أعلى نقطة فوق اسم المنصة، مع الحفاظ على التنسيق
# =====================================================================

final_css = """
body {
    background-color: #ffffff !important;
    color: #000000 !important;
    font-family: 'Segoe UI', 'Cairo', sans-serif !important;
    direction: rtl !important;
}
.main-wrapper {max-width: 1000px; margin: 0 auto; padding: 30px;}

/* ---------- Header & Logo Section ---------- */
.header-box {
    text-align: center;
    border-bottom: 2px solid #c5a059;
    padding-bottom: 24px;
    margin-bottom: 10px;
}
.logo-container {
    margin-bottom: 15px;
    display: flex;
    justify-content: center;
}
.logo-img {max-width: 120px; height: auto;}
.title-main {
    font-size: 26px;
    font-weight: 900;
    margin: 0;
    letter-spacing: 1px;
    color: #000000 !important;
}
.title-sub {
    font-size: 20px;
    font-weight: 800;
    margin: 4px 0 0 0;
    color: #333333 !important;
}
.ceo-line {
    font-size: 16px;
    font-weight: 700;
    margin: 10px 0 0 0;
    display: block;
    white-space: nowrap;
    color: #c5a059 !important;
}
.tagline {
    font-style: italic;
    color: #555555 !important;
    margin: 8px 0 0 0;
    font-size: 14px;
}

/* ---------- Search & Indicators ---------- */
.search-wrap {margin: 24px 0 16px 0;}
.search-wrap input {
    width: 100%;
    padding: 14px 16px;
    border: 2px solid #c5a059;
    border-radius: 6px;
    box-sizing: border-box;
    background-color: #ffffff;
    color: #000000;
    font-size: 15px;
}
.status-bar {display: flex; gap: 10px; margin: 0 0 30px 0; flex-wrap: wrap;}
.status-box {
    flex: 1;
    min-width: 120px;
    border: 1.5px solid #c5a059;
    border-radius: 6px;
    padding: 14px 8px;
    text-align: center;
    font-weight: 800;
    background-color: #f9f9f9;
    color: #000000;
}

/* ---------- Section Titles ---------- */
.section-title {
    font-size: 20px;
    font-weight: 900;
    color: #000000 !important;
    margin: 26px 0 14px 0;
    border-right: 4px solid #c5a059;
    padding-right: 10px;
}

/* ---------- Operations Cards (اللون الأبيض الناصع) ---------- */
.op-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 15px !important;
}
.op-card {
    background-color: #000000 !important;
    padding: 22px !important;
    margin-bottom: 0px !important;
    border-radius: 4px !important;
    width: 100% !important;
    display: block !important;
    text-align: right !important;
    border-top: 3px solid #c5a059 !important;
    box-sizing: border-box !important;
}
.op-title {
    font-size: 18px !important;
    font-weight: 900 !important;
    color: #ffffff !important; 
    display: block !important;
}
.op-desc {
    font-size: 13px !important;
    color: #ffffff !important; 
    display: block !important;
    margin-top: 6px !important;
    opacity: 1.0 !important;
}
"""

core_portals = [
    ("🤖 المساعد القانوني الذكي", "اسأل عن أي موضوع قانوني واحصل على إجابة دقيقة مدعومة بالمصادر."),
    ("📖 الموسوعة القانونية", "القوانين، الأحكام، آراء فقهية وشروحات."),
    ("🛡️ مركز التوعية والوقاية القانونية", "نصائح قانونية، جرائم إلكترونية، وقاية ومعالجة."),
    ("👤 دليل المحامين", "ابحث عن محامٍ متخصص في منطقتك."),
    ("📝 نماذج العقود والمستندات", "نماذج جاهزة وقابلة للتعديل وفق القوانين الأردنية."),
    ("🔤 المصطلحات القانونية", "قاموس شامل للمصطلحات القانونية باللغة الإنجليزية."),
    ("🎓 التطوير المهني", "دورات، مهارات، وتطوير الذات المهني."),
    ("📰 JCLET — المجلة العلمية", "المجلة العلمية المحكّمة للمنصة."),
]

operations_engines = [
    ("📚 المكتبة القانونية | Legal Library Search", "بحث في التشريعات، الكتب، والسوابق القضائية."),
    ("🏛️ بوابات المحاكم | Court Portals", "اتصال مباشر بخدمات القضاء ومتابعة القضايا."),
    ("🏢 المرافق الحكومية | Govt Facilities", "الوصول إلى بيانات الأراضي والبلديات والشركات."),
    ("📜 دفتر التاجر | Trader's Journal", "أتمتة الامتثال التجاري والسجلات."),
    ("🎥 مكتب الاجتماعات المرئي | Meeting Room", "غرفة اجتماعات مرئية احترافية وآمنة."),
    ("⚖️ التحكيم والعقود الدولية | Arbitration & Intl. Contracts", "العقود الدولية وآليات التحكيم."),
]

with gr.Blocks(css=final_css, title="ALOS — Sovereign Legal Operating System") as demo:
    with gr.Column(elem_classes="main-wrapper"):

        # 1) الشعار + اسم المنصة + الاسم في سطر واحد
        gr.HTML("""
        <div class="header-box">
            <div class="logo-container">
                <img src="file/143812.jpg" class="logo-img">
            </div>
            <h1 class="title-main">ALOS</h1>
            <p class="title-sub">SOVEREIGN LEGAL OPERATING SYSTEM</p>
            <span class="ceo-line">Founder & CEO: Sameer Alnabtiti</span>
            <p class="tagline">Reimagining Legal Systems Through Sovereign AI</p>
        </div>
        """)

        # 2) البحث + المؤشرات
        gr.HTML("""
        <div class="search-wrap">
            <input type="text" placeholder="🔍 ابحث في المنصة...">
        </div>
        <div class="status-bar">
            <div class="status-box">📅 المواعيد</div>
            <div class="status-box">📄 العقود</div>
            <div class="status-box">⚖️ القضايا</div>
            <div class="status-box">🔔 الإشعارات</div>
        </div>
        """)

        # 3) البوابات الأساسية
        gr.HTML('<div class="section-title">البوابات الأساسية</div>')
        core_cards_html = '<div class="op-grid">'
        for title, desc in core_portals:
            core_cards_html += f"""
            <div class="op-card">
                <span class="op-title">{title}</span>
                <span class="op-desc">{desc}</span>
            </div>
            """
        core_cards_html += "</div>"
        gr.HTML(core_cards_html)

        # 4) المحركات التشغيلية
        gr.HTML('<div class="section-title">Legal Operations — المحركات التشغيلية</div>')
        ops_cards_html = '<div class="op-grid">'
        for title, desc in operations_engines:
            ops_cards_html += f"""
            <div class="op-card">
                <span class="op-title">{title}</span>
                <span class="op-desc">{desc}</span>
            </div>
            """
        ops_cards_html += "</div>"
        gr.HTML(ops_cards_html)

if __name__ == "__main__":
    demo.launch()
