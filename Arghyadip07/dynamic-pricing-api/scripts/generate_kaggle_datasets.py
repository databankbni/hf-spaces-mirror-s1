import pandas as pd
import numpy as np
import os

def generate_inventory_dataset():
    """Simulate the Retail Store Inventory Forecasting dataset."""
    np.random.seed(42)
    n_rows = 50000
    
    dates = pd.date_range(start='2025-01-01', periods=365, freq='D')
    products = [f"PROD_{i}" for i in range(1, 21)]
    
    data = []
    for _ in range(n_rows):
        product = np.random.choice(products)
        date = np.random.choice(dates)
        
        # Base price and competitor
        base_price = np.random.uniform(50, 500)
        competitor_price = base_price * np.random.uniform(0.85, 1.15)
        
        # High elasticity demand
        price_ratio = base_price / competitor_price
        demand = int(max(0.0, np.random.normal(50, 15) * np.exp(-3.0 * (price_ratio - 1.0))))
        
        # Inventory mechanics
        inventory = int(np.random.uniform(10, 2000))
        if inventory < demand:
            demand = inventory # stockout
            
        data.append({
            "Date": date,
            "ProductID": product,
            "Price": round(base_price, 2),
            "CompetitorPrice": round(competitor_price, 2),
            "InventoryLevel": inventory,
            "SalesQty": demand
        })
        
    df = pd.DataFrame(data)
    os.makedirs("data/raw/kaggle_inventory", exist_ok=True)
    df.to_csv("data/raw/kaggle_inventory/retail_store_inventory.csv", index=False)
    print("Generated Retail Store Inventory dataset.")

def generate_pricing_dataset():
    """Simulate the Retail Pricing & Demand Signals dataset."""
    np.random.seed(99)
    n_rows = 50000
    
    data = []
    for _ in range(n_rows):
        timestamp = pd.Timestamp('2025-01-01') + pd.Timedelta(minutes=np.random.randint(0, 500000))
        item_code = f"ITEM_{np.random.randint(100, 200)}"
        
        # Highly competitive pricing signals
        comp_price = np.random.uniform(20, 150)
        my_price = comp_price * np.random.uniform(0.9, 1.2)
        
        # Price gap directly affects demand signals
        gap = my_price - comp_price
        signal_strength = np.exp(-0.2 * gap)
        demand = int(max(0.0, np.random.poisson(30) * signal_strength))
        
        stock = int(np.random.exponential(500))
        
        data.append({
            "timestamp": timestamp,
            "item_code": item_code,
            "current_price": round(my_price, 2),
            "comp_price": round(comp_price, 2),
            "demand": demand,
            "stock_available": stock
        })
        
    df = pd.DataFrame(data)
    os.makedirs("data/raw/kaggle_pricing", exist_ok=True)
    df.to_csv("data/raw/kaggle_pricing/pricing_demand_signals.csv", index=False)
    print("Generated Retail Pricing & Demand Signals dataset.")

if __name__ == "__main__":
    generate_inventory_dataset()
    generate_pricing_dataset()
