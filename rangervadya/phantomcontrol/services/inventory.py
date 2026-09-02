from database import get_connection
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def get_sales_velocity(product_id, days_back=30):
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    cur = conn.cursor()
    cur.execute('''
        SELECT COALESCE(SUM(quantity), 0) / ? 
        FROM sales 
        WHERE product_id = ? AND sale_date >= ?
    ''', (days_back, product_id, cutoff))
    velocity = cur.fetchone()[0] or 0.0
    conn.close()
    return velocity

def update_inventory_zones():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, date_added FROM products WHERE status = "in_stock"')
    rows = cur.fetchall()
    now = datetime.now()
    scores = []
    for product_id, date_added_str in rows:
        date_added = datetime.fromisoformat(date_added_str)
        days_on_shelf = (now - date_added).days
        velocity = get_sales_velocity(product_id, 30)
        score = (days_on_shelf * 0.7) - (velocity * 30 * 0.3)
        scores.append((product_id, days_on_shelf, velocity, score))
    
    if not scores:
        logger.info("Нет товаров для сортировки.")
        return
    
    scores_sorted = sorted(scores, key=lambda x: x[3])
    n = len(scores_sorted)
    zones = {}
    for i, (pid, days, vel, _) in enumerate(scores_sorted):
        if i < n * 0.25:
            zone = 'A'
        elif i < n * 0.5:
            zone = 'B'
        elif i < n * 0.75:
            zone = 'C'
        else:
            zone = 'D'
        zones[pid] = (zone, days, vel)
    
    for pid, (zone, days, vel) in zones.items():
        cur.execute('''
            INSERT INTO inventory_zones (product_id, zone, days_on_shelf, sales_velocity, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                zone = excluded.zone,
                days_on_shelf = excluded.days_on_shelf,
                sales_velocity = excluded.sales_velocity,
                last_updated = excluded.last_updated
        ''', (pid, zone, days, vel, now.isoformat()))
    conn.commit()
    conn.close()
    logger.info(f"Зоны обновлены для {len(zones)} товаров.")