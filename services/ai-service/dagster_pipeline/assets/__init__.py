from dagster_pipeline.assets.execution import (
    forecasting_asset,
    pipeline_result_asset,
    query_execution_asset,
    visualization_asset,
)
from dagster_pipeline.assets.classification import classification_asset
from dagster_pipeline.assets.intent_classification import intent_classification_asset
from dagster_pipeline.assets.intent_extraction import intent_extraction_asset
from dagster_pipeline.assets.preprocessing_high import preprocessing_high_asset
from dagster_pipeline.assets.preprocessing_low import preprocessing_low_asset
from dagster_pipeline.assets.routing import routing_asset
from dagster_pipeline.assets.transcription import (
    pipeline_request_asset,
    transcription_asset,
)

ALL_ASSETS = [
    pipeline_request_asset,
    transcription_asset,
    preprocessing_low_asset,
    classification_asset,
    intent_classification_asset,
    preprocessing_high_asset,
    intent_extraction_asset,
    routing_asset,
    query_execution_asset,
    visualization_asset,
    forecasting_asset,
    pipeline_result_asset,
]

__all__ = [
    "ALL_ASSETS",
    "pipeline_request_asset",
    "transcription_asset",
    "preprocessing_low_asset",
    "classification_asset",
    "intent_classification_asset",
    "preprocessing_high_asset",
    "intent_extraction_asset",
    "routing_asset",
    "query_execution_asset",
    "visualization_asset",
    "forecasting_asset",
    "pipeline_result_asset",
]
