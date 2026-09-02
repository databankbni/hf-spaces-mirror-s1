FROM node:20-slim

WORKDIR /app

COPY package*.json ./

RUN npm install --only=production

COPY . .

# Hugging Face Spaces port requirement (7860)
EXPOSE 7860

ENV PORT=7860

CMD ["npm", "start"]