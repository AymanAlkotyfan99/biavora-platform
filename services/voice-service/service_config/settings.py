import os
import logging
from pathlib import Path
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env.microservices')

_raw_debug = os.getenv("DJANGO_DEBUG", os.getenv("DEBUG", "false"))
DEBUG = str(_raw_debug).strip().lower() in {"1", "true", "yes", "on"}
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-voice-service-secret-key-32bytes-minimum-for-jwt"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG is false")

_raw_allowed_hosts = os.getenv("DJANGO_ALLOWED_HOSTS", os.getenv("ALLOWED_HOSTS", ""))
if _raw_allowed_hosts.strip():
    ALLOWED_HOSTS = [host.strip() for host in _raw_allowed_hosts.split(",") if host.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
else:
    ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'users',
    'workspace',
    'voice_reports',
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

if os.getenv('DJANGO_TEST_SQLITE', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.getenv('DJANGO_TEST_SQLITE_NAME', ':memory:'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'bi_voice_agent'),
            'USER': os.getenv('DB_USER', 'bi_admin'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'postgres-voice'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 600,
        }
    }

AUTH_USER_MODEL = 'users.User'

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
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

SMALL_WHISPER_URL = os.getenv('SMALL_WHISPER_URL', 'http://ai-service:8005')
SMALL_WHISPER_HEALTH_TIMEOUT_SECONDS = int(os.getenv('SMALL_WHISPER_HEALTH_TIMEOUT_SECONDS', '5'))
SMALL_WHISPER_CONNECT_TIMEOUT_SECONDS = int(os.getenv('SMALL_WHISPER_CONNECT_TIMEOUT_SECONDS', '10'))
SMALL_WHISPER_TIMEOUT_SECONDS = int(os.getenv('SMALL_WHISPER_TIMEOUT_SECONDS', '300'))
SMALL_WHISPER_MAX_RETRIES = int(os.getenv('SMALL_WHISPER_MAX_RETRIES', '1'))
AI_SERVICE_INTERNAL_API_KEY = os.getenv('AI_SERVICE_INTERNAL_API_KEY', '')
QUERY_SERVICE_URL = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006')
VISUALIZATION_SERVICE_URL = os.getenv('VISUALIZATION_SERVICE_URL', 'http://visualization-service:8007')
REPORT_SERVICE_URL = os.getenv('REPORT_SERVICE_URL', 'http://report-service:8003')
SUBSCRIPTION_SERVICE_URL = os.getenv('SUBSCRIPTION_SERVICE_URL', 'http://subscription-service:8008')
SERVICE_REQUEST_TIMEOUT_SECONDS = int(os.getenv('SERVICE_REQUEST_TIMEOUT_SECONDS', '30'))
SERVICE_REQUEST_CONNECT_TIMEOUT_SECONDS = int(os.getenv('SERVICE_REQUEST_CONNECT_TIMEOUT_SECONDS', '10'))
SERVICE_REQUEST_READ_TIMEOUT_SECONDS = int(os.getenv('SERVICE_REQUEST_READ_TIMEOUT_SECONDS', '120'))
SERVICE_INTERNAL_TOKEN = str(
    os.getenv('INTERNAL_SERVICE_TOKEN', '')
    or os.getenv('QUERY_SERVICE_INTERNAL_TOKEN', '')
    or os.getenv('SERVICE_INTERNAL_TOKEN', '')
    or os.getenv('INTERNAL_API_TOKEN', '')
    or ''
).strip()
if not SERVICE_INTERNAL_TOKEN:
    logging.getLogger(__name__).warning(
        "SERVICE_INTERNAL_TOKEN not configured. "
        "voice-service calls to query-service may fail when user JWT is not forwarded."
    )

# Phase 7 / CRIT-05: voice-service no longer pins a workspace database from
# the environment. query-service resolves the canonical ClickHouse database
# from ``workspace_id`` on every call. The legacy
# ``QUERY_WORKSPACE_DATABASE`` env (which silently routed everything to
# ``etl``) has been removed deliberately.
VOICE_SERVICE_ALLOW_SYNC_PIPELINE = str(
    os.getenv('VOICE_SERVICE_ALLOW_SYNC_PIPELINE', 'false')
).strip().lower() in {'1', 'true', 'yes', 'on'}

# ---------------------------------------------------------------------------
# CRIT-02: Async pipeline (Celery)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv(
    'CELERY_BROKER_URL',
    os.getenv('REDIS_URL', 'redis://redis:6379/1'),
)
CELERY_RESULT_BACKEND = os.getenv(
    'CELERY_RESULT_BACKEND',
    os.getenv('REDIS_URL', 'redis://redis:6379/2'),
)
CELERY_TASK_ALWAYS_EAGER = str(os.getenv('CELERY_TASK_ALWAYS_EAGER', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = int(os.getenv('CELERY_TASK_TIME_LIMIT', '900'))
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv('CELERY_TASK_SOFT_TIME_LIMIT', '840'))
CELERY_WORKER_CONCURRENCY = int(os.getenv('CELERY_WORKER_CONCURRENCY', '4'))
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv('CELERY_WORKER_PREFETCH_MULTIPLIER', '1'))
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_DEFAULT_QUEUE = 'voice_pipeline'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# ---------------------------------------------------------------------------
# CRIT-11: Audio validation hardening
# ---------------------------------------------------------------------------
CLAMAV_HOST = os.getenv('CLAMAV_HOST', 'clamav')
CLAMAV_PORT = int(os.getenv('CLAMAV_PORT', '3310'))
CLAMAV_TIMEOUT_SECONDS = int(os.getenv('CLAMAV_TIMEOUT_SECONDS', '30'))
CLAMAV_REQUIRED = str(os.getenv('CLAMAV_REQUIRED', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
AUDIO_FFPROBE_REQUIRED = str(os.getenv('AUDIO_FFPROBE_REQUIRED', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
AUDIO_MAX_SIZE_BYTES = int(os.getenv('AUDIO_MAX_SIZE_BYTES', str(100 * 1024 * 1024)))
AUDIO_MAX_DURATION_SECONDS = int(os.getenv('AUDIO_MAX_DURATION_SECONDS', '300'))

METABASE_URL = os.getenv('METABASE_URL', 'http://metabase:3000')
METABASE_USERNAME = os.getenv('METABASE_USERNAME', '')
METABASE_PASSWORD = os.getenv('METABASE_PASSWORD', '')
METABASE_DATABASE_ID = int(os.getenv('METABASE_DATABASE_ID', '2'))
METABASE_SECRET_KEY = os.getenv('METABASE_SECRET_KEY', '')

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
_raw_cors_allowed_origins = os.getenv("DJANGO_CORS_ALLOWED_ORIGINS", os.getenv("CORS_ALLOWED_ORIGINS", ""))
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _raw_cors_allowed_origins.split(",")
    if origin.strip()
]
if DEBUG and not CORS_ALLOWED_ORIGINS:
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
if CORS_ALLOW_CREDENTIALS and not DEBUG and not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured(
        "DJANGO_CORS_ALLOWED_ORIGINS (or CORS_ALLOWED_ORIGINS) must be set when credentials are enabled."
    )
