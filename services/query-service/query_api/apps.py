import os

from django.apps import AppConfig


class QueryApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "query_api"

    def ready(self):
        from query_api.sql_parser import ensure_sql_parser_ready

        debug_env = str(os.getenv("DEBUG", "false")).strip().lower() in {"1", "true", "yes", "on"}
        ensure_sql_parser_ready(strict=not debug_env)

