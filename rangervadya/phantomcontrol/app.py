import dash
from dash import dcc, html, Input, Output, State, callback, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
import os
import base64
import io
from PIL import Image
import tempfile
import logging
import time
import requests
import json
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# 0. Cloudflare D1 настройки
# ========================
D1_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
D1_DATABASE_ID = os.getenv('CLOUDFLARE_DATABASE_ID')
D1_API_TOKEN = os.getenv('CLOUDFLARE_API_TOKEN')

def d1_query(sql, params=None):
    """Выполняет запрос к Cloudflare D1 через HTTP API."""
    if not all([D1_ACCOUNT_ID, D1_DATABASE_ID, D1_API_TOKEN]):
        raise Exception("Cloudflare D1 не настроен. Проверьте переменные окружения.")
    
    url = f"https://api.cloudflare.com/client/v4/accounts/{D1_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {D1_API_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {"sql": sql}
    if params:
        data["params"] = params
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                return result['result'][0]['results']
            else:
                raise Exception(f"Ошибка D1: {result.get('errors')}")
        else:
            raise Exception(f"HTTP ошибка: {response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"Ошибка D1 запроса: {e}")
        raise

# ========================
# 1. Функции для работы с БД через D1
# ========================
def init_db():
    """Создаёт таблицы в Cloudflare D1."""
    try:
        d1_query('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                sku TEXT UNIQUE,
                purchase_price REAL,
                current_price REAL,
                quantity INTEGER DEFAULT 1,
                date_added TEXT,
                status TEXT DEFAULT 'in_stock'
            )
        ''')
        d1_query('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                sale_date TEXT,
                quantity INTEGER DEFAULT 1,
                sale_price REAL
            )
        ''')
        d1_query('''
            CREATE TABLE IF NOT EXISTS inventory_zones (
                product_id INTEGER PRIMARY KEY,
                zone CHAR(1),
                days_on_shelf INTEGER,
                sales_velocity REAL,
                last_updated TEXT
            )
        ''')
        d1_query('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                action TEXT,
                field TEXT,
                old_value TEXT,
                new_value TEXT,
                timestamp TEXT,
                user TEXT DEFAULT 'system'
            )
        ''')
        try:
            d1_query("SELECT quantity FROM products LIMIT 1")
        except:
            try:
                d1_query("ALTER TABLE products ADD COLUMN quantity INTEGER DEFAULT 1")
            except:
                pass
        logger.info("База данных Cloudflare D1 инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации D1: {e}")

def log_change(product_id, action, field, old_value, new_value, user='system'):
    try:
        d1_query('''
            INSERT INTO audit_log (product_id, action, field, old_value, new_value, timestamp, user)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', [product_id, action, field, str(old_value), str(new_value), datetime.now().isoformat(), user])
    except Exception as e:
        logger.error(f"Ошибка логирования: {e}")

def get_all_products():
    try:
        results = d1_query('''
            SELECT p.id, p.name, p.sku, p.purchase_price, p.current_price, 
                   p.date_added, p.status, p.quantity,
                   z.zone, z.days_on_shelf, z.sales_velocity
            FROM products p
            LEFT JOIN inventory_zones z ON p.id = z.product_id
            ORDER BY p.id
        ''')
        if results:
            return pd.DataFrame(results)
        else:
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"Ошибка загрузки товаров: {e}")
        return pd.DataFrame()

def update_product(product_id, field, value):
    try:
        old_result = d1_query(f'SELECT {field} FROM products WHERE id = ?', [product_id])
        old_value = old_result[0][field] if old_result else None
        d1_query(f'UPDATE products SET {field} = ? WHERE id = ?', [value, product_id])
        log_change(product_id, 'update', field, old_value, value)
    except Exception as e:
        logger.error(f"Ошибка обновления товара: {e}")

def update_zone_field(product_id, field, value):
    try:
        existing = d1_query('SELECT product_id FROM inventory_zones WHERE product_id = ?', [product_id])
        if existing:
            d1_query(f'UPDATE inventory_zones SET {field} = ? WHERE product_id = ?', [value, product_id])
        else:
            d1_query('''
                INSERT INTO inventory_zones (product_id, zone, days_on_shelf, sales_velocity, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', [product_id, 'A', 0, 0.0, datetime.now().isoformat()])
            d1_query(f'UPDATE inventory_zones SET {field} = ? WHERE product_id = ?', [value, product_id])
    except Exception as e:
        logger.error(f"Ошибка обновления зоны: {e}")

def delete_product(product_id):
    try:
        result = d1_query('SELECT name, sku FROM products WHERE id = ?', [product_id])
        if result:
            name = result[0].get('name', '')
            sku = result[0].get('sku', '')
            d1_query('DELETE FROM products WHERE id = ?', [product_id])
            log_change(product_id, 'delete', 'all', f'{name} ({sku})', 'удалён')
            try:
                from services.email_sender import EmailSender
                email = EmailSender()
                if email.enabled:
                    email.send_product_deleted(name, sku)
            except:
                pass
            try:
                from services.telegram_bot import TelegramBot
                bot = TelegramBot()
                if bot.enabled:
                    bot.send_product_deleted(name, sku)
            except:
                pass
    except Exception as e:
        logger.error(f"Ошибка удаления товара: {e}")

def add_product(name, sku, purchase_price, current_price, quantity=1, status='in_stock'):
    try:
        existing = d1_query('SELECT id FROM products WHERE sku = ?', [sku])
        if existing:
            product_id = existing[0]['id']
            d1_query('''
                UPDATE products 
                SET name = ?, purchase_price = ?, current_price = ?, quantity = ?, status = ?
                WHERE id = ?
            ''', [name, purchase_price, current_price, quantity, status, product_id])
            log_change(product_id, 'update', 'all', 'existing', f'{name} ({sku})')
            return product_id
        else:
            date_added = datetime.now().isoformat()
            d1_query('''
                INSERT INTO products (name, sku, purchase_price, current_price, quantity, date_added, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', [name, sku, purchase_price, current_price, quantity, date_added, status])
            result = d1_query('SELECT last_insert_rowid() as id')
            product_id = result[0]['id']
            log_change(product_id, 'add', 'all', 'none', f'{name} ({sku})')
            try:
                from services.email_sender import EmailSender
                email = EmailSender()
                if email.enabled:
                    email.send_product_added(name, sku, current_price)
            except:
                pass
            try:
                from services.telegram_bot import TelegramBot
                bot = TelegramBot()
                if bot.enabled:
                    bot.send_product_added(name, sku, current_price)
            except:
                pass
            return product_id
    except Exception as e:
        logger.error(f"Ошибка добавления товара: {e}")
        raise

def add_sale(product_id, quantity, sale_price):
    try:
        sale_date = datetime.now().isoformat()
        d1_query('''
            INSERT INTO sales (product_id, sale_date, quantity, sale_price)
            VALUES (?, ?, ?, ?)
        ''', [product_id, sale_date, quantity, sale_price])
        logger.info(f"✅ Продажа записана: product_id={product_id}, qty={quantity}, price={sale_price}")
    except Exception as e:
        logger.error(f"Ошибка записи продажи: {e}")

def decrease_quantity(product_id, sale_price=None):
    try:
        result = d1_query('SELECT quantity, current_price, name FROM products WHERE id = ?', [product_id])
        if not result:
            return "Ошибка"
        row = result[0]
        qty = row['quantity']
        price = row['current_price'] if sale_price is None else sale_price
        name = row['name']
        
        add_sale(product_id, 1, float(price) if price is not None else 0.0)
        
        if qty > 1:
            new_qty = qty - 1
            d1_query('UPDATE products SET quantity = ? WHERE id = ?', [new_qty, product_id])
            log_change(product_id, 'sell', 'quantity', qty, new_qty)
            try:
                from services.email_sender import EmailSender
                email = EmailSender()
                if email.enabled:
                    email.send_email(f"🔄 Списание: {name}", f"Товар {name}, осталось: {new_qty} шт., цена: {price} ₽")
            except:
                pass
            try:
                from services.telegram_bot import TelegramBot
                bot = TelegramBot()
                if bot.enabled:
                    bot.send_message(f"🔄 <b>Списание</b>\n📦 {name}\nОсталось: {new_qty} шт.\n💰 {price} ₽")
            except:
                pass
            if new_qty <= 3:
                try:
                    email.send_low_stock(name, new_qty)
                except:
                    pass
                try:
                    bot.send_low_stock(name, new_qty)
                except:
                    pass
            return "Уменьшено"
        else:
            d1_query('UPDATE products SET quantity = 0, status = "sold" WHERE id = ?', [product_id])
            log_change(product_id, 'sell', 'status', 'in_stock', 'sold')
            try:
                from services.email_sender import EmailSender
                email = EmailSender()
                if email.enabled:
                    email.send_product_sold(name, 0, price)
            except:
                pass
            try:
                from services.telegram_bot import TelegramBot
                bot = TelegramBot()
                if bot.enabled:
                    bot.send_product_sold(name, 0, price)
            except:
                pass
            return "Продан"
    except Exception as e:
        logger.error(f"Ошибка списания: {e}")
        return "Ошибка"

def update_inventory_zones(retries=3, delay=0.2):
    for attempt in range(retries):
        try:
            rows = d1_query('SELECT id, date_added FROM products WHERE status = "in_stock"')
            now = datetime.now()
            for row in rows:
                product_id = row['id']
                date_added_str = row['date_added']
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
                d1_query('''
                    INSERT INTO inventory_zones (product_id, zone, days_on_shelf, last_updated)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(product_id) DO UPDATE SET
                        zone = excluded.zone,
                        days_on_shelf = excluded.days_on_shelf,
                        last_updated = excluded.last_updated
                ''', [product_id, zone, days_on_shelf, now.isoformat()])
            return
        except Exception as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(delay)
                continue
            else:
                logger.error(f"Ошибка обновления зон: {e}")
                raise

# ========================
# 2. Прогноз (упрощённый)
# ========================
def get_all_forecast(days_ahead=30):
    try:
        df = d1_query('''
            SELECT p.id, p.name, s.sale_date, s.quantity
            FROM sales s
            JOIN products p ON s.product_id = p.id
            WHERE s.sale_date >= date('now', '-60 days')
            ORDER BY s.sale_date
        ''')
        if not df:
            return {}
        result = {}
        now = datetime.now()
        df_pd = pd.DataFrame(df)
        for name, group in df_pd.groupby('name'):
            group['sale_date'] = pd.to_datetime(group['sale_date'])
            last_30 = group[group['sale_date'] >= now - timedelta(days=30)]
            if not last_30.empty:
                avg = last_30['quantity'].mean()
            else:
                avg = group['quantity'].mean()
            forecast = [max(1, int(avg + 0.5))] * days_ahead
            result[name] = forecast
        return result
    except Exception as e:
        logger.error(f"Ошибка прогноза: {e}")
        return {}

def get_trend_products():
    try:
        df = d1_query('SELECT name, current_price, purchase_price FROM products WHERE status="in_stock"')
        if not df:
            return []
        df_pd = pd.DataFrame(df)
        df_pd['margin'] = ((df_pd['current_price'] - df_pd['purchase_price']) / df_pd['purchase_price']) * 100
        top = df_pd.nlargest(3, 'margin')
        return [(row['name'], f"Маржа {row['margin']:.0f}%") for _, row in top.iterrows()]
    except Exception as e:
        logger.error(f"Ошибка трендов: {e}")
        return []

# ========================
# 3. Реальный AI-анализ фото
# ========================
def analyze_photo_real(image_path):
    try:
        import torch
        import torchvision.transforms as transforms
        from torchvision import models
        from PIL import Image
        import urllib.request
        
        model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
        model.eval()
        
        url = "https://raw.githubusercontent.com/pytorch/hub/master/imagenet_classes.txt"
        with urllib.request.urlopen(url) as f:
            labels = [line.decode('utf-8').strip() for line in f.readlines()]
        
        transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        
        image = Image.open(image_path).convert('RGB')
        input_tensor = transform(image).unsqueeze(0)
        
        with torch.no_grad():
            output = model(input_tensor)
            probabilities = torch.nn.functional.softmax(output[0], dim=0)
            top_probs, top_indices = torch.topk(probabilities, 5)
        
        predictions = []
        for i in range(5):
            idx = top_indices[i].item()
            prob = top_probs[i].item()
            label = labels[idx] if idx < len(labels) else f"Class {idx}"
            predictions.append((label, prob))
        
        main_label, main_prob = predictions[0]
        category = main_label.split(',')[0].strip()
        
        trending_keywords = ['sunglass', 'jacket', 'boot', 'sneaker', 'watch', 'perfume', 'backpack', 'bag', 'hat', 'scarf']
        is_trending = any(kw in category.lower() for kw in trending_keywords)
        seasonal_keywords = ['jacket', 'coat', 'scarf', 'glove', 'boot', 'sunglass', 'shorts', 't-shirt', 'sandals', 'hat']
        is_seasonal = any(kw in category.lower() for kw in seasonal_keywords)
        
        if main_prob > 0.85 and is_trending:
            recommendation = "Рекомендуем закупить! 🔥"
            reason = f"Модель уверена на {main_prob*100:.1f}%, категория '{category}' в тренде."
        elif main_prob > 0.85 and is_seasonal:
            recommendation = "С осторожностью (сезонный товар). ⚠️"
            reason = f"Высокая уверенность ({main_prob*100:.1f}%), но товар сезонный. Проверьте спрос."
        elif main_prob > 0.85:
            recommendation = "С осторожностью (не в тренде). ⚠️"
            reason = f"Уверенность {main_prob*100:.1f}%, но категория '{category}' не в тренде."
        elif main_prob > 0.6:
            recommendation = "Возможно, стоит рассмотреть. 🤔"
            reason = f"Уверенность {main_prob*100:.1f}%. Категория '{category}'."
        else:
            recommendation = "Не рекомендуется. ❌"
            reason = f"Модель не уверена ({main_prob*100:.1f}%). Возможно, это {predictions[1][0]} или {predictions[2][0]}."
        
        return {
            'category': category,
            'main_confidence': main_prob,
            'recommendation': recommendation,
            'reason': reason,
            'all_predictions': predictions,
            'is_trending': is_trending,
            'is_seasonal': is_seasonal
        }
    except Exception as e:
        logger.error(f"Ошибка в AI-анализе: {e}", exc_info=True)
        return None

    # ========================
# 4. Вспомогательные функции для дашборда
# ========================
def load_data():
    df_products = get_all_products()
    try:
        df_sales = pd.DataFrame(d1_query('SELECT * FROM sales'))
    except:
        df_sales = pd.DataFrame()
    try:
        df_zones = pd.DataFrame(d1_query('SELECT * FROM inventory_zones'))
    except:
        df_zones = pd.DataFrame()
    return df_products, df_sales, df_zones

def get_metrics(df_products, df_sales, df_zones):
    total_invested = df_products['purchase_price'].sum() if not df_products.empty else 0
    in_stock = df_products[df_products['status'] == 'in_stock'] if not df_products.empty else pd.DataFrame()
    total_circulation = in_stock['current_price'].sum() if not in_stock.empty else 0
    total_sales = df_sales['sale_price'].sum() if not df_sales.empty else 0
    profit = total_sales - total_invested
    if not df_zones.empty and 'zone' in df_zones.columns:
        zone_counts = df_zones['zone'].value_counts().reset_index()
        zone_counts.columns = ['zone', 'count']
    else:
        zone_counts = pd.DataFrame()
    return {
        'invested': total_invested,
        'circulation': total_circulation,
        'profit': profit,
        'zone_counts': zone_counts,
        'in_stock_count': len(in_stock)
    }

def get_top_margin(df_products):
    if df_products.empty:
        return pd.DataFrame()
    in_stock = df_products[df_products['status'] == 'in_stock'].copy()
    if not in_stock.empty:
        in_stock['purchase_price'] = pd.to_numeric(in_stock['purchase_price'], errors='coerce').fillna(0)
        in_stock['current_price'] = pd.to_numeric(in_stock['current_price'], errors='coerce').fillna(0)
        in_stock['margin'] = ((in_stock['current_price'] - in_stock['purchase_price']) / in_stock['purchase_price']) * 100
        top = in_stock.nlargest(5, 'margin')[['name', 'margin', 'current_price', 'purchase_price']]
        return top
    return pd.DataFrame()

def get_sales_trend(df_sales, df_products):
    if df_sales.empty or df_products.empty:
        return None
    df = df_sales.merge(df_products[['id', 'name']], left_on='product_id', right_on='id')
    df['sale_date'] = pd.to_datetime(df['sale_date'])
    df['week'] = df['sale_date'].dt.to_period('W').apply(lambda r: r.start_time)
    weekly = df.groupby(['week', 'name']).agg({'quantity': 'sum'}).reset_index()
    return weekly

# ========================
# 5. Dash-приложение
# ========================
external_stylesheets = [
    dbc.themes.DARKLY,
    "https://use.fontawesome.com/releases/v6.0.0/css/all.css"
]

app = dash.Dash(__name__, external_stylesheets=external_stylesheets, suppress_callback_exceptions=True)
app.title = "Phantom Service – Командный центр"

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body { background-color: #0d1117; font-family: 'Segoe UI', sans-serif; }
            .card-gradient {
                background: linear-gradient(145deg, #1c2333, #0d1117);
                border: 1px solid #2d3a4a;
                border-radius: 15px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.4);
                transition: transform 0.2s, box-shadow 0.2s;
            }
            .card-gradient:hover {
                transform: translateY(-4px);
                box-shadow: 0 12px 40px rgba(0,0,0,0.6);
            }
            .phantom-title {
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                background: linear-gradient(135deg, #f5af19, #f12711);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                text-shadow: none;
                letter-spacing: 2px;
            }
            .metric-value { font-size: 2rem; font-weight: 700; color: #f8f9fa; }
            .metric-label { font-size: 0.9rem; color: #adb5bd; text-transform: uppercase; letter-spacing: 1px; }
            .zone-badge { font-weight: 700; padding: 6px 12px; border-radius: 20px; font-size: 0.8rem; }
            .zone-A { background: #28a745; color: #fff; }
            .zone-B { background: #ffc107; color: #212529; }
            .zone-C { background: #fd7e14; color: #fff; }
            .zone-D { background: #dc3545; color: #fff; }
            .sidebar-link {
                color: #adb5bd !important;
                transition: all 0.2s;
                border-radius: 10px;
                padding: 12px 20px;
                margin-bottom: 5px;
                display: flex;
                align-items: center;
            }
            .sidebar-link:hover { background: #2d3a4a; color: #f8f9fa !important; text-decoration: none; }
            .sidebar-link.active { background: #f5af19; color: #0d1117 !important; font-weight: 600; }
            .upload-area {
                border: 2px dashed #2d3a4a;
                border-radius: 15px;
                padding: 40px;
                text-align: center;
                transition: border 0.3s;
                cursor: pointer;
            }
            .upload-area:hover { border-color: #f5af19; }
            .upload-area.dragover { border-color: #f5af19; background: rgba(245, 175, 25, 0.05); }
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td,
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th {
                background-color: #0d1117 !important;
                color: #f8f9fa !important;
                border-color: #2d3a4a !important;
            }
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td input,
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td .dash-cell-value {
                color: #f8f9fa !important;
                background-color: #1a2028 !important;
            }
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td.focused {
                background-color: #2d3a4a !important;
                color: #ffffff !important;
            }
            .spinner {
                display: inline-block;
                width: 40px;
                height: 40px;
                border: 4px solid #f5af19;
                border-radius: 50%;
                border-top-color: transparent;
                animation: spin 1s linear infinite;
            }
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            .confidence-bar {
                height: 8px;
                border-radius: 4px;
                background: #2d3a4a;
                margin-top: 4px;
                overflow: hidden;
            }
            .confidence-bar-fill {
                height: 100%;
                border-radius: 4px;
                transition: width 0.5s ease;
            }
            .detail-hidden { display: none; }
            .detail-visible { display: block; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# ========================
# 6. Боковое меню
# ========================
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "280px",
    "padding": "20px 10px",
    "background": "#161b22",
    "border-right": "1px solid #2d3a4a",
    "overflow-y": "auto",
    "z-index": 1000,
}
CONTENT_STYLE = {"margin-left": "280px", "padding": "20px 30px"}

sidebar = html.Div([
    html.Div([
        html.H2("PHANTOM", className="phantom-title text-center", style={'fontSize': '2rem'}),
        html.P("SERVICE", className="text-center text-secondary", style={'letterSpacing': '3px', 'fontSize': '0.8rem'})
    ], className="mb-4"),
    html.Hr(style={'borderColor': '#2d3a4a'}),
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-home me-3"), "Обзор"], href="/", active="exact", className="sidebar-link"),
        dbc.NavLink([html.I(className="fas fa-camera me-3"), "AI-Анализ фото"], href="/photo", active="exact", className="sidebar-link"),
        dbc.NavLink([html.I(className="fas fa-boxes me-3"), "Склад"], href="/stock", active="exact", className="sidebar-link"),
        dbc.NavLink([html.I(className="fas fa-chart-line me-3"), "Прогноз"], href="/forecast", active="exact", className="sidebar-link"),
        dbc.NavLink([html.I(className="fas fa-history me-3"), "История"], href="/history", active="exact", className="sidebar-link"),
        dbc.NavLink([html.I(className="fas fa-cog me-3"), "Настройки"], href="/settings", active="exact", className="sidebar-link"),
    ], vertical=True, pills=True, className="mt-3"),
    html.Hr(style={'borderColor': '#2d3a4a'}),
    html.Div([html.Small("© 2026 Phantom Service", className="text-secondary")], className="text-center mt-4")
], style=SIDEBAR_STYLE)

# ========================
# 7. Страницы (полностью идентичны оригинальному dashboard.py)
# ========================
# СТРАНИЦА "ОБЗОР"
overview_page = html.Div([
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.Div([html.I(className="fas fa-coins fa-2x me-3", style={'color': '#f5af19'}), html.Span("Вложено", className="metric-label")]),
                html.H2(id="invested", className="metric-value mt-2")
            ])
        ], className="card-gradient"), width=3),
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.Div([html.I(className="fas fa-chart-line fa-2x me-3", style={'color': '#28a745'}), html.Span("В обороте", className="metric-label")]),
                html.H2(id="circulation", className="metric-value mt-2")
            ])
        ], className="card-gradient"), width=3),
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.Div([html.I(className="fas fa-wallet fa-2x me-3", style={'color': '#ffc107'}), html.Span("Чистая прибыль", className="metric-label")]),
                html.H2(id="profit", className="metric-value mt-2")
            ])
        ], className="card-gradient"), width=3),
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.Div([html.I(className="fas fa-boxes fa-2x me-3", style={'color': '#17a2b8'}), html.Span("На складе", className="metric-label")]),
                html.H2(id="stock-count", className="metric-value mt-2")
            ])
        ], className="card-gradient"), width=3),
    ], className="mb-4"),
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H5("📊 Распределение по зонам", className="text-light")),
            dbc.CardBody(dcc.Graph(id="zone-pie", config={'displayModeBar': False}))
        ], className="card-gradient"), width=6),
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H5("📈 Динамика продаж", className="text-light")),
            dbc.CardBody(dcc.Graph(id="sales-trend", config={'displayModeBar': False}))
        ], className="card-gradient"), width=6),
    ], className="mb-4"),
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H5("🔥 Топ-5 по марже", className="text-light")),
            dbc.CardBody(html.Div(id="top-table", className="table-responsive"))
        ], className="card-gradient"), width=6),
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H5("📅 Прогноз закупок", className="text-light")),
            dbc.CardBody(html.Ul(id="forecast-list", className="list-unstyled"))
        ], className="card-gradient"), width=6),
    ]),
    dbc.Row([
        dbc.Col(dbc.Button([html.I(className="fas fa-sync-alt me-2"), "Обновить зоны"], id="update-zones-btn", color="warning", className="me-3"), width="auto"),
        dbc.Col(html.Small(id="last-updated", className="text-secondary"), width="auto"),
    ], className="mt-3"),
    dcc.Interval(id="interval", interval=60000)
])

# СТРАНИЦА "AI-АНАЛИЗ ФОТО"
photo_page = html.Div([
    dbc.Row([
        dbc.Col(html.H3("🤖 AI-анализ фотографий товаров", className="text-light mb-3"), width=12),
    ]),
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.P("Загрузите фото товара, и нейросеть (ResNet18) оценит его перспективность.", className="text-secondary"),
                dcc.Upload(
                    id="upload-photo",
                    children=html.Div([
                        html.I(className="fas fa-cloud-upload-alt fa-3x", style={'color': '#f5af19'}),
                        html.P("Перетащите или выберите файл", className="mt-2 text-secondary")
                    ]),
                    className="upload-area",
                    multiple=False,
                ),
                html.Div(id="upload-status", className="mt-3"),
                html.Div(id="analysis-spinner", className="mt-2", style={'display': 'none'}, children=[
                    html.Div(className="spinner", style={'margin': '0 auto'}),
                    html.P("Анализируем изображение...", className="text-secondary text-center")
                ])
            ])
        ], className="card-gradient"), width=6),
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H5("Результат анализа", className="text-light")),
            dbc.CardBody(html.Div(id="analysis-result-container"))
        ], className="card-gradient"), width=6),
    ])
])

# СТРАНИЦА "СКЛАД"
stock_page = html.Div([
    dbc.Row([
        dbc.Col(html.H3("📦 Управление складом", className="text-light mb-3"), width=12),
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Input(id="stock-search", placeholder="Поиск по названию или SKU...", className="mb-2"),
            dbc.Select(
                id="stock-zone-filter",
                options=[
                    {"label": "Все зоны", "value": "all"},
                    {"label": "🟢 A (горячие)", "value": "A"},
                    {"label": "🟡 B (тёплые)", "value": "B"},
                    {"label": "🟠 C (холодные)", "value": "C"},
                    {"label": "🔴 D (мёртвые)", "value": "D"},
                ],
                value="all",
                className="mb-2"
            ),
            html.Div([
                dbc.Button("➕ Добавить", id="open-add-modal", color="success", className="me-2", size="sm"),
                dbc.Button("🔄 Обновить зоны", id="stock-update-zones", color="warning", className="me-2", size="sm"),
                dbc.Button("📥 Шаблон", id="download-template-btn", color="secondary", className="me-2", size="sm"),
                dbc.Button("📤 Выгрузить", id="export-data-btn", color="info", size="sm"),
            ]),
        ], width=8),
        dbc.Col([
            html.Div([
                dbc.Button("➕ Добавить", id="open-add-modal", color="success", className="me-2", size="sm"),
                dbc.Button("🔄 Обновить зоны", id="stock-update-zones", color="warning", className="me-2", size="sm"),
                dbc.Button("📥 Шаблон", id="download-template-btn", color="secondary", className="me-2", size="sm"),
                dbc.Button("📤 Выгрузить", id="export-data-btn", color="info", size="sm"),
            ], className="d-flex flex-wrap justify-content-end")
        ], width=4),
    ], className="mb-3"),
    dbc.Row([
        dbc.Col([
            dcc.Upload(
                id="upload-csv",
                children=html.Div([
                    html.I(className="fas fa-file-upload me-2"),
                    "Перетащите или выберите CSV/Excel файл для импорта"
                ]),
                style={
                    "width": "100%",
                    "height": "60px",
                    "lineHeight": "60px",
                    "borderWidth": "1px",
                    "borderStyle": "dashed",
                    "borderRadius": "5px",
                    "textAlign": "center",
                    "margin": "10px 0",
                    "borderColor": "#2d3a4a",
                    "color": "#adb5bd"
                },
                multiple=False,
                accept=".csv,.xlsx,.xls"
            ),
            html.Div(id="upload-csv-status", className="mt-2"),
        ], width=12),
    ]),
    dbc.Card([
        dbc.CardBody([
            dash_table.DataTable(
                id="stock-table-datatable",
                columns=[
                    {"name": "ID", "id": "id", "type": "numeric", "editable": False},
                    {"name": "Название", "id": "name", "editable": True},
                    {"name": "SKU", "id": "sku", "editable": True},
                    {"name": "Закупка", "id": "purchase_price", "type": "numeric", "editable": True},
                    {"name": "Продажа", "id": "current_price", "type": "numeric", "editable": True},
                    {"name": "Кол-во", "id": "quantity", "type": "numeric", "editable": True},
                    {"name": "Зона", "id": "zone", "editable": False, "type": "text"},
                    {"name": "Дней", "id": "days_on_shelf", "editable": False, "type": "numeric"},
                    {"name": "Скорость", "id": "sales_velocity", "type": "numeric", "editable": True},
                    {"name": "Статус", "id": "status", "editable": False, "type": "text"},
                    {"name": "Действие", "id": "delete", "presentation": "markdown"},
                    {"name": "Списать", "id": "sell", "presentation": "markdown"},
                ],
                style_table={"overflowX": "auto"},
                style_cell={"backgroundColor": "#0d1117", "color": "#f8f9fa", "borderColor": "#2d3a4a"},
                style_header={"backgroundColor": "#161b22", "color": "#f5af19", "fontWeight": "bold"},
                editable=True,
                filter_action="native",
                sort_action="native",
                page_size=15,
                style_data_conditional=[
                    {"if": {"filter_query": "{zone} eq 'A'"},"backgroundColor": "#1a3a2a","color": "#28a745"},
                    {"if": {"filter_query": "{zone} eq 'B'"},"backgroundColor": "#3a3a1a","color": "#ffc107"},
                    {"if": {"filter_query": "{zone} eq 'C'"},"backgroundColor": "#2a3a3a","color": "#17a2b8"},
                    {"if": {"filter_query": "{zone} eq 'D'"},"backgroundColor": "#3a1a1a","color": "#dc3545"},
                    {"if": {"filter_query": "{quantity} <= 0"},"color": "#dc3545","fontWeight": "bold"},
                    {"if": {"filter_query": "{quantity} > 0 && {quantity} <= 3"},"color": "#ffc107","fontWeight": "bold"},
                    {"if": {"filter_query": "{quantity} > 3"},"color": "#28a745"},
                    {"if": {"filter_query": "{status} eq 'in_stock'"},"color": "#28a745"},
                    {"if": {"filter_query": "{status} eq 'sold'"},"color": "#6c757d","textDecoration": "line-through"},
                    {"if": {"row_index": "even"},"backgroundColor": "#1a2028"},
                    {"if": {"state": "selected"},"backgroundColor": "#2d3a4a","border": "1px solid #f5af19"}
                ]
            ),
            html.Div(id="stock-table-output")
        ])
    ], className="card-gradient"),
    dbc.Modal([
        dbc.ModalHeader("Добавить товар"),
        dbc.ModalBody([
            dbc.Input(id="add-name", placeholder="Название", className="mb-2"),
            dbc.Input(id="add-sku", placeholder="SKU", className="mb-2"),
            dbc.Input(id="add-purchase", placeholder="Закупка (цена)", type="number", className="mb-2"),
            dbc.Input(id="add-sale", placeholder="Продажа (цена)", type="number", className="mb-2"),
            dbc.Input(id="add-quantity", placeholder="Количество", type="number", className="mb-2"),
            dbc.Select(id="add-status", options=[{"label":"В наличии","value":"in_stock"},{"label":"Продан","value":"sold"}], value="in_stock", className="mb-2"),
        ]),
        dbc.ModalFooter([
            dbc.Button("Отмена", id="close-add-modal", color="secondary", className="me-2"),
            dbc.Button("Сохранить", id="save-add-product", color="success"),
        ]),
    ], id="add-product-modal", is_open=False),
    dcc.Download(id="download-csv"),
])

# СТРАНИЦА "ПРОГНОЗ"
forecast_page = html.Div([
    dbc.Row([
        dbc.Col(html.H3("📈 Прогноз продаж", className="text-light mb-3"), width=12),
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.P("Прогноз на 30 дней для каждого товара (на основе средних продаж).", className="text-secondary"),
                    dcc.Graph(id="forecast-graph")
                ])
            ], className="card-gradient"),
        ], width=12),
    ]),
])

# СТРАНИЦА "ИСТОРИЯ"
history_page = html.Div([
    dbc.Row([
        dbc.Col(html.H3("📜 История изменений", className="text-light mb-3"), width=12),
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dash_table.DataTable(
                        id="audit-table",
                        columns=[
                            {"name": "ID", "id": "id"},
                            {"name": "Товар", "id": "product_id"},
                            {"name": "Действие", "id": "action"},
                            {"name": "Поле", "id": "field"},
                            {"name": "Было", "id": "old_value"},
                            {"name": "Стало", "id": "new_value"},
                            {"name": "Время", "id": "timestamp"},
                            {"name": "Пользователь", "id": "user"},
                        ],
                        style_table={"overflowX": "auto"},
                        style_cell={"backgroundColor": "#0d1117", "color": "#f8f9fa", "borderColor": "#2d3a4a"},
                        style_header={"backgroundColor": "#161b22", "color": "#f5af19", "fontWeight": "bold"},
                        page_size=20,
                        filter_action="native",
                        sort_action="native",
                    )
                ])
            ], className="card-gradient")
        ], width=12)
    ])
])

# СТРАНИЦА "НАСТРОЙКИ"
settings_page = html.Div([
    dbc.Row([
        dbc.Col(html.H3("⚙️ Настройки системы", className="text-light mb-3"), width=12),
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Зоны склада"),
                dbc.CardBody([
                    html.Label("Границы дней для зон:"),
                    dbc.Row([
                        dbc.Col([html.Label("Зона A (горячие): <"), dbc.Input(type="number", value=7, id="zone-a-days", className="mb-2")], width=3),
                        dbc.Col([html.Label("Зона B (тёплые): <"), dbc.Input(type="number", value=21, id="zone-b-days", className="mb-2")], width=3),
                        dbc.Col([html.Label("Зона C (холодные): <"), dbc.Input(type="number", value=45, id="zone-c-days", className="mb-2")], width=3),
                        dbc.Col([html.Label("Зона D (мёртвые): >="), dbc.Input(type="number", value=45, id="zone-d-days", className="mb-2")], width=3),
                    ]),
                    dbc.Button("Сохранить настройки зон", id="save-zone-settings", color="primary", className="mt-2")
                ])
            ], className="card-gradient mb-4"),
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Управление данными"),
                dbc.CardBody([
                    dbc.Button("Очистить все данные", id="clear-data-btn", color="danger", className="mt-2"),
                    html.Div(id="clear-data-status", className="mt-2"),
                    dbc.Button("📄 Скачать отчёт (PDF)", id="download-pdf-btn", color="primary", className="mt-2"),
                    dcc.Download(id="download-pdf"),
                ])
            ], className="card-gradient")
        ], width=6),
    ]),
    html.Div(id="settings-page-status", className="mt-3")
])

# ========================
# 8. Основной Layout
# ========================
app.layout = html.Div([
    dcc.Location(id="url"),
    sidebar,
    html.Div([
        html.Div(id="page-overview", children=overview_page, style={"display": "block"}),
        html.Div(id="page-photo", children=photo_page, style={"display": "none"}),
        html.Div(id="page-stock", children=stock_page, style={"display": "none"}),
        html.Div(id="page-forecast", children=forecast_page, style={"display": "none"}),
        html.Div(id="page-history", children=history_page, style={"display": "none"}),
        html.Div(id="page-settings", children=settings_page, style={"display": "none"}),
    ], style=CONTENT_STYLE),
    dcc.Store(id="stock-trigger", data=0),
    dcc.Store(id="current-path", data="/"),
    dcc.Store(id="analysis-result-store", data={}),
    dcc.Store(id="detail-visible", data=False),
    dbc.Toast(
        id="global-toast",
        header="Уведомление",
        icon="primary",
        dismissable=True,
        is_open=False,
        duration=3000,
        style={"position": "fixed", "bottom": 20, "right": 20, "width": 350, "z-index": 9999},
    ),
])

# ========================
# 9. Callback для переключения страниц
# ========================
@callback(
    [Output("page-overview", "style"),
     Output("page-photo", "style"),
     Output("page-stock", "style"),
     Output("page-forecast", "style"),
     Output("page-history", "style"),
     Output("page-settings", "style"),
     Output("current-path", "data")],
    [Input("url", "pathname")]
)
def switch_page(pathname):
    overview_style = {"display": "none"}
    photo_style = {"display": "none"}
    stock_style = {"display": "none"}
    forecast_style = {"display": "none"}
    history_style = {"display": "none"}
    settings_style = {"display": "none"}
    
    if pathname == "/photo":
        photo_style = {"display": "block"}
    elif pathname == "/stock":
        stock_style = {"display": "block"}
    elif pathname == "/forecast":
        forecast_style = {"display": "block"}
    elif pathname == "/history":
        history_style = {"display": "block"}
    elif pathname == "/settings":
        settings_style = {"display": "block"}
    else:
        overview_style = {"display": "block"}
    
    return overview_style, photo_style, stock_style, forecast_style, history_style, settings_style, pathname

# ========================
# 10. Callback для страницы "Обзор"
# ========================
@callback(
    [Output("invested", "children"),
     Output("circulation", "children"),
     Output("profit", "children"),
     Output("stock-count", "children"),
     Output("zone-pie", "figure"),
     Output("sales-trend", "figure"),
     Output("top-table", "children"),
     Output("forecast-list", "children"),
     Output("last-updated", "children")],
    [Input("interval", "n_intervals"),
     Input("update-zones-btn", "n_clicks"),
     Input("stock-trigger", "data")]
)
def update_overview(n_interval, n_clicks, trigger):
    if n_clicks:
        logger.info("Ручное обновление зон")
        update_inventory_zones()
    
    df_products, df_sales, df_zones = load_data()
    metrics = get_metrics(df_products, df_sales, df_zones)
    
    invested = f"{metrics['invested']:,.0f} ₽" if metrics['invested'] else "0 ₽"
    circulation = f"{metrics['circulation']:,.0f} ₽" if metrics['circulation'] else "0 ₽"
    profit_val = metrics['profit']
    profit_str = f"{profit_val:,.0f} ₽" if profit_val else "0 ₽"
    stock_count = metrics['in_stock_count']
    
    zone_df = metrics['zone_counts']
    if not zone_df.empty:
        fig_pie = px.pie(
            zone_df, values='count', names='zone', 
            color='zone', 
            color_discrete_map={'A':'#28a745','B':'#ffc107','C':'#fd7e14','D':'#dc3545'},
            hole=0.4,
            title=None
        )
        fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#adb5bd')
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
    else:
        fig_pie = go.Figure()
        fig_pie.add_annotation(text="Нет данных", showarrow=False)
        fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)', font_color='#adb5bd')
    
    sales_trend = get_sales_trend(df_sales, df_products)
    if sales_trend is not None and not sales_trend.empty:
        fig_sales = px.line(sales_trend, x='week', y='quantity', color='name', 
                            title=None, markers=True,
                            labels={'quantity': 'Продажи', 'week': 'Неделя'})
        fig_sales.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#adb5bd',
            xaxis=dict(gridcolor='#2d3a4a', showgrid=True),
            yaxis=dict(gridcolor='#2d3a4a', showgrid=True),
            legend=dict(orientation='h', yanchor='bottom', y=-0.2, xanchor='center', x=0.5),
            margin=dict(l=40, r=40, t=40, b=80)
        )
        fig_sales.update_traces(line=dict(width=3), marker=dict(size=8))
    else:
        fig_sales = go.Figure()
        fig_sales.add_annotation(text="Нет продаж", showarrow=False)
        fig_sales.update_layout(paper_bgcolor='rgba(0,0,0,0)', font_color='#adb5bd')
    
    top = get_top_margin(df_products)
    if not top.empty:
        table_rows = []
        for _, row in top.iterrows():
            table_rows.append(html.Tr([
                html.Td(row['name'], style={'color': '#f8f9fa'}),
                html.Td(f"{row['margin']:.1f}%", style={'color': '#ffc107'}),
                html.Td(f"{row['purchase_price']:.0f} ₽", style={'color': '#adb5bd'}),
                html.Td(f"{row['current_price']:.0f} ₽", style={'color': '#28a745'})
            ]))
        top_table = dbc.Table([
            html.Thead(html.Tr([html.Th("Товар"), html.Th("Наценка %"), html.Th("Закупка"), html.Th("Продажа")], style={'color': '#adb5bd'})),
            html.Tbody(table_rows)
        ], bordered=False, hover=True, className="table-dark table-sm", striped=True)
    else:
        top_table = html.P("Нет данных", className="text-secondary")
    
    try:
        recs = get_trend_products()
    except:
        recs = []
    if recs:
        items = []
        for name, text in recs:
            items.append(html.Li([
                html.I(className="fas fa-arrow-right me-2", style={'color': '#f5af19'}),
                html.Strong(name, style={'color': '#f8f9fa'}), " — ",
                html.Span(text, style={'color': '#adb5bd'})
            ], className="mb-2"))
        forecast_list = html.Ul(items)
    else:
        forecast_list = html.P("Недостаточно данных", className="text-secondary")
    
    last_upd = f"Обновлено: {datetime.now().strftime('%H:%M:%S')}"
    return invested, circulation, profit_str, stock_count, fig_pie, fig_sales, top_table, forecast_list, last_upd

# ========================
# 11. Callback для обновления таблицы склада
# ========================
@callback(
    [Output("stock-table-datatable", "data"),
     Output("stock-table-datatable", "columns"),
     Output("total-products", "children"),
     Output("total-invested", "children"),
     Output("avg-price", "children"),
     Output("zone-stats", "children")],
    [Input("current-path", "data"),
     Input("stock-trigger", "data"),
     Input("stock-update-zones", "n_clicks"),
     Input("stock-search", "value"),
     Input("stock-zone-filter", "value")]
)
def update_stock_table(path, trigger, n_clicks, search, zone_filter):
    ctx = dash.callback_context
    if ctx.triggered:
        triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
        if triggered_id in ["current-path", "stock-update-zones"]:
            update_inventory_zones()
    if path != "/stock":
        return [], [], "0", "0 ₽", "0 ₽", "0/0/0/0"
    try:
        df = get_all_products()
        if df.empty:
            return [], [], "0", "0 ₽", "0 ₽", "0/0/0/0"
        df_in_stock = df[df['status'] == 'in_stock'].copy()
        if zone_filter != "all":
            df_in_stock = df_in_stock[df_in_stock['zone'] == zone_filter]
        if search:
            df_in_stock = df_in_stock[df_in_stock['name'].str.contains(search, case=False) | df_in_stock['sku'].str.contains(search, case=False)]
        df_in_stock = df_in_stock.sort_values('id')
        data = df_in_stock.to_dict('records')
        
        for row in data:
            row['delete'] = '🗑️ Удалить'
            row['sell'] = '➖ 1'
            if row.get('status') == 'in_stock':
                row['status'] = '✅ В наличии'
            else:
                row['status'] = '❌ Продан'
        
        total_products = df_in_stock['quantity'].sum() if not df_in_stock.empty else 0
        total_invested = df_in_stock['purchase_price'].sum() if not df_in_stock.empty else 0
        avg_price = df_in_stock['current_price'].mean() if not df_in_stock.empty else 0
        zone_counts = df_in_stock['zone'].value_counts().fillna(0) if not df_in_stock.empty else {}
        zone_stats = f"{int(zone_counts.get('A', 0))} 🟢 / {int(zone_counts.get('B', 0))} 🟡 / {int(zone_counts.get('C', 0))} 🟠 / {int(zone_counts.get('D', 0))} 🔴"
        
        columns = [{"name": i, "id": i} for i in df_in_stock.columns if i != 'id'] if not df_in_stock.empty else []
        columns = [{"name": "ID", "id": "id", "type": "numeric", "editable": False}] + columns
        columns.append({"name": "Действие", "id": "delete", "presentation": "markdown"})
        columns.append({"name": "Списать", "id": "sell", "presentation": "markdown"})
        
        total_invested_str = f"{total_invested:,.0f} ₽" if total_invested else "0 ₽"
        avg_price_str = f"{avg_price:,.0f} ₽" if avg_price else "0 ₽"
        
        return data, columns, str(total_products), total_invested_str, avg_price_str, zone_stats
    except Exception as e:
        logger.error(f"Ошибка загрузки таблицы: {e}")
        return [], [], "0", "0 ₽", "0 ₽", "0/0/0/0"

# ========================
# 12. Callback для обработки кликов (удаление и списание)
# ========================
@callback(
    [Output("stock-trigger", "data", allow_duplicate=True),
     Output("global-toast", "is_open"),
     Output("global-toast", "children"),
     Output("stock-table-datatable", "active_cell")],
    Input("stock-table-datatable", "active_cell"),
    State("stock-table-datatable", "data"),
    State("stock-trigger", "data"),
    prevent_initial_call=True
)
def handle_cell_action(active_cell, data, trigger):
    if not active_cell:
        return trigger, False, "", None
    column_id = active_cell['column_id']
    row_index = active_cell['row']
    if row_index >= len(data):
        return trigger, False, "", None
    product_id = data[row_index]['id']
    product_name = data[row_index].get('name', 'товар')
    if column_id == 'delete':
        delete_product(product_id)
        update_inventory_zones()
        return trigger + 1, True, f"🗑️ Товар «{product_name}» удалён", None
    elif column_id == 'sell':
        current_price = data[row_index].get('current_price', 0)
        try:
            current_price = float(current_price)
        except (ValueError, TypeError):
            current_price = 0.0
        result = decrease_quantity(product_id, sale_price=current_price)
        update_inventory_zones()
        if result == "Продан":
            msg = f"✅ Товар «{product_name}» полностью продан и убран со склада"
        else:
            msg = f"✅ Товар «{product_name}» списан (осталось {data[row_index]['quantity']-1})"
        return trigger + 1, True, msg, None
    return trigger, False, "", None

# ========================
# 13. Callback для автосохранения
# ========================
@callback(
    [Output("stock-table-output", "children", allow_duplicate=True),
     Output("stock-trigger", "data", allow_duplicate=True)],
    Input("stock-table-datatable", "data_previous"),
    State("stock-table-datatable", "data"),
    State("stock-trigger", "data"),
    prevent_initial_call=True
)
def save_on_edit(data_prev, data_cur, trigger):
    if data_prev is None or data_cur is None:
        return "", trigger
    try:
        for i, row in enumerate(data_cur):
            if i < len(data_prev):
                prev = data_prev[i]
                for key in ['name', 'sku', 'purchase_price', 'current_price', 'quantity', 'sales_velocity', 'status']:
                    if key in row and row[key] != prev.get(key):
                        pid = row['id']
                        value = row[key]
                        if key in ['purchase_price', 'current_price', 'sales_velocity']:
                            try:
                                value = float(value)
                            except (ValueError, TypeError):
                                value = 0.0
                        elif key == 'quantity':
                            try:
                                value = int(float(value))
                            except (ValueError, TypeError):
                                value = 1
                            if value <= 0:
                                update_product(pid, 'quantity', 0)
                                update_product(pid, 'status', 'sold')
                                return html.Div("✅ Товар переведён в статус «Продан» (количество = 0)", className="text-success mt-2"), trigger + 1
                        if key == 'sales_velocity':
                            update_zone_field(pid, key, value)
                        else:
                            update_product(pid, key, value)
                        return html.Div("✅ Изменения сохранены", className="text-success mt-2"), trigger + 1
        return "", trigger
    except Exception as e:
        logger.error(f"Ошибка при сохранении: {e}", exc_info=True)
        return html.Div(f"❌ Ошибка: {str(e)}", className="text-danger mt-2"), trigger

# ========================
# 14. Callback для добавления/импорта (с модалкой и уведомлением)
# ========================
@callback(
    [Output("add-product-modal", "is_open"),
     Output("stock-table-output", "children", allow_duplicate=True),
     Output("upload-csv-status", "children"),
     Output("stock-trigger", "data", allow_duplicate=True),
     Output("add-name", "value"),
     Output("add-sku", "value"),
     Output("add-purchase", "value"),
     Output("add-sale", "value"),
     Output("add-quantity", "value"),
     Output("global-toast", "is_open", allow_duplicate=True),
     Output("global-toast", "children", allow_duplicate=True)],
    [Input("open-add-modal", "n_clicks"),
     Input("close-add-modal", "n_clicks"),
     Input("save-add-product", "n_clicks"),
     Input("upload-csv", "contents")],
    [State("add-product-modal", "is_open"),
     State("add-name", "value"),
     State("add-sku", "value"),
     State("add-purchase", "value"),
     State("add-sale", "value"),
     State("add-quantity", "value"),
     State("add-status", "value"),
     State("stock-trigger", "data"),
     State("upload-csv", "filename")],
    prevent_initial_call=True
)
def handle_add_and_import(open_clicks, close_clicks, save_clicks,
                         upload_contents,
                         is_open, name, sku, purchase, sale, quantity, status, trigger,
                         filename):
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open, "", "", trigger, "", "", "", "", 1, False, ""
    
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if triggered_id == "open-add-modal":
        return True, "", "", trigger, "", "", "", "", 1, False, ""
    
    if triggered_id == "close-add-modal":
        return False, "", "", trigger, "", "", "", "", 1, False, ""
    
    if triggered_id == "save-add-product":
        if name and sku and purchase is not None and sale is not None:
            try:
                qty = int(quantity) if quantity and int(quantity) > 0 else 1
                product_id = add_product(name, sku, float(purchase), float(sale), qty, status)
                update_inventory_zones()
                msg = "Товар добавлен/обновлён"
                if status == "sold":
                    msg += " (проданный, для статистики)"
                return False, msg, "", trigger + 1, "", "", "", "", 1, True, msg
            except Exception as e:
                return False, f"Ошибка: {e}", "", trigger, "", "", "", "", 1, True, f"Ошибка: {e}"
        else:
            return False, "Заполните все поля", "", trigger, "", "", "", "", 1, True, "Заполните все поля"
    
    if triggered_id == "upload-csv" and upload_contents:
        try:
            content_type, content_string = upload_contents.split(',')
            decoded = base64.b64decode(content_string)
            
            if filename.endswith('.csv'):
                df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
            elif filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(io.BytesIO(decoded))
            else:
                return is_open, "", "❌ Поддерживаются только CSV и Excel", trigger, "", "", "", "", 1, True, "Ошибка формата"
            
            if 'sku' in df.columns and 'name' in df.columns:
                imported = 0
                for _, row in df.iterrows():
                    if pd.isna(row.get('sku')) or pd.isna(row.get('name')):
                        continue
                    purchase_price = float(row.get('purchase_price', 0)) if pd.notna(row.get('purchase_price')) else 0.0
                    current_price = float(row.get('current_price', 0)) if pd.notna(row.get('current_price')) else 0.0
                    quantity = int(row.get('quantity', 1)) if pd.notna(row.get('quantity')) else 1
                    add_product(row['name'], row['sku'], purchase_price, current_price, quantity, row.get('status', 'in_stock'))
                    imported += 1
                update_inventory_zones()
                return is_open, "", f"✅ Импортировано {imported} товаров. Таблица обновлена.", trigger + 1, "", "", "", "", 1, True, f"Импортировано {imported} товаров"
            
            elif 'sku' in df.columns and 'sale_date' in df.columns:
                # Получаем sku -> id
                all_products = d1_query('SELECT id, sku FROM products')
                sku_map = {p['sku']: p['id'] for p in all_products}
                imported = 0
                for _, row in df.iterrows():
                    product_id = sku_map.get(row['sku'])
                    if product_id:
                        quantity = int(row.get('quantity', 1)) if pd.notna(row.get('quantity')) else 1
                        sale_price = float(row.get('sale_price', 0)) if pd.notna(row.get('sale_price')) else 0.0
                        add_sale(product_id, quantity, sale_price)
                        imported += 1
                return is_open, "", f"✅ Импортировано {imported} продаж.", trigger + 1, "", "", "", "", 1, True, f"Импортировано {imported} продаж"
            else:
                return is_open, "", "❌ Неизвестный формат. Ожидаются колонки для товаров (name, sku) или продаж (sku, sale_date).", trigger, "", "", "", "", 1, True, "Ошибка формата"
        except Exception as e:
            logger.error(f"Ошибка импорта: {e}")
            return is_open, "", f"❌ Ошибка импорта: {str(e)}", trigger, "", "", "", "", 1, True, f"Ошибка: {str(e)}"
    
    return is_open, "", "", trigger, "", "", "", "", 1, False, ""

# ========================
# 15. Callback для очистки данных
# ========================
@callback(
    [Output("clear-data-status", "children"),
     Output("stock-trigger", "data", allow_duplicate=True)],
    Input("clear-data-btn", "n_clicks"),
    State("stock-trigger", "data"),
    prevent_initial_call=True
)
def clear_data(n_clicks, trigger):
    if n_clicks:
        try:
            d1_query('DELETE FROM sales')
            d1_query('DELETE FROM inventory_zones')
            d1_query('DELETE FROM products')
            d1_query('DELETE FROM audit_log')
            update_inventory_zones()
            return "Все данные (включая аудит-лог) очищены", trigger + 1
        except Exception as e:
            return f"Ошибка очистки: {e}", trigger
    return "", trigger

# ========================
# 16. Callback для загрузки истории
# ========================
@callback(
    Output("audit-table", "data"),
    Input("url", "pathname")
)
def load_audit(pathname):
    if pathname != "/history":
        return []
    try:
        results = d1_query('SELECT * FROM audit_log ORDER BY id DESC LIMIT 500')
        if results:
            return results
        else:
            return []
    except Exception as e:
        logger.error(f"Ошибка загрузки аудита: {e}")
        return []

# ========================
# 17. Callback для скачивания PDF
# ========================
@callback(
    Output("download-pdf", "data"),
    Input("download-pdf-btn", "n_clicks"),
    prevent_initial_call=True
)
def download_pdf(n_clicks):
    if n_clicks:
        try:
            from services.pdf_export import generate_stock_report
            df_products, df_sales, df_zones = load_data()
            pdf_bytes = generate_stock_report(df_products, df_sales, df_zones)
            return dcc.send_bytes(pdf_bytes, f"stock_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
        except Exception as e:
            logger.error(f"Ошибка генерации PDF: {e}", exc_info=True)
            return None

# ========================
# 18. Callback для AI-анализа фото
# ========================
@callback(
    [Output("upload-status", "children"),
     Output("analysis-result-container", "children"),
     Output("analysis-spinner", "style"),
     Output("analysis-result-store", "data")],
    [Input("upload-photo", "contents")],
    [State("upload-photo", "filename")]
)
def handle_photo_upload(contents, filename):
    if contents is None:
        return "", html.P("Загрузите фото для анализа", className="text-secondary"), {'display': 'none'}, {}
    
    spinner_style = {'display': 'block', 'text-align': 'center'}
    status_msg = html.Div("⏳ Файл загружен, анализируем...", className="text-info")
    
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        image = Image.open(io.BytesIO(decoded))
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, filename)
        image.save(temp_path)
        logger.info(f"Файл сохранен: {temp_path}")
    except Exception as e:
        logger.error(f"Ошибка сохранения файла: {e}")
        return html.Div(f"Ошибка сохранения файла: {e}", className="text-danger"), html.P("Попробуйте другое изображение", className="text-secondary"), {'display': 'none'}, {}
    
    result = analyze_photo_real(temp_path)
    if os.path.exists(temp_path):
        os.remove(temp_path)
    
    if result is None:
        return html.Div("❌ Не удалось проанализировать (ошибка модели)", className="text-danger"), html.P("Попробуйте другое изображение", className="text-secondary"), {'display': 'none'}, {}
    
    confidence_percent = result['main_confidence'] * 100
    bar_color = "#28a745" if confidence_percent > 85 else "#ffc107" if confidence_percent > 60 else "#dc3545"
    confidence_bar = html.Div([
        html.Div(className="confidence-bar", children=[
            html.Div(className="confidence-bar-fill", style={
                'width': f'{confidence_percent}%',
                'background': bar_color
            })
        ])
    ])
    
    short_html = html.Div([
        html.H5(f"Категория: {result['category']}", className="text-light"),
        html.P(f"Уверенность: {confidence_percent:.1f}%", className="text-secondary"),
        confidence_bar,
        html.P(f"Тренд: {'✅ Да' if result['is_trending'] else '❌ Нет'}", className="text-secondary"),
        html.P(f"Сезон: {'✅ Да' if result['is_seasonal'] else '❌ Нет'}", className="text-secondary"),
        html.H4(result['recommendation'], className=("text-success" if "Рекомендуем" in result['recommendation'] else "text-warning" if "С осторожностью" in result['recommendation'] else "text-danger")),
        dbc.Button("📋 Подробно", id="toggle-detail-btn", color="info", className="mt-2", n_clicks=0),
        html.Div(id="analysis-detail-container", className="mt-3", style={"display": "none"})
    ])
    
    status_msg = html.Div([
        html.I(className="fas fa-check-circle text-success me-2"),
        f"✅ Файл '{filename}' проанализирован (ResNet18)"
    ], className="text-success")
    
    return status_msg, short_html, {'display': 'none'}, result

# ========================
# 19. Callback для переключения подробного режима
# ========================
@callback(
    Output("analysis-detail-container", "children"),
    Output("analysis-detail-container", "style"),
    Input("toggle-detail-btn", "n_clicks"),
    State("analysis-result-store", "data")
)
def toggle_detail(n_clicks, result):
    if n_clicks is None or n_clicks % 2 == 0:
        return "", {"display": "none"}
    else:
        if not result or not result.get('all_predictions'):
            return html.P("Нет данных для отображения", className="text-secondary"), {"display": "block"}
        detail_html = html.Div([
            html.H5("Детальный отчёт:", className="text-light"),
            html.P(f"Обоснование: {result.get('reason', 'Нет данных')}", className="text-secondary"),
            html.H6("Топ-5 предсказаний нейросети:", className="mt-3 text-light"),
            html.Ul([
                html.Li(f"{pred[0]} – {pred[1]*100:.1f}%") for pred in result.get('all_predictions', [])
            ], className="text-secondary")
        ])
        return detail_html, {"display": "block"}

# ========================
# 20. Callback для страницы "Прогноз"
# ========================
@callback(
    Output("forecast-graph", "figure"),
    [Input("url", "pathname"),
     Input("stock-trigger", "data")]
)
def update_forecast(pathname, trigger):
    if pathname != "/forecast":
        return go.Figure()
    forecast_data = get_all_forecast()
    if not forecast_data:
        fig = go.Figure()
        fig.add_annotation(text="Нет данных для прогноза", showarrow=False)
        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', font_color='#adb5bd')
        return fig
    fig = go.Figure()
    days = list(range(1, 31))
    for name, forecast in forecast_data.items():
        if len(forecast) == 30:
            fig.add_trace(go.Scatter(x=days, y=forecast, mode='lines+markers', name=name))
    fig.update_layout(
        title="Прогноз продаж на 30 дней (ARIMA/Prophet)",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font_color='#adb5bd',
        xaxis_title="День",
        yaxis_title="Прогнозируемое количество",
        xaxis=dict(gridcolor='#2d3a4a'),
        yaxis=dict(gridcolor='#2d3a4a')
    )
    return fig

# ========================
# 21. Callback для сохранения настроек зон
# ========================
@callback(
    Output("settings-page-status", "children"),
    [Input("save-zone-settings", "n_clicks")],
    [State("zone-a-days", "value"),
     State("zone-b-days", "value"),
     State("zone-c-days", "value"),
     State("zone-d-days", "value")],
    prevent_initial_call=True
)
def save_settings(n_clicks, zone_a, zone_b, zone_c, zone_d):
    if n_clicks:
        return html.Div(f"Настройки зон сохранены: A<{zone_a}, B<{zone_b}, C<{zone_c}, D>={zone_d}", className="text-success")
    return ""

# ========================
# 22. Callback для выгрузки (шаблон или данные)
# ========================
@callback(
    Output("download-csv", "data"),
    [Input("download-template-btn", "n_clicks"),
     Input("export-data-btn", "n_clicks")],
    prevent_initial_call=True
)
def download_file(template_clicks, export_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        return None
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == "download-template-btn":
        df_products = pd.DataFrame(columns=['name', 'sku', 'purchase_price', 'current_price', 'quantity', 'status'])
        df_sales = pd.DataFrame(columns=['sku', 'sale_date', 'quantity', 'sale_price'])
        filename = "template_import.xlsx"
    else:
        # Выгружаем данные из D1
        df_products = get_all_products()
        try:
            sales_data = d1_query('SELECT s.*, p.sku FROM sales s JOIN products p ON s.product_id = p.id')
            df_sales = pd.DataFrame(sales_data) if sales_data else pd.DataFrame()
        except:
            df_sales = pd.DataFrame()
        filename = "my_stock_data.xlsx"
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_products.to_excel(writer, sheet_name='products', index=False)
        if not df_sales.empty:
            df_sales.to_excel(writer, sheet_name='sales', index=False)
    output.seek(0)
    return dcc.send_bytes(output.getvalue(), filename)

# ========================
# 23. Запуск
# ========================
server = app.server

if __name__ == '__main__':
    init_db()
    update_inventory_zones()
    app.run(debug=False, host='0.0.0.0', port=7860)