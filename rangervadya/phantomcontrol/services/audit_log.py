from database import get_connection
from datetime import datetime

def log_change(product_id, action, field, old_value, new_value, user='system'):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO audit_log (product_id, action, field, old_value, new_value, timestamp, user)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (product_id, action, field, str(old_value), str(new_value), datetime.now().isoformat(), user))
    conn.commit()
    conn.close()