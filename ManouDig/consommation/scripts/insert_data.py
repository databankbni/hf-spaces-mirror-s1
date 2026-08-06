import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Chargement des variables d'environnement
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

# Chargement du dataset exporté depuis le notebook
df = pd.read_csv("data/train_dataset.csv")

# Renommer les colonnes contenant des caractères spéciaux
df.rename(
    columns={
        "PropertyGFABuilding(s)": "PropertyGFABuilding_s",
        "SiteEnergyUse(kBtu)": "SiteEnergyUse_kBtu",
    },
    inplace=True,
)

# PostgreSQL stocke les colonnes en minuscules
df.columns = [col.lower() for col in df.columns]

print("Colonnes importées :")
print(df.columns.tolist())

# Insertion dans la table dataset
df.to_sql(
    name="dataset",
    con=engine,
    if_exists="append",
    index=False,
)

print(f"✅ {len(df)} lignes importées dans la table dataset.")