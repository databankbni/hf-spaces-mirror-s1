import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Chargement des variables d'environnement
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL n'est pas défini dans le fichier .env")

engine = create_engine(DATABASE_URL)

# Chargement du dataset
df = pd.read_csv("data/train_dataset.csv")

# Renommage des colonnes contenant des caractères spéciaux
df.rename(
    columns={
        "PropertyGFABuilding(s)": "PropertyGFABuilding_s",
        "SiteEnergyUse(kBtu)": "SiteEnergyUse_kBtu",
    },
    inplace=True,
)

# PostgreSQL utilise des noms de colonnes en minuscules
df.columns = [col.lower() for col in df.columns]

# Import dans la table dataset
df.to_sql(
    name="dataset",
    con=engine,
    if_exists="append",
    index=False,
)

print(f"✅ {len(df)} lignes importées dans la table dataset.")