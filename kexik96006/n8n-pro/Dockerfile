# Step 1: Base image select karein (Node.js ka lightweight version)
FROM node:18-alpine

# Step 2: Container ke andar ek working directory banayein
WORKDIR /app

# Step 3: Package files copy karein
COPY package*.json ./

# Step 4: Dependencies install karein
RUN npm install

# Step 5: Baki sara code (server.js) container mein copy karein
COPY . .

# Step 6: Port 7860 expose karein (Hugging Face Requirement)
EXPOSE 7860

# Step 7: Container start hone par ye command chale
CMD ["npm", "start"]