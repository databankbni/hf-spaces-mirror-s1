import pandas as pd
import os
import logging
from datetime import datetime
from database import get_connection
from services.inventory import update_inventory_zones

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_products_from_csv(filepath):
    if not os.path.exists(filepath):
        logger.error(f"Файл не найден: {filepath}")
        return False
    try:
        df = pd.read_csv(filepath)
        required = ['name', 'sku', 'purchase_price', 'current_price']
        if not all(col in df.columns for col in required):
            logger.error(f"Отсутствуют обязательные колонки: {required}")
            return False
        conn = get_connection()
        cur = conn.cursor()
        for _, row in df.iterrows():
            date_added = row.get('date_added', datetime.now().isoformat())
            if not isinstance(date_added, str):
                date_added = date_added.isoformat()
            status = row.get('status', 'in_stock')
            cur.execute('''
                INSERT OR REPLACE INTO products (sku, name, purchase_price, current_price, date_added, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (row['sku'], row['name'], row['purchase_price'], row['current_price'], date_added, status))
        conn.commit()
        conn.close()
        logger.info(f"Загружено {len(df)} товаров из {filepath}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при загрузке товаров: {e}")
        return False

def load_sales_from_csv(filepath):
    if not os.path.exists(filepath):
        logger.error(f"Файл не найден: {filepath}")
        return False
    try:
        df = pd.read_csv(filepath)
        if 'sku' not in df.columns and 'product_id' not in df.columns:
            logger.error("Необходима колонка 'sku' или 'product_id'")
            return False
        if 'sale_date' not in df.columns:
            logger.error("Отсутствует колонка 'sale_date'")
            return False
        conn = get_connection()
        cur = conn.cursor()
        sku_to_id = {}
        if 'sku' in df.columns:
            cur.execute('SELECT id, sku FROM products')
            for pid, sku in cur.fetchall():
                sku_to_id[sku] = pid
        inserted = 0
        for _, row in df.iterrows():
            if 'sku' in row:
                product_id = sku_to_id.get(row['sku'])
                if product_id is None:
                    logger.warning(f"SKU {row['sku']} не найден, пропускаем")
                    continue
            else:
                product_id = row['product_id']
            sale_date = row['sale_date']
            if not isinstance(sale_date, str):
                sale_date = sale_date.isoformat()
            quantity = row.get('quantity', 1)
            sale_price = row.get('sale_price', None)
            cur.execute('''
                INSERT INTO sales (product_id, sale_date, quantity, sale_price)
                VALUES (?, ?, ?, ?)
            ''', (product_id, sale_date, quantity, sale_price))
            inserted += 1
        conn.commit()
        conn.close()
        logger.info(f"Загружено {inserted} продаж из {filepath}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при загрузке продаж: {e}")
        return False

def import_all_data(products_file=None, sales_file=None):
    if products_file and os.path.exists(products_file):
        ok = load_products_from_csv(products_file)
        if not ok:
            logger.error("Импорт товаров не удался")
            return False
    else:
        logger.warning("Файл товаров не указан или не найден")
    if sales_file and os.path.exists(sales_file):
        ok = load_sales_from_csv(sales_file)
        if not ok:
            logger.error("Импорт продаж не удался")
            return False
    else:
        logger.warning("Файл продаж не указан или не найден")
    update_inventory_zones()
    return True