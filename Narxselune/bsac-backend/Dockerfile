FROM node:18-alpine
# Установка системных зависимостей для сборки модулей Node.js
RUN apk update && apk add --no-cache build-base gcc autoconf automake zlib-dev libpng-dev nasm bash vips-dev

ENV NODE_ENV=production
WORKDIR /opt/

# Копируем файлы зависимостей из подпапки backend
COPY backend/package.json backend/package-lock.json ./
RUN npm install -g node-gyp
RUN npm config set fetch-retry-maxtimeout 600000
RUN npm install --only=production
ENV PATH /opt/node_modules/.bin:$PATH

# Переходим в рабочую папку и копируем код бэкенда из подпапки backend
WORKDIR /opt/app
COPY backend/ .

# Собираем административную панель Strapi
RUN npm run build

# Настройка портов под стандарты Hugging Face Spaces
ENV PORT=7860
EXPOSE 7860

CMD ["npm", "run", "start"]