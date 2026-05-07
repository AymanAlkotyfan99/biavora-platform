import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent.parent / ".env")

_raw_debug = os.getenv("DJANGO_DEBUG", os.getenv("DEBUG", "false"))
DEBUG = str(_raw_debug).strip().lower() in {"1", "true", "yes", "on"}
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set")

_raw_allowed_hosts = os.getenv("DJANGO_ALLOWED_HOSTS", os.getenv("ALLOWED_HOSTS", ""))
ALLOWED_HOSTS = [host.strip() for host in _raw_allowed_hosts.split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "users",
    "workspace",
    "visualization_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "service_config.urls"
WSGI_APPLICATION = "service_config.wsgi.application"
ASGI_APPLICATION = "service_config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "bi_voice_agent"),
        "USER": os.getenv("DB_USER", "bi_admin"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "postgres-visualization"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 600,
    }
}
if not DATABASES["default"]["PASSWORD"]:
    raise ImproperlyConfigured("DB_PASSWORD must be set")

AUTH_USER_MODEL = "users.User"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INTERNAL_API_TOKEN = str(os.getenv("INTERNAL_API_TOKEN", "") or "").strip()
SERVICE_INTERNAL_TOKEN = str(
    os.getenv("SERVICE_INTERNAL_TOKEN", "") or os.getenv("INTERNAL_SERVICE_TOKEN", "") or INTERNAL_API_TOKEN or ""
).strip()
if SERVICE_INTERNAL_TOKEN and len(SERVICE_INTERNAL_TOKEN) < 32 and not DEBUG:
    raise ImproperlyConfigured("SERVICE_INTERNAL_TOKEN must be at least 32 characters when set (production).")

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "visualization_api.authentication.ServiceInternalTokenAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

METABASE_URL = os.getenv("METABASE_URL", "http://metabase:3000")
METABASE_USERNAME = os.getenv("METABASE_USERNAME", "")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", "")
METABASE_DATABASE_ID = int(os.getenv("METABASE_DATABASE_ID", "2"))
METABASE_SECRET_KEY = os.getenv("METABASE_SECRET_KEY", "")

CORS_ALLOW_ALL_ORIGINS = False
_raw_cors_allowed_origins = os.getenv("DJANGO_CORS_ALLOWED_ORIGINS", os.getenv("CORS_ALLOWED_ORIGINS", ""))
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in _raw_cors_allowed_origins.split(",") if origin.strip()]
# Keep startup safe in envs where explicit CORS origins are not set yet.
# Credentials are enabled only when explicit origins are configured.
CORS_ALLOW_CREDENTIALS = bool(CORS_ALLOWED_ORIGINS)
