import pandas as pd
from datetime import datetime, timedelta
from database import get_connection
import logging

logger = logging.getLogger(__name__)

def get_forecast_prophet(product_id, days_ahead=30):
    """
    Прогноз с использованием Prophet (если установлен).
    Если Prophet не установлен, использует скользящее среднее.
    """
    try:
        from prophet import Prophet
    except ImportError:
        logger.warning("Prophet не установлен, используется простая модель")
        return get_forecast_simple(product_id, days_ahead)
    
    conn = get_connection()
    df = pd.read_sql_query('''
        SELECT sale_date as ds, quantity as y
        FROM sales
        WHERE product_id = ?
        ORDER BY sale_date
    ''', conn, params=(product_id,), parse_dates=['ds'])
    conn.close()
    
    if df.empty or len(df) < 3:
        return None
    
    # Создаём и обучаем модель
    model = Prophet(yearly_seasonality=False, weekly_seasonality=True, daily_seasonality=False)
    model.fit(df)
    
    # Делаем прогноз
    future = model.make_future_dataframe(periods=days_ahead, include_history=False)
    forecast = model.predict(future)
    return forecast['yhat'].clip(lower=0).astype(int).tolist()

def get_forecast_simple(product_id, days_ahead=30):
    """Простой прогноз на основе среднего за последние 30 дней."""
    conn = get_connection()
    df = pd.read_sql_query('''
        SELECT quantity, sale_date
        FROM sales
        WHERE product_id = ?
        AND sale_date >= date('now', '-30 days')
    ''', conn, params=(product_id,))
    conn.close()
    if df.empty:
        return None
    avg = df['quantity'].mean()
    forecast = [max(1, int(avg + 0.5))] * days_ahead
    return forecast