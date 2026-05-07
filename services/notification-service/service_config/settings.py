import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env.microservices')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'notification-service-secret-key')

# Phase 11 / CRIT-15: production-safe DEBUG and ALLOWED_HOSTS defaults.
DEBUG = str(os.getenv('DEBUG', 'False')).strip().lower() in {"1", "true", "yes", "on"}

_raw_allowed_hosts = os.getenv('ALLOWED_HOSTS', '').strip()
_allowed_hosts = [host.strip() for host in _raw_allowed_hosts.split(',') if host.strip()] if _raw_allowed_hosts else []
if not _allowed_hosts:
    _allowed_hosts = ['localhost', '127.0.0.1'] if DEBUG else []
# Internal service-to-service requests use the Docker hostname "notification-service".
if 'notification-service' not in _allowed_hosts:
    _allowed_hosts.append('notification-service')
ALLOWED_HOSTS = _allowed_hosts

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'notification',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'service_config.urls'
WSGI_APPLICATION = 'service_config.wsgi.application'
ASGI_APPLICATION = 'service_config.asgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'bi_voice_agent'),
        'USER': os.getenv('DB_USER', 'bi_admin'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'StrongPassword123'),
        'HOST': os.getenv('DB_HOST', 'postgres-notification'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
}

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'BI Voice Agent <no-reply@bivoiceagent.com>')
SERVER_EMAIL = EMAIL_HOST_USER
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '10'))
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

NOTIFICATION_INTERNAL_API_KEY = os.getenv('NOTIFICATION_SERVICE_API_KEY', '').strip()
SUBSCRIPTION_EXPIRY_WARNING_DAYS = os.getenv('SUBSCRIPTION_EXPIRY_WARNING_DAYS', '7,3,1')

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
