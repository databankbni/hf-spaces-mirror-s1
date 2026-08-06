---
title: Consommation
emoji: 📈
colorFrom: yellow
colorTo: pink
sdk: gradio
sdk_version: 5.34.2
app_file: app.py
pinned: false
---

# ⚡ Seattle Energy Prediction API

## Présentation

Ce projet a pour objectif de déployer un modèle de Machine Learning permettant de prédire la consommation énergétique de bâtiments non résidentiels de la ville de Seattle.

L'application expose le modèle via une API REST développée avec **FastAPI** et propose également une interface utilisateur **Gradio**.

Le modèle de Machine Learning est stocké sur **Hugging Face Hub** et téléchargé automatiquement au démarrage de l'application.

Toutes les prédictions sont enregistrées dans une base de données **SQLite** à l'aide de SQLAlchemy.

---

# Technologies utilisées

- Python 3.11
- FastAPI
- Gradio
- Pydantic
- SQLAlchemy
- PostgreSQL (Neon)
- Scikit-learn
- Pandas
- Joblib
- Pytest
- GitHub Actions
- Hugging Face Spaces

---

# Architecture du projet

```text
projet5elec/

│
├── app/
│   ├── app_gradio.py
│   ├── crud.py
│   ├── database.py
│   ├── main.py
│   ├── ml_model.py
│   ├── models.py
│   ├── schemas.py
│   └── security.py
│
├── data/
│   └── energie.ipynb
│
├── scripts/
│
├── tests/
│
├── requirements.txt
├── app.py
└── README.md
```
---

# Architecture globale

```
                    Utilisateur
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
   Interface Gradio              API FastAPI
          │                             │
          │                             │
          ▼                             ▼
                Modèle Machine Learning
                         │
                         ▼
              Random Forest Regressor
                         │
                         ▼
             Base PostgreSQL (Neon)
                         │
                         ▼
 Historisation des prédictions + Monitoring
```
---

# Modèle de Machine Learning

Le modèle utilisé est :

**RandomForestRegressor**

Variable cible :

```
SiteEnergyUse(kBtu)
```

Variables utilisées :

- YearBuilt
- BuildingAge
- NumberofFloors
- Log_Surface
- PropertyGFATotal
- LargestPropertyUseTypeGFA
- PropertyGFABuilding_s
- BuildingType
- PrimaryPropertyType
- City
- State

---

# Base de données

Le projet utilise une base de données **PostgreSQL hébergée sur NeonDB** afin d'assurer la persistance des données et la traçabilité des prédictions réalisées par le modèle de Machine Learning.

La connexion à la base est gérée avec **SQLAlchemy**. Les paramètres de connexion sont fournis grâce à la variable d'environnement `DATABASE_URL`, ce qui permet de ne jamais stocker les informations sensibles dans le code source.

---

## Authentification

L'accès aux fonctionnalités de prédiction est protégé par une **API Key**.

Chaque requête envoyée vers l'endpoint :

```
POST /predict
```

doit contenir l'en-tête HTTP :

```
X-API-Key: votre_api_key
```

La vérification est réalisée par le module `security.py`. Si la clé est absente ou invalide, l'API renvoie automatiquement une réponse **HTTP 403 Forbidden**.

Cette authentification limite l'accès au service aux utilisateurs autorisés.

---

## Sécurité

Les informations sensibles ne sont jamais enregistrées dans le dépôt GitHub.

Les secrets sont stockés dans :

- le fichier `.env` en développement local ;
- les **GitHub Secrets** pour l'intégration continue ;
- les **Secrets Hugging Face** lors du déploiement.

Les variables suivantes sont utilisées :

- `DATABASE_URL`
- `API_KEY`
- `HF_TOKEN`

Cette organisation garantit la confidentialité des identifiants de connexion et des clés d'accès.

---

## Stockage des données

La base PostgreSQL contient trois tables principales.

### Table `predictions`

Cette table enregistre chaque prédiction effectuée par l'API.

Pour chaque appel sont conservés :

- les caractéristiques du bâtiment ;
- la valeur prédite (`prediction_kbtu`) ;
- la date de création.

Cette table permet de conserver un historique complet des prédictions réalisées.

---

### Table `monitoring`

Cette table est destinée au suivi du fonctionnement de l'application.

Elle peut enregistrer :

- le temps de réponse du modèle ;
- le statut de l'exécution ;
- la version du modèle utilisée ;
- la date de la requête.

Ces informations permettent d'évaluer les performances de l'API et de détecter d'éventuelles anomalies.

---

### Table `dataset`

Cette table contient le jeu de données utilisé lors de l'entraînement du modèle.

Le dataset est :

1. préparé dans le notebook `energie.ipynb` ;
2. exporté au format CSV (`train_dataset.csv`) ;
3. importé dans PostgreSQL grâce au script :

```
scripts/insert_data.py
```

Le stockage du dataset dans la base garantit la reproductibilité du projet et la conservation des données ayant servi à entraîner le modèle.

---

## Gestion des données

Le cycle de vie des données est le suivant :

1. Nettoyage et préparation des données dans le notebook `energie.ipynb`.
2. Entraînement du modèle **Random Forest Regressor**.
3. Sauvegarde du modèle (`model.pkl`).
4. Export du jeu d'entraînement (`train_dataset.csv`).
5. Import du dataset dans PostgreSQL via `scripts/insert_data.py`.
6. Réalisation des prédictions par l'API FastAPI.
7. Enregistrement automatique de chaque prédiction dans la table `predictions`.
8. Suivi du fonctionnement de l'application grâce à la table `monitoring`.

Cette organisation permet d'assurer la traçabilité complète des données, leur conservation et leur exploitation tout au long du cycle de vie du projet.
---

# Installation

Cloner le dépôt :

```bash
git clone https://github.com/mansour-ndoye/projet5elec.git

cd projet5elec
```

Créer un environnement virtuel :

Windows

```bash
python -m venv venv
venv\Scripts\activate
```

Linux

```bash
python -m venv venv
source venv/bin/activate
```

Installer les dépendances :

```bash
pip install -r requirements.txt
```

---

# Variables d'environnement

Créer un fichier `.env`

```
DATABASE_URL=postgresql://...

API_KEY=xxxxxxxx

HF_TOKEN=xxxxxxxx
```

---

# Lancer l'API

```bash
uvicorn app.main:app --reload
```

API disponible :

```
http://127.0.0.1:8000
```

---

# Documentation

Swagger :

```
http://127.0.0.1:8000/docs
```

ReDoc :

```
http://127.0.0.1:8000/redoc
```

---

# Interface Gradio

Accessible directement depuis :

```
http://127.0.0.1:8000/gradio
```

---

# Exemple d'appel API

```
POST /predict
```

Header

```
X-API-Key: votre_api_key
```

Body

```json
{
  "YearBuilt": 2005,
  "BuildingAge": 21,
  "NumberofFloors": 5,
  "Log_Surface": 11,
  "PropertyGFATotal": 100000,
  "LargestPropertyUseTypeGFA": 80000,
  "PropertyGFABuilding_s": 95000,
  "BuildingType": "NonResidential",
  "PrimaryPropertyType": "Office",
  "City": "Seattle",
  "State": "WA"
}
```

Réponse

```json
{
    "prediction_kbtu": 123456.78
}
```

---

# Tests

Lancer les tests

```bash
pytest
```

Couverture

```bash
pytest --cov=app
```

---

# Git

Le projet suit une stratégie de branches :

- master
- dev
- feature/database
- feature/api
- feature/model
- feature/tests
- feature/cicd

Les versions sont identifiées par des **tags Git**.

Exemple :

```
v1.0
v1.1
```

---

# CI/CD

GitHub Actions permet automatiquement :

- exécution des tests
- vérification du code
- déploiement sur Hugging Face Spaces

---

# Déploiement

Le projet est déployé automatiquement sur **Hugging Face Spaces** après validation des tests GitHub Actions.

---

# Auteur

Projet réalisé dans le cadre de la formation

**OpenClassrooms – Ingénieur Intelligence Artificielle**