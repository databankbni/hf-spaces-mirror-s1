from datetime import datetime, timedelta
import pandas as pd


def format_date(date_value):
    """تحويل التاريخ إلى YYYY-MM-DD"""
    try:
        return pd.to_datetime(date_value).strftime("%Y-%m-%d")
    except Exception:
        return ""


def is_subscription_active(expiry_date):
    """هل الاشتراك ما زال ساريًا؟"""
    try:
        expiry = pd.to_datetime(expiry_date).date()
        return expiry >= datetime.now().date()
    except Exception:
        return False


def get_subscription_status(expiry_date):
    """إرجاع حالة الاشتراك"""
    return "نشط" if is_subscription_active(expiry_date) else "منتهي"


def remaining_days(expiry_date):
    """عدد الأيام المتبقية"""
    try:
        expiry = pd.to_datetime(expiry_date).date()
        return (expiry - datetime.now().date()).days
    except Exception:
        return -1


def extend_subscription(expiry_date, days):
    """
    تمديد الاشتراك.
    إذا كان الاشتراك منتهيًا يبدأ من اليوم،
    وإذا كان ما زال ساريًا يضيف الأيام على التاريخ الحالي.
    """
    try:
        expiry = pd.to_datetime(expiry_date).date()
    except Exception:
        expiry = datetime.now().date()

    today = datetime.now().date()

    if expiry < today:
        expiry = today

    return (expiry + timedelta(days=int(days))).strftime("%Y-%m-%d")