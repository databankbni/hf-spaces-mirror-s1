from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-change-me-in-production'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'app', # Changed from 'dashboard'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'config.urls' # Changed from 'climate_dashboard.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'app' / 'templates'], # Changed from 'dashboard'
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': '/tmp/db.sqlite3',
    }
}

WSGI_APPLICATION = 'config.wsgi.application' # Changed from 'climate_dashboard.wsgi.application'

STATIC_URL = '/static/'
STATICFILES_DIRS = []

MEDIA_URL = '/output/'
MEDIA_ROOT = BASE_DIR / 'output'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'