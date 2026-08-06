# FROM php:8.2-cli-bookworm

# # 避免 apt 安装过程中出现交互式提示
# ENV DEBIAN_FRONTEND=noninteractive

# # 创建非 root 用户 (UID 1000)，用于避开 Chromium/Calibre 的 root 沙箱限制
# RUN useradd -m -u 1000 appuser

# # 安装基础系统依赖
# RUN apt-get update && apt-get install -y \
#     git \
#     unzip \
#     zip \
#     calibre \
#     fontconfig \
#     fonts-freefont-ttf \
#     fonts-linuxlibertine \
#     fonts-dejavu-core \
#     fonts-gubbi \
#     fonts-opendyslexic \
#     libsqlite3-dev \
#     libzip-dev \
#     libcurl4-openssl-dev \
#     libicu-dev \
#     libonig-dev \
#     nodejs \
#     npm \
#     && rm -rf /var/lib/apt/lists/*

# # 编译并安装运行所需的 PHP 扩展
# RUN docker-php-ext-configure intl \
#     && docker-php-ext-install pdo pdo_sqlite pdo_mysql zip curl sysvsem intl mbstring

# # 从官方镜像引入 Composer
# COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

# # 设置工作目录并克隆 wsexport 源码
# WORKDIR /app
# RUN git clone https://gitlab.wikimedia.org/toolforge-repos/wsexport.git .

# # 声明真正的系统环境变量
# ENV APP_ENV=prod
# ENV APP_SECRET=bf48e1003666d925acccf24e937d7bfd
# ENV DATABASE_URL=sqlite:///%kernel.project_dir%/var/data.db
# ENV MAILER_DSN=null://default

# # 创建 Symfony 缓存与日志目录并开放权限
# RUN mkdir -p var/cache var/log var/sessions && chmod -R 777 var

# # 安装 PHP 依赖（排除开发环境包，优化自动加载）
# RUN composer install --no-dev --optimize-autoloader --no-interaction

# # 安装前端/npm 依赖
# RUN npm ci

# # 初始化数据库结构（基于系统环境变量，将表结构自动适配在 SQLite 数据库中）
# RUN php bin/console doctrine:schema:create

# # 确保非 root 用户 appuser (UID 1000) 拥有整个工作目录和家目录的所有权
# RUN chown -R appuser:appuser /app /home/appuser

# # 切换到非 root 用户运行（解决 Calibre/Chromium 不能在 root 下运行沙箱的问题）
# USER appuser

# # 暴露 Hugging Face 要求的 7860 端口
# EXPOSE 7860

# # 启动 PHP 内置服务器监听 7860 端口运行服务
# CMD ["php", "-S", "0.0.0.0:7860", "-t", "public/"]

FROM ubuntu:22.04

# 避免安装时出现交互式卡顿
ENV DEBIAN_FRONTEND=noninteractive

# 安装编译所需的依赖
RUN apt-get update && apt-get install -y \
    git \
    g++ \
    make \
    python3 \
    python3-pip \
    curl \
    wget

# 下载并编译 DrawFish
RUN git clone https://github.com/zhou20120904/DrawFish.git /DrawFish
WORKDIR /DrawFish/src
# 编译方式与 stockfish 相同。为了兼容 HuggingFace 的 CPU，使用 x86-64-modern 或 x86-64-bmi2
RUN make build ARCH=native

WORKDIR /
RUN git clone https://github.com/zhou20120904/Fairy-Drawfish.git /Fairy-Drawfish
WORKDIR /Fairy-Drawfish/src
RUN CXXFLAGS='-march=native' make -j profile-build ARCH=x86-64-avx2 COMP=gcc
RUN ls

# 下载官方的 lichess-bot 框架
WORKDIR /app
RUN git clone https://github.com/lichess-bot-devs/lichess-bot.git .
RUN pip3 install -r requirements.txt

# 将编译好的 drawfish 引擎复制到 bot 的 engines 目录
RUN mkdir -p /app/engines
RUN cp /DrawFish/src/stockfish /app/engines/drawfish
RUN cp /Fairy-Drawfish/src/stockfish /app/engines/fairy-drawfish

# 复制配置文件和启动脚本
COPY config.yml /app/config.yml
COPY start.sh /app/start.sh
COPY homemade.py /app/homemade.py
RUN chmod +x /app/start.sh

# 暴露 7860 端口（必须，应对 HF 的健康检查）
EXPOSE 7860

# 运行启动脚本
CMD ["/app/start.sh"]