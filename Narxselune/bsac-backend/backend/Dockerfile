FROM node:18-alpine
# Установка системных зависимостей для сборки модулей Node.js
RUN apk update && apk add --no-cache build-base gcc autoconf automake zlib-dev libpng-dev nasm bash vips-dev

ENV NODE_ENV=production
WORKDIR /opt/

# Копируем файлы зависимостей
COPY package.json package-lock.json ./
RUN npm install -g node-gyp
RUN npm config set fetch-retry-maxtimeout 600000
RUN npm install --only=production
ENV PATH /opt/node_modules/.bin:$PATH

# Копируем исходный код бэкенда
WORKDIR /opt/app
COPY . .

# Собираем административную панель Strapi
RUN npm run build

# Панель Hugging Face Spaces по умолчанию слушает порт 7860
ENV PORT=7860
EXPOSE 7860

CMD ["npm", "run", "start"]
