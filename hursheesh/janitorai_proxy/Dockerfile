FROM node:18-slim

WORKDIR /app

# Copy manifest first so Docker can cache the npm install layer
COPY package.json ./
RUN npm install --omit=dev

# Now copy the rest of the app
COPY . .

# HF Spaces expects the app to listen on 7860
EXPOSE 7860

CMD ["node", "server.js"]
