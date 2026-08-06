import os
import sys
import pandas as pd
import random
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.services.rl_pricing_service import RLPricingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("Initializing RL Pricing Service...")
    service = RLPricingService(
        data_path="data/processed/super_model_data_clean.csv",
        artifact_path="artifacts/demand_model.joblib",
        rl_policy_path="artifacts/rl_q_table.json"
    )
    service.startup()

    print("Loading super model dataset to sample contexts...")
    df = pd.read_csv("data/processed/super_model_data_clean.csv")

    # Sample random contexts from the real data
    print("Training RL agent across 5000 episodes...")
    for episode in range(5000):
        # Pick a random row
        row = df.sample(1).iloc[0]
        
        competitor_price = float(row['competitor_price'])
        # Pick a random unit cost between 40% and 90% of competitor_price to make it realistic
        random_unit_cost = round(random.uniform(competitor_price * 0.4, competitor_price * 0.9), 2)
        
        # Train on this context without saving to disk every time
        service.train_on_experience(
            competitor_price=float(row['competitor_price']),
            inventory=int(row['inventory']),
            day_of_week=int(row['day_of_week']),
            unit_cost=random_unit_cost,
            num_episodes=5,
            save_policy=False
        )
        
        if (episode + 1) % 1000 == 0:
            print(f"Completed {episode + 1} / 5000 contexts...")

    # Save final policy
    service.save_policy()
    info = service.policy_info()
    print(f"Training complete! Final policy size: {info['policy_size']} states.")

if __name__ == "__main__":
    main()
