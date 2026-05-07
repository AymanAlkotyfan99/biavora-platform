import os
import sys
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
    "database",
    "query_api",
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
        "HOST": os.getenv("DB_HOST", "postgres-query"),
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

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
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

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "etl_user")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "etl_pass123")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "etl")

ETL_SERVICE_URL = os.getenv("ETL_SERVICE_URL", "http://etl-platform:8001")

# Shared secret for ai-service / voice-service -> query-service ``/query/validate/`` and ``/query/execute/``.
# ``INTERNAL_API_TOKEN`` is the canonical name; legacy aliases remain accepted
# so older deployments do not reject internal callers during rollout.
INTERNAL_API_TOKEN = str(
    os.getenv("INTERNAL_API_TOKEN", "")
    or os.getenv("QUERY_SERVICE_INTERNAL_TOKEN", "")
    or os.getenv("SERVICE_INTERNAL_TOKEN", "")
    or os.getenv("INTERNAL_SERVICE_TOKEN", "")
    or ""
).strip()
SERVICE_INTERNAL_TOKEN = INTERNAL_API_TOKEN
INTERNAL_SERVICE_TOKEN = INTERNAL_API_TOKEN
QUERY_SERVICE_INTERNAL_TOKEN = INTERNAL_API_TOKEN

_DEV_ONLY_INTERNAL_AUTH_BYPASS = str(os.getenv("DEV_ONLY_INTERNAL_AUTH_BYPASS", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _query_service_running_tests() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules or any(
        arg.endswith("pytest") or arg == "test" for arg in sys.argv
    )


_MIN_INTERNAL_TOKEN_LEN = 32

# Startup validation for internal token (fail loud outside tests)
if not _query_service_running_tests():
    if not INTERNAL_API_TOKEN and not _DEV_ONLY_INTERNAL_AUTH_BYPASS:
        raise ImproperlyConfigured(
            "query_service_missing_internal_token: set INTERNAL_SERVICE_TOKEN (or INTERNAL_API_TOKEN) "
            "to a shared secret of at least 32 characters for service-to-service calls. "
            "For unsafe local-only experiments, set DEV_ONLY_INTERNAL_AUTH_BYPASS=true."
        )
    if INTERNAL_API_TOKEN and len(INTERNAL_API_TOKEN) < _MIN_INTERNAL_TOKEN_LEN and not _DEV_ONLY_INTERNAL_AUTH_BYPASS:
        raise ImproperlyConfigured(
            f"query_service_internal_token_too_short: internal token must be >= {_MIN_INTERNAL_TOKEN_LEN} characters."
        )

if not INTERNAL_API_TOKEN and _DEV_ONLY_INTERNAL_AUTH_BYPASS:
    import logging

    logging.getLogger(__name__).warning(
        "query_service_dev_only_internal_auth_bypass_enabled_without_shared_token",
        extra={"unsafe": True},
    )
elif INTERNAL_API_TOKEN:
    import logging

    logging.getLogger(__name__).info(
        "SERVICE_INTERNAL_TOKEN configured",
        extra={"token_length": len(INTERNAL_API_TOKEN)},
    )

CORS_ALLOW_ALL_ORIGINS = False
_raw_cors_allowed_origins = os.getenv("DJANGO_CORS_ALLOWED_ORIGINS", os.getenv("CORS_ALLOWED_ORIGINS", ""))
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in _raw_cors_allowed_origins.split(",") if origin.strip()]
# Keep startup safe in environments where explicit CORS origins are not provided yet.
# We never allow wildcard + credentials; credentials are enabled only with explicit origins.
CORS_ALLOW_CREDENTIALS = bool(CORS_ALLOWED_ORIGINS)
