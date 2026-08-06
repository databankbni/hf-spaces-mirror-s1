import gradio as gr

# دالة لإدارة عداد التسبيح
def count_tasbeeh(current_count, dhikr):
    # زيادة العداد بمقدار 1
    new_count = current_count + 1
    
    # التحقق مما إذا وصل الطفل للعدد المطلوب (33)
    if new_count >= 33:
        message = f"🎉 رَائِع جِدّاً! لَقَدْ أَتْمَمْتَ 33 مَرَّةً مِنْ ({dhikr}). جَزَاكَ اللَّهُ خَيْراً! 🌟"
        # إعادة العداد إلى صفر لتبدأ من جديد أو تنتقل لذكر آخر
        return 0, message
    else:
        message = f"✨ اِسْتَمِرَّ.. لَقَدْ سَبَّحْتَ {new_count} مَرَّاتٍ. نَحْوِ الْهَدَفِ (33) 🚀"
        return new_count, message

# دالة لتصفير العداد عند تغيير الذكر
def reset_counter():
    return 0, "📿 اِضْغَطْ عَلَى الزِّرِّ فِي الْأَسْفَلِ لِتَبْدَأَ التَّسْبِيحَ:"

# بناء واجهة التطبيق
with gr.Blocks(css="* {text-align: center; direction: rtl;} .gr-button {font-size: 24px; font-weight: bold;}") as demo:
    gr.Markdown("# 📿 مِسْبَحَتِي الرَّقْمِيَّةُ الذَّكِيَّةُ 📿")
    gr.Markdown("### لِنَجْمَعَ الْحَسَنَاتِ مَعاً! اِخْتَرْ ذِكْراً ثُمَّ اضْغَطْ عَلَى زِرِّ التَّسْبِيحِ")
    
    # اختيار الذكر
    dhikr_choice = gr.Radio(
        choices=["سُبْحَانَ اللَّهِ 🌸", "الْحَمْدُ لِلَّهِ ☀️", "اللَّهُ أَكْبَرُ 🕋", "أَسْتَغْفِرُ اللَّهَ 💫"], 
        label="اِخْتَرْ الذِّكْرَ الَّذِي تُرِيدُ تُرْدِيدَهُ:",
        value="سُبْحَانَ اللَّهِ 🌸"
    )
    
    # تخزين رقم العداد الحالي (مخفي عن واجهة المستخدم ولكنه يعمل في الخلفية)
    counter_state = gr.State(value=0)
    
    # عرض رسالة العداد والتشجيع
    output_message = gr.Markdown("📿 اِضْغَطْ عَلَى الزِّرِّ فِي الْأَسْفَلِ لِتَبْدَأَ التَّسْبِيحَ:")
    
    # زر التسبيح الكبير والتفاعلي
    tasbeeh_btn = gr.Button("اضغط هنا للتسبيح ✨ 👆", variant="primary")
    
    # ربط زر التسبيح بالدالة
    tasbeeh_btn.click(
        fn=count_tasbeeh,
        inputs=[counter_state, dhikr_choice],
        outputs=[counter_state, output_message]
    )
    
    # تصفير العداد تلقائياً إذا قام المستخدم بتغيير نوع الذكر
    dhikr_choice.change(
        fn=reset_counter,
        inputs=None,
        outputs=[counter_state, output_message]
    )

# تشغيل التطبيق
demo.launch()