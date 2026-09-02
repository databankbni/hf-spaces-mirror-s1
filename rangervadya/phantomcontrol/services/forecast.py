from database import get_connection
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def get_all_forecast(days_ahead=30):
    """Возвращает прогноз для всех товаров (простая экстраполяция)."""
    conn = get_connection()
    products = pd.read_sql_query('SELECT id, name FROM products WHERE status="in_stock"', conn)
    conn.close()
    result = {}
    for _, row in products.iterrows():
        pid = row['id']
        forecast = get_forecast_for_product(pid, days_ahead)
        if forecast:
            result[row['name']] = forecast
    return result

def get_forecast_for_product(product_id, days_ahead=30):
    conn = get_connection()
    df = pd.read_sql_query('''
        SELECT sale_date, quantity 
        FROM sales 
        WHERE product_id = ? 
        ORDER BY sale_date
    ''', conn, params=(product_id,), parse_dates=['sale_date'])
    conn.close()
    if df.empty:
        return None
    df_daily = df.groupby('sale_date').agg({'quantity': 'sum'}).asfreq('D', fill_value=0)
    if len(df_daily) < 3:
        last_week_avg = df_daily['quantity'].tail(7).mean()
        forecast = [max(0, int(last_week_avg))] * days_ahead
        return forecast
    # Простая экстраполяция: среднее за последние 7 дней
    last_week_avg = df_daily['quantity'].tail(7).mean()
    forecast = [max(0, int(last_week_avg))] * days_ahead
    return forecast

def get_trend_products(top_n=3):
    """Анализирует продажи за последние 60 дней и рекомендует товары."""
    conn = get_connection()
    df = pd.read_sql_query('''
        SELECT p.id, p.name, s.sale_date, s.quantity
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE s.sale_date >= date('now', '-60 days')
    ''', conn, parse_dates=['sale_date'])
    conn.close()
    if df.empty:
        return [("Нет данных", "Нет истории продаж.")]
    df['week'] = df['sale_date'].dt.to_period('W').apply(lambda r: r.start_time)
    weekly = df.groupby(['id', 'name', 'week']).agg({'quantity': 'sum'}).reset_index()
    results = []
    for (pid, pname), group in weekly.groupby(['id', 'name']):
        if len(group) < 3:
            continue
        x = (group['week'] - group['week'].min()).dt.days
        y = group['quantity']
        if len(x) > 1:
            slope = ( (x - x.mean()) * (y - y.mean()) ).sum() / ((x - x.mean())**2).sum() if len(x) > 1 else 0
            results.append((pname, slope))
    results.sort(key=lambda x: x[1], reverse=True)
    recommendations = []
    for name, slope in results[:top_n]:
        if slope > 0.1:
            recommendations.append((name, f"Растущий тренд (+{slope:.2f} продаж в неделю)"))
        else:
            recommendations.append((name, "Стабильный спрос."))
    return recommendations