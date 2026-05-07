"""
report-service voice_reports.services
=====================================

Per CRIT-01, report-service is read-only. The Whisper client, ClickHouse
executor, Metabase service, SQLGuard, and AI trace builder were all moved
out of this service: their canonical owners are voice-service / ai-service /
query-service / visualization-service.

The only thing that remains here is the JWT embedding helper, used by the
read-only views to mint short-lived embed URLs from previously persisted
``metabase_question_id`` values.
"""

from .jwt_embedding import JWTEmbeddingService, get_jwt_service

__all__ = ["JWTEmbeddingService", "get_jwt_service"]
