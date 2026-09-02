import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv('DB_PATH', 'avito_data.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            sku TEXT UNIQUE,
            purchase_price REAL,
            current_price REAL,
            date_added TEXT,
            status TEXT DEFAULT 'in_stock'
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            sale_date TEXT,
            quantity INTEGER DEFAULT 1,
            sale_price REAL,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS inventory_zones (
            product_id INTEGER PRIMARY KEY,
            zone CHAR(1),
            days_on_shelf INTEGER,
            sales_velocity REAL,
            last_updated TEXT,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    # Проверяем, есть ли колонка quantity
    cur.execute("PRAGMA table_info(sales)")
    columns = [col[1] for col in cur.fetchall()]
    if 'quantity' not in columns:
        cur.execute('ALTER TABLE sales ADD COLUMN quantity INTEGER DEFAULT 1')
    conn.commit()
    conn.close()
    print("База данных инициализирована (пустая).")

if __name__ == '__main__':
    init_db()