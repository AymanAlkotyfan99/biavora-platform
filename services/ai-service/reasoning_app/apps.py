from django.apps import AppConfig
import os


class ReasoningAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reasoning_app'

    def ready(self):
        from shared.sql_parser import ensure_sql_parser_ready

        debug_env = str(os.getenv("DEBUG", "false")).strip().lower() in {"1", "true", "yes", "on"}
        ensure_sql_parser_ready(strict=not debug_env)
