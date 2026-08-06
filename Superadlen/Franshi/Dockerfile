# Utiliser une image Node.js officielle et légère
FROM node:18-slim

# Définir le dossier de travail dans le conteneur
WORKDIR /app

# Copier les fichiers de configuration de paquets
COPY package*.json ./

# Installer les dépendances
RUN npm install --production

# Copier le reste du code de l'application
COPY . .

# Hugging Face Spaces s'attend à ce que l'application tourne sur le port 7860
ENV PORT=7860
EXPOSE 7860

# Commande pour démarrer votre addon Stremio
CMD ["npm", "start"]