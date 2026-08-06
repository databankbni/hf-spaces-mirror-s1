# 1. Utiliser l'image officielle Python légère de la Silicon Valley
FROM python:3.10-slim

# 2. Définir le dossier de travail sécurisé à l'intérieur du serveur
WORKDIR /code

# 3. Installer toutes nos briques technologiques en UNE SEULE LIGNE propre (Sans bug de cache)
RUN pip install --no-cache-dir fastapi uvicorn requests supabase==2.4.0 httpx==0.24.1

# 4. Copier tout le reste de ton projet (app.py) dans le serveur
COPY . .

# 5. Donner l'ordre de démarrage officiel à ton antenne sur le port usine 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
