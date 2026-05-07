"""voice-service ⇄ ai-service convenience facade.

Exposes the ``AIClient`` adapter used by ``orchestration_service`` so the
orchestrator does not have to know whether the underlying transport is
``AIServiceClient`` (CRIT-12 rename, current canonical name).
"""

from __future__ import annotations

from voice_reports.services.ai_service_client import AIServiceClient, get_ai_service_client


class AIClient:
    """Thin adapter around :class:`AIServiceClient`.

    Provides ``process_audio``/``process_text`` entry points with the exact
    keyword arguments the orchestrator passes today, so renaming the
    underlying class did not require touching the orchestrator's call sites.
    """

    def __init__(self) -> None:
        self.client: AIServiceClient = get_ai_service_client()

    def process_text(
        self,
        *,
        text: str,
        user_id: str,
        workspace_id: str,
        manager_id: str,
        dataset_id: str,
        source_id: str,
        table_name: str,
        report_id: str,
    ):
        return self.client.process_text(
            text=text,
            user_id=user_id,
            workspace_id=workspace_id,
            manager_id=manager_id,
            dataset_id=dataset_id,
            source_id=source_id,
            table_name=table_name,
            report_id=report_id,
        )

    def process_audio(
        self,
        *,
        audio_file: str,
        user_id: str,
        workspace_id: str,
        manager_id: str,
        dataset_id: str,
        source_id: str,
        table_name: str,
        report_id: str,
    ):
        return self.client.process_audio(
            audio_file=audio_file,
            user_id=user_id,
            workspace_id=workspace_id,
            manager_id=manager_id,
            dataset_id=dataset_id,
            source_id=source_id,
            table_name=table_name,
            report_id=report_id,
        )


_singleton: "AIClient | None" = None


def get_ai_client() -> AIClient:
    global _singleton
    if _singleton is None:
        _singleton = AIClient()
    return _singleton


__all__ = ["AIClient", "get_ai_client"]
