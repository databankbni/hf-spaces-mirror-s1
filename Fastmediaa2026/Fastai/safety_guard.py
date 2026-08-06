def check_model_access(selected_model, allowed_models_string):
    # تحويل النص اللي جاي من الـ CSV لقائمة نظيفة
    allowed_list = [m.strip() for m in allowed_models_string.split(",")]
    
    # لو النموذج اللي اختاره العميل مش في القائمة المسموحة، نرجعه لأول نموذج مسموح له
    if selected_model not in allowed_list:
        return allowed_list[0]
    
    return selected_model

def get_allowed_models_list(allowed_models_string):
    # دي الدالة الجديدة اللي هتستخدمها في الـ UI
    # وظيفتها ترجع القائمة نظيفة للموقع عشان يعرضها للعميل
    return [m.strip() for m in allowed_models_string.split(",")]