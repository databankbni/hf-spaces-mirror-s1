FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV JAVALD_DISABLE=1
ENV SAL_DISABLE_JAVA=1
ENV SAL_USE_VCLPLUGIN=svp

RUN sed -i 's/main/main contrib non-free/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/main/main contrib non-free/g' /etc/apt/sources.list

RUN echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-impress \
    default-jre-headless \
    python3-uno \
    ghostscript \
    poppler-utils \
    fontconfig \
    libgl1 \
    libgomp1 \
    wget \
    cabextract \
    zip \
    locales \
    ca-certificates \
    ttf-mscorefonts-installer \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i -e 's/# ru_RU.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen
ENV LANG=ru_RU.UTF-8 \
    LANGUAGE=ru_RU:ru \
    LC_ALL=ru_RU.UTF-8

RUN fc-cache -f -v

RUN useradd -m -u 1000 user
ENV HOME=/home/user
WORKDIR $HOME/app

RUN mkdir -p $HOME/.config/libreoffice && chown -R user:user $HOME

USER user

COPY --chown=user ./requirements.txt $HOME/app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r $HOME/app/requirements.txt

COPY --chown=user . $HOME/app

EXPOSE 7860


CMD ["python", "bot.py"]
