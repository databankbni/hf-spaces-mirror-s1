from database import get_connection
from datetime import datetime

def get_zone(days_on_shelf):
    if days_on_shelf < 7:
        return 'A'   # горячий товар
    elif days_on_shelf < 21:
        return 'B'   # тёплый
    elif days_on_shelf < 45:
        return 'C'   # холодный
    else:
        return 'D'   # мёртвый – пора уценивать

def update_inventory_zones():
    """
    Пересчитывает зоны для всех товаров со статусом 'in_stock'
    и обновляет таблицу inventory_zones.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, date_added FROM products WHERE status = "in_stock"')
    rows = cur.fetchall()
    now = datetime.now()
    updated = 0
    for product_id, date_added_str in rows:
        date_added = datetime.fromisoformat(date_added_str)
        days_on_shelf = (now - date_added).days
        zone = get_zone(days_on_shelf)
        cur.execute('''
            INSERT INTO inventory_zones (product_id, zone, days_on_shelf, last_updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                zone = excluded.zone,
                days_on_shelf = excluded.days_on_shelf,
                last_updated = excluded.last_updated
        ''', (product_id, zone, days_on_shelf, now.isoformat()))
        updated += 1
    conn.commit()
    conn.close()
    print(f"Зоны обновлены для {updated} товаров.")

if __name__ == '__main__':
    update_inventory_zones()