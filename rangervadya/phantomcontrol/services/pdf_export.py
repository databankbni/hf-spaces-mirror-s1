from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import pandas as pd
import io
from datetime import datetime
import os

# Регистрируем шрифт, поддерживающий кириллицу
try:
    # Пытаемся загрузить системный шрифт Arial или Helvetica
    # На macOS обычно есть /System/Library/Fonts/Supplemental/Arial.ttf
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    if not os.path.exists(font_path):
        # Fallback для Linux
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('Arial', font_path))
        default_font = 'Arial'
    else:
        # Используем встроенный Helvetica (не поддерживает кириллицу, но не будет ошибок)
        default_font = 'Helvetica'
except:
    default_font = 'Helvetica'

def generate_stock_report(df_products, df_sales, df_zones):
    """Генерирует PDF-отчёт и возвращает bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    
    # Создаём стили с явным указанием шрифта
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=16, textColor=colors.black, fontName=default_font)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=12, textColor=colors.black, fontName=default_font)
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontName=default_font)

    elements = []

    # Заголовок
    elements.append(Paragraph("Отчёт по складу", title_style))
    elements.append(Paragraph(f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    # Таблица товаров
    elements.append(Paragraph("Товары", heading_style))
    if not df_products.empty:
        data = [["ID", "Название", "SKU", "Закупка", "Продажа", "Кол-во", "Статус"]]
        for _, row in df_products.iterrows():
            data.append([
                str(row['id']),
                row['name'],
                row['sku'],
                f"{row['purchase_price']:.0f}",
                f"{row['current_price']:.0f}",
                str(row['quantity']),
                row['status']
            ])
        table = Table(data, colWidths=[1*cm, 4*cm, 2.5*cm, 2*cm, 2*cm, 1.5*cm, 2.5*cm])
        table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), default_font),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.black),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), default_font),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("Нет товаров", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    # Таблица продаж
    elements.append(Paragraph("Продажи", heading_style))
    if not df_sales.empty and not df_products.empty:
        df_sales_merged = df_sales.merge(df_products[['id', 'sku', 'name']], left_on='product_id', right_on='id', how='left')
        data_sales = [["Товар", "SKU", "Дата", "Кол-во", "Цена"]]
        for _, row in df_sales_merged.iterrows():
            data_sales.append([
                row.get('name', ''),
                row.get('sku', ''),
                row['sale_date'][:10] if isinstance(row['sale_date'], str) else str(row['sale_date'])[:10],
                str(row['quantity']),
                f"{row['sale_price']:.0f}"
            ])
        table_sales = Table(data_sales, colWidths=[3*cm, 2.5*cm, 3*cm, 2*cm, 2.5*cm])
        table_sales.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), default_font),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.black),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), default_font),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ]))
        elements.append(table_sales)
    else:
        elements.append(Paragraph("Нет продаж", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    # Зоны
    elements.append(Paragraph("Зоны склада", heading_style))
    if not df_zones.empty and not df_products.empty:
        df_zones_merged = df_zones.merge(df_products[['id', 'name']], left_on='product_id', right_on='id', how='left')
        data_zones = [["Товар", "Зона", "Дней", "Скорость"]]
        for _, row in df_zones_merged.iterrows():
            data_zones.append([
                row.get('name', str(row['product_id'])),
                row['zone'],
                str(row['days_on_shelf']),
                f"{row['sales_velocity']:.2f}" if row['sales_velocity'] else "0"
            ])
        table_zones = Table(data_zones, colWidths=[4*cm, 2*cm, 2*cm, 2.5*cm])
        table_zones.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), default_font),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.black),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), default_font),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ]))
        elements.append(table_zones)
    else:
        elements.append(Paragraph("Нет данных о зонах", normal_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()