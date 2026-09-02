import pandas as pd
from database import get_connection
from datetime import datetime

def get_all_products():
    conn = get_connection()
    df = pd.read_sql_query('''
        SELECT p.id, p.name, p.sku, p.purchase_price, p.current_price, 
               p.date_added, p.status, p.quantity,
               z.zone, z.days_on_shelf, z.sales_velocity
        FROM products p
        LEFT JOIN inventory_zones z ON p.id = z.product_id
        ORDER BY p.id
    ''', conn)
    conn.close()
    return df

def update_product(product_id, field, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f'UPDATE products SET {field} = ? WHERE id = ?', (value, product_id))
    conn.commit()
    conn.close()

def update_zone_field(product_id, field, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT product_id FROM inventory_zones WHERE product_id = ?', (product_id,))
    if cur.fetchone():
        cur.execute(f'UPDATE inventory_zones SET {field} = ? WHERE product_id = ?', (value, product_id))
    else:
        cur.execute('''
            INSERT INTO inventory_zones (product_id, zone, days_on_shelf, sales_velocity, last_updated)
            VALUES (?, ?, ?, ?, ?)
        ''', (product_id, 'A', 0, 0.0, datetime.now().isoformat()))
        cur.execute(f'UPDATE inventory_zones SET {field} = ? WHERE product_id = ?', (value, product_id))
    conn.commit()
    conn.close()

def delete_product(product_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()

def add_product(name, sku, purchase_price, current_price, quantity=1, status='in_stock'):
    conn = get_connection()
    cur = conn.cursor()
    date_added = datetime.now().isoformat()
    cur.execute('''
        INSERT INTO products (name, sku, purchase_price, current_price, quantity, date_added, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (name, sku, purchase_price, current_price, quantity, date_added, status))
    conn.commit()
    product_id = cur.lastrowid
    conn.close()
    return product_id

def add_sale(product_id, quantity, sale_price):
    """Добавляет запись о продаже в таблицу sales."""
    conn = get_connection()
    cur = conn.cursor()
    sale_date = datetime.now().isoformat()
    cur.execute('''
        INSERT INTO sales (product_id, sale_date, quantity, sale_price)
        VALUES (?, ?, ?, ?)
    ''', (product_id, sale_date, quantity, sale_price))
    conn.commit()
    conn.close()

def decrease_quantity(product_id, sale_price=None):
    """
    Уменьшает количество на 1. Если передан sale_price, записывает продажу.
    Если количество становится 0, удаляет товар.
    Возвращает: True – товар остался, False – товар удалён.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT quantity, current_price FROM products WHERE id = ?', (product_id,))
    row = cur.fetchone()
    if row:
        qty = row[0]
        price = row[1] if sale_price is None else sale_price
        if qty > 1:
            cur.execute('UPDATE products SET quantity = quantity - 1 WHERE id = ?', (product_id,))
            # Записываем продажу (одна единица)
            if sale_price is not None or price:
                add_sale(product_id, 1, price if price else 0)
            conn.commit()
            conn.close()
            return True
        else:
            # Удаляем товар и записываем последнюю продажу
            if sale_price is not None or price:
                add_sale(product_id, 1, price if price else 0)
            cur.execute('DELETE FROM products WHERE id = ?', (product_id,))
            conn.commit()
            conn.close()
            return False
    conn.close()
    return True

def update_inventory_zones():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, date_added FROM products WHERE status = "in_stock"')
    rows = cur.fetchall()
    now = datetime.now()
    for product_id, date_added_str in rows:
        date_added = datetime.fromisoformat(date_added_str)
        days_on_shelf = (now - date_added).days
        if days_on_shelf < 7:
            zone = 'A'
        elif days_on_shelf < 21:
            zone = 'B'
        elif days_on_shelf < 45:
            zone = 'C'
        else:
            zone = 'D'
        cur.execute('''
            INSERT INTO inventory_zones (product_id, zone, days_on_shelf, last_updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                zone = excluded.zone,
                days_on_shelf = excluded.days_on_shelf,
                last_updated = excluded.last_updated
        ''', (product_id, zone, days_on_shelf, now.isoformat()))
    conn.commit()
    conn.close()