# Project Overview
`ai-service` is the analytical intelligence backend for BI Agentic Platform. It orchestrates transcription, low/high preprocessing, input classification, intent extraction, SQL planning/review, chart recommendation, and optional forecasting output for downstream services.

# Folder Structure
- `backend/`: Django project config and top-level routing.
- `dagster_pipeline/`: Dagster assets/jobs/definitions that sequence the AI pipeline stages.
- `forecasting/`: forecasting bridge, pipeline logic, and embedded TimesFM code used for predictive workflows.
- `intent_extraction/`: intent parsing, validation, routing, and schema handling.
- `llm_app/`: LLM-facing service/view/prompt/response components.
- `preprocessing_low/`: low-level cleanup/spell correction/noise removal.
- `preprocessing_high/`: schema-aware semantic correction and diagnostics.
- `reasoning_app/`: graph-driven intent classification/routing reasoning app.
- `shared/`: reusable cross-pipeline contracts, validators, SQL/chart policies and helpers.
- `whisper_app/`: transcription-specific app endpoints/tasks/models.
- `*/migrations/`: Django schema migration package files.

# File Explanations
## backend/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
- **Important Functions/Methods:** none

## backend/asgi.py
- **Responsibility:** Runtime bootstrap/entry point.
- **Role in System:** ASGI config for backend project.
- **Important Classes:** none
- **Important Functions/Methods:** none

## backend/settings.py
- **Responsibility:** Global Django/runtime settings.
- **Role in System:** Django settings for Small Whisper Backend (STATELESS AI WORKER).
- **Important Classes:** none
- **Important Functions/Methods:** none

## backend/urls.py
- **Responsibility:** API route mapping.
- **Role in System:** URL configuration for backend project.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `health_view` | Helper within this module. | `request` | Returns context-dependent output or mutates state. |

## backend/wsgi.py
- **Responsibility:** Runtime bootstrap/entry point.
- **Role in System:** WSGI config for backend project.
- **Important Classes:** none
- **Important Functions/Methods:** none

## dagster_pipeline/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `pipeline_failure_hook` | Helper within this module. | `context` | Returns (typically): None |

## dagster_pipeline/assets/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
- **Important Functions/Methods:** none

## dagster_pipeline/assets/classification.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `classification_asset` | Helper within this module. | `context, preprocessing_low_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/assets/execution.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_extract_result_preview` | Extracts structured information. | `execution_result, max_rows` | Returns (typically): dict[str, Any] |
| `_single_value_result_shape` | Helper within this module. | `execution_result` | Returns (typically): bool |
| `_is_numeric_value` | Helper within this module. | `value` | Returns (typically): bool |
| `_column_name` | Helper within this module. | `column` | Returns (typically): str |
| `_column_type` | Helper within this module. | `column` | Returns (typically): str |
| `_column_type_is_numeric` | Helper within this module. | `column_type` | Returns (typically): bool |
| `_result_shape_profile` | Helper within this module. | `execution_result` | Returns (typically): dict[str, Any] |
| `_normalize_chart_type` | Normalizes values to canonical shape. | `chart_type` | Returns (typically): str |
| `_chart_request_hints` | Helper within this module. | `query_text` | Returns (typically): dict[str, bool] |
| `_looks_percentage_share_query` | Helper within this module. | `query_text` | Returns (typically): bool |
| `_intent_metric_type` | Helper within this module. | `intent_payload` | Returns (typically): str |
| `_intent_chart_type` | Helper within this module. | `intent_payload` | Returns (typically): str |
| `_query_for_chart_selection` | Helper within this module. | `payload` | Returns (typically): str |
| `_shape_supports` | Helper within this module. | `chart_type` | Returns (typically): bool |
| `_validated_chart_choice` | Validates input/business constraints. | `none` | Returns (typically): tuple[str, str] |
| `_ranking_with_dimension` | Helper within this module. | `intent_payload` | Returns (typically): bool |
| `_relationship_comparison_shape` | Helper within this module. | `intent_payload` | Returns (typically): bool |
| `_sql_has_agg_limit_without_group_by` | Helper within this module. | `sql_query` | Returns (typically): bool |
| `_time_grouping_intent` | Helper within this module. | `intent_payload` | Returns (typically): bool |
| `_looks_predictive_query` | Helper within this module. | `query` | Returns (typically): bool |
| `_looks_time_series_query` | Helper within this module. | `query` | Returns (typically): bool |
| `_root_cause_for` | Helper within this module. | `stage, payload` | Returns (typically): tuple[str, str, str] |
| `_to_trace_stage` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `_build_stage_failed` | Builds payload/contract/structured data. | `none` | Returns (typically): dict[str, Any] |
| `_validate_ir_contract` | Validates input/business constraints. | `validated_intent` | Returns (typically): tuple[bool, list[str]] |
| `_table_suffix` | Helper within this module. | `table_name` | Returns (typically): str |
| `_enforce_etl_table_binding` | Helper within this module. | `none` | Returns (typically): tuple[bool, str] |
| `query_execution_asset` | Helper within this module. | `context, routing_asset` | Returns (typically): dict[str, Any] |
| `visualization_asset` | Helper within this module. | `context, query_execution_asset` | Returns (typically): dict[str, Any] |
| `forecasting_asset` | Helper within this module. | `context, query_execution_asset` | Returns (typically): dict[str, Any] |
| `pipeline_result_asset` | Helper within this module. | `pipeline_request_asset, transcription_asset, preprocessing_low_asset, intent_classification_asset, preprocessing_high_asset, intent_extraction_asset, routing_asset, query_execution_asset, visualization_asset, forecasting_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/assets/intent_classification.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `intent_classification_asset` | Helper within this module. | `context, pipeline_request_asset, preprocessing_low_asset, classification_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/assets/intent_extraction.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_schema_from_preprocessing_high` | Runs a major processing step. | `preprocessing_high_asset` | Returns (typically): dict[str, list[dict[str, Any]]] |
| `_bound_table_schema_or_error` | Helper within this module. | `none` | Returns (typically): dict[str, list[dict[str, Any]]] |
| `intent_extraction_asset` | Extracts structured information. | `context, preprocessing_high_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/assets/preprocessing_high.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `preprocessing_high_asset` | Runs a major processing step. | `context, pipeline_request_asset, intent_classification_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/assets/preprocessing_low.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `preprocessing_low_asset` | Runs a major processing step. | `context, pipeline_request_asset, transcription_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/assets/routing.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `routing_asset` | Helper within this module. | `context, intent_extraction_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/assets/transcription.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:**
  - `PipelineRequestConfig` (Config): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `pipeline_request_asset` | Helper within this module. | `context, config` | Returns (typically): dict[str, Any] |
| `transcription_asset` | Helper within this module. | `context, pipeline_request_asset` | Returns (typically): dict[str, Any] |

## dagster_pipeline/definitions.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
- **Important Functions/Methods:** none

## dagster_pipeline/jobs.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Orchestration
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_build_request_config` | Builds payload/contract/structured data. | `none` | Returns (typically): dict[str, Any] |
| `_execute_job` | Helper within this module. | `job_name, run_config` | Returns context-dependent output or mutates state. |
| `_safe_getattr` | Fetches data and returns it. | `obj, name, default` | Returns (typically): Any |
| `_extract_dagster_runtime` | Extracts structured information. | `result` | Returns (typically): dict[str, Any] |
| `_attach_runtime_to_payload` | Loads configuration/data. | `payload, runtime` | Returns (typically): dict[str, Any] |
| `_build_orchestration_failure_payload` | Loads configuration/data. | `none` | Returns (typically): dict[str, Any] |
| `run_transcription_pipeline` | Executes a full runnable flow. | `none` | Returns (typically): dict[str, Any] |
| `run_full_ai_pipeline` | Executes a full runnable flow. | `none` | Returns (typically): dict[str, Any] |

## forecasting/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Shared forecasting modules for TimesFM integration.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/dagster_handler.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `run_forecasting_handler` | Executes a full runnable flow. | `payload` | Returns (typically): dict[str, Any] |

## forecasting/pipeline.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `ForecastRequest` (object): No explicit class-level docstring.
  - `ForecastingError` (Exception): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_int_env` | Helper within this module. | `name, default` | Returns (typically): int |
| `detect_forecast_request` | Helper within this module. | `none` | Returns (typically): ForecastRequest |
| `_is_numeric` | Helper within this module. | `value` | Returns (typically): bool |
| `_to_float` | Helper within this module. | `value` | Returns (typically): float | None |
| `_parse_datetime` | Parses raw input to structured output. | `value` | Returns (typically): datetime | None |
| `_explicit_time_priority` | Helper within this module. | `column` | Returns (typically): int |
| `_choose_time_column` | Helper within this module. | `none` | Returns (typically): tuple[str | None, str] |
| `_choose_value_column` | Helper within this module. | `none` | Returns (typically): str | None |
| `_sorted_series` | Helper within this module. | `rows, time_column, value_column` | Returns (typically): list[tuple[datetime, float]] |
| `_infer_frequency` | Infers values from context. | `sorted_points` | Returns (typically): timedelta |
| `_validate_spacing_consistency` | Validates input/business constraints. | `sorted_points` | Returns (typically): tuple[bool, str] |
| `_frequency_to_granularity` | Helper within this module. | `frequency` | Returns (typically): str |
| `_format_ds` | Helper within this module. | `dt` | Returns (typically): str |
| `_escape_sql_string` | Helper within this module. | `value` | Returns (typically): str |
| `_build_inline_clickhouse_sql` | Builds payload/contract/structured data. | `rows` | Returns (typically): str |
| `_series_row` | Helper within this module. | `dt, value, series_type` | Returns (typically): dict[str, Any] |
| `_chart_series_config` | Helper within this module. | `none` | Returns (typically): list[dict[str, Any]] |
| `_sort_series_rows` | Helper within this module. | `rows` | Returns (typically): list[dict[str, Any]] |
| `_validate_forecast_points` | Validates input/business constraints. | `none` | Returns (typically): str |
| `_build_historical_only_dataset` | Builds payload/contract/structured data. | `none` | Returns (typically): dict[str, Any] |
| `_fill_missing_values` | Helper within this module. | `values` | Returns (typically): list[float] |
| `build_forecast_dataset` | Builds payload/contract/structured data. | `none` | Returns (typically): dict[str, Any] |
| `ForecastingError.__init__` | Helper within this module. | `self, code, message` | Returns (typically): None |
| `ForecastingError.to_dict` | Helper within this module. | `self` | Returns (typically): dict[str, Any] |

## forecasting/timesfm/run.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_load_model` | Loads configuration/data. | `source` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/src/timesfm/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM API.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/src/timesfm/configs.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Abstract configs for TimesFM layers.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `ForecastConfig` (object): Options for forecasting.
  - `ResidualBlockConfig` (object): Framework-agnostic config for a residual block.
  - `RandomFourierFeaturesConfig` (object): Framework-agnostic config for random fourier features.
  - `TransformerConfig` (object): Framework-agnostic config for a transformer.
  - `StackedTransformersConfig` (object): Framework-agnostic config for a stacked transformers.
- **Important Functions/Methods:** none

## forecasting/timesfm/src/timesfm/flax/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/src/timesfm/flax/dense.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Dense layers for TimesFM.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `ResidualBlock` (nnx.Module): Residual block with two linear layers and a linear residual connection.
  - `RandomFourierFeatures` (nnx.Module): Random Fourier features layer.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `ResidualBlock.__init__` | Helper within this module. | `self, config` | Returns context-dependent output or mutates state. |
| `ResidualBlock.__call__` | Helper within this module. | `self, x` | Returns (typically): Float[Array, 'b ... o'] |
| `RandomFourierFeatures.__init__` | Helper within this module. | `self, config` | Returns context-dependent output or mutates state. |
| `RandomFourierFeatures.__call__` | Helper within this module. | `self, x` | Returns (typically): Float[Array, 'b ... o'] |

## forecasting/timesfm/src/timesfm/flax/normalization.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Normalization layers for TimesFM.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `RMSNorm` (nnx.Module): RMS normalization.
  - `LayerNorm` (nnx.Module): Layer normalization replica of  LayerNorm.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `RMSNorm.__init__` | Helper within this module. | `self, num_features` | Returns context-dependent output or mutates state. |
| `RMSNorm.__call__` | Helper within this module. | `self, inputs` | Returns (typically): Float[Array, 'b ... d'] |
| `LayerNorm.__init__` | Helper within this module. | `self, num_features` | Returns context-dependent output or mutates state. |
| `LayerNorm.__call__` | Helper within this module. | `self, inputs` | Returns (typically): Float[Array, 'b ... d'] |

## forecasting/timesfm/src/timesfm/flax/transformer.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Transformer layers for TimesFM.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `RotaryPositionalEmbedding` (nnx.Module): Rotary positional embedding.
  - `PerDimScale` (nnx.Module): Per-dimension scaling.
  - `MultiHeadAttention` (nnx.Module): Multi-head attention.
  - `Transformer` (nnx.Module): Classic Transformer used in TimesFM.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `make_attn_mask` | Makes attention mask. | `query_length, num_all_masked_kv, query_index_offset, kv_length` | Returns (typically): Bool[Array, 'b 1 q n'] |
| `RotaryPositionalEmbedding.__init__` | Helper within this module. | `self, embedding_dims, min_timescale, max_timescale` | Returns context-dependent output or mutates state. |
| `RotaryPositionalEmbedding.__call__` | Generates a JTensor of sinusoids with different frequencies. | `self, inputs, position` | Returns context-dependent output or mutates state. |
| `PerDimScale.__init__` | Helper within this module. | `self, num_dims` | Returns context-dependent output or mutates state. |
| `PerDimScale.__call__` | Helper within this module. | `self, x` | Returns (typically): Float[Array, 'b ... d'] |
| `MultiHeadAttention.__init__` | Helper within this module. | `self, num_heads, in_features` | Returns context-dependent output or mutates state. |
| `MultiHeadAttention.__call__` | Applies multi-head dot product attention on the input data. | `self, inputs_q` | Returns (typically): tuple[Float[Array, 'b ... o'], DecodeCache | None] |
| `Transformer.__init__` | Helper within this module. | `self, config` | Returns context-dependent output or mutates state. |
| `Transformer.__call__` | Helper within this module. | `self, input_embeddings, patch_mask, decode_cache` | Returns (typically): tuple[Float[Array, 'b n d'], DecodeCache | None] |

## forecasting/timesfm/src/timesfm/flax/util.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Flax utility functions for TimesFM layers.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `DecodeCache` (object): Cache for decoding.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `update_running_stats` | Updates the running stats. | `n, mu, sigma, x, mask` | Returns (typically): tuple[tuple[Float[Array, 'b'], Float[Array, 'b'], Float[Array, 'b']], tuple[Float[Array, 'b'], Float[Array, 'b'], Float[Array, 'b']]] |
| `scan_along_axis` | Scans along an axis. | `f, init, xs, axis` | Returns context-dependent output or mutates state. |
| `revin` | Reversible per-instance normalization. | `x, mu, sigma, reverse` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/src/timesfm/timesfm_2p5/timesfm_2p5_base.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM 2p5 base implementation.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFM_2p5_200M_Definition` (object): Framework-agnostic config of TimesFM 2.5.
  - `TimesFM_2p5` (object): Abstract base class for TimesFM models.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `strip_leading_nans` | Removes contiguous NaN values from the beginning of a NumPy array. | `arr` | Returns context-dependent output or mutates state. |
| `linear_interpolation` | Performs linear interpolation to fill NaN values in a 1D numpy array. | `arr` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5.load_checkpoint` | Loads a TimesFM model from a checkpoint. | `self, path` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5.compile` | Compiles the TimesFM model for fast decoding. | `self, forecast_config` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5.forecast` | Forecasts the time series. | `self, horizon, inputs` | Returns (typically): tuple[np.ndarray, np.ndarray] |
| `TimesFM_2p5.forecast_with_covariates` | Forecasts on a list of time series with covariates. | `self, inputs, dynamic_numerical_covariates, dynamic_categorical_covariates, static_numerical_covariates, static_categorical_covariates, xreg_mode, normalize_xreg_target_per_input, ridge, max_rows_per_col, force_on_cpu` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/src/timesfm/timesfm_2p5/timesfm_2p5_flax.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM models in Flax.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFM_2p5_200M_flax_module` (nnx.Module): TimesFM 2.5 with 200M parameters.
  - `TimesFM_2p5_200M_flax` (timesfm_2p5_base.TimesFM_2p5): Flax implementation of TimesFM 2.5 with 200M parameters.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `try_gc` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `_create_stacked_transformers` | Creates a new object/resource. | `config, key` | Returns context-dependent output or mutates state. |
| `_scan_along_axis` | Scans along an axis. | `f, init, xs, axis` | Returns context-dependent output or mutates state. |
| `_apply_stacked_transformers` | Helper within this module. | `model, x, m, decode_cache` | Returns (typically): Float[Array, 'b n d'] |
| `_flip_quantile_fn` | Helper within this module. | `x` | Returns context-dependent output or mutates state. |
| `_force_flip_invariance_fn` | Forces flip invariance. | `flipped_pf_outputs, flipped_quantile_spreads, flipped_ar_outputs` | Returns context-dependent output or mutates state. |
| `_use_continuous_quantile_head_fn` | Uses continuous quantile head. | `full_forecast, quantile_spreads, max_horizon` | Returns context-dependent output or mutates state. |
| `_fix_quantile_crossing_fn` | Fixes quantile crossing. | `full_forecast` | Returns context-dependent output or mutates state. |
| `_before_model_decode` | All Jax steps before model decode call. | `fc, inputs, masks` | Returns context-dependent output or mutates state. |
| `_after_model_decode` | All Jax steps after model decode call. | `fc, pf_outputs, quantile_spreads, ar_outputs, flipped_pf_outputs, flipped_quantile_spreads, flipped_ar_outputs, is_positive, mu, sigma, p` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_flax_module.__init__` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_flax_module.__call__` | Helper within this module. | `self, inputs, masks, decode_cache` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_flax_module.decode` | Helper within this module. | `self, horizon, inputs, masks` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_flax_module.compile` | Compiles query/contract/prompt. | `self, context, horizon, per_core_batch_size` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_flax.from_pretrained` | Loads a Flax TimesFM model. | `cls, model_id` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_flax.compile` | Compiles query/contract/prompt. | `self, forecast_config, dryrun` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/src/timesfm/timesfm_2p5/timesfm_2p5_torch.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM models.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFM_2p5_200M_torch_module` (nn.Module): TimesFM 2.5 with 200M parameters.
  - `TimesFM_2p5_200M_torch` (timesfm_2p5_base.TimesFM_2p5, PyTorchModelHubMixin): PyTorch implementation of TimesFM 2.5 with 200M parameters.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `TimesFM_2p5_200M_torch_module.__init__` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_torch_module.load_checkpoint` | Loads a PyTorch TimesFM model from a checkpoint. | `self, path` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_torch_module.forward` | Helper within this module. | `self, inputs, masks, decode_caches` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_torch_module.decode` | Decodes the time series. | `self, horizon, inputs, masks` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_torch_module.forecast_naive` | Forecasts the time series. | `self, horizon, inputs` | Returns (typically): list[np.ndarray] |
| `TimesFM_2p5_200M_torch.__init__` | Helper within this module. | `self, torch_compile, config` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_torch._from_pretrained` | Loads a PyTorch safetensors TimesFM model from a local path or the Hugging | `cls` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_torch._save_pretrained` | Saves the model's state dictionary to a safetensors file. This method | `self, save_directory` | Returns context-dependent output or mutates state. |
| `TimesFM_2p5_200M_torch.compile` | Attempts to compile the model for fast decoding. | `self, forecast_config` | Returns (typically): None |

## forecasting/timesfm/src/timesfm/torch/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/src/timesfm/torch/dense.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Dense layers for TimesFM.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `ResidualBlock` (nn.Module): Residual block with two linear layers and a linear residual connection.
  - `RandomFourierFeatures` (nn.Module): Random Fourier features layer.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `ResidualBlock.__init__` | Helper within this module. | `self, config` | Returns context-dependent output or mutates state. |
| `ResidualBlock.forward` | Helper within this module. | `self, x` | Returns (typically): torch.Tensor |
| `RandomFourierFeatures.__init__` | Helper within this module. | `self, config` | Returns context-dependent output or mutates state. |
| `RandomFourierFeatures.forward` | Helper within this module. | `self, x` | Returns (typically): torch.Tensor |

## forecasting/timesfm/src/timesfm/torch/normalization.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Normalization layers for TimesFM.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `RMSNorm` (nn.Module): RMS normalization.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `RMSNorm.__init__` | Helper within this module. | `self, num_features` | Returns context-dependent output or mutates state. |
| `RMSNorm.forward` | Helper within this module. | `self, inputs` | Returns (typically): torch.Tensor |

## forecasting/timesfm/src/timesfm/torch/transformer.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Transformer layers for TimesFM.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `RotaryPositionalEmbedding` (nn.Module): Rotary positional embedding.
  - `PerDimScale` (nn.Module): Per-dimension scaling.
  - `MultiHeadAttention` (nn.Module): Multi-head attention.
  - `Transformer` (nn.Module): Classic Transformer used in TimesFM.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `make_attn_mask` | Makes attention mask. | `query_length, num_all_masked_kv, query_index_offset, kv_length` | Returns (typically): torch.Tensor |
| `_dot_product_attention` | Computes dot-product attention given query, key, and value. | `query, key, value, mask` | Returns context-dependent output or mutates state. |
| `_torch_dot_product_attention` | Performs the exact same (unscaled) attention as the above function, | `query, key, value, mask` | Returns context-dependent output or mutates state. |
| `RotaryPositionalEmbedding.__init__` | Helper within this module. | `self, embedding_dims, min_timescale, max_timescale` | Returns context-dependent output or mutates state. |
| `RotaryPositionalEmbedding.forward` | Generates a JTensor of sinusoids with different frequencies. | `self, inputs, position` | Returns context-dependent output or mutates state. |
| `PerDimScale.__init__` | Helper within this module. | `self, num_dims` | Returns context-dependent output or mutates state. |
| `PerDimScale.forward` | Helper within this module. | `self, x` | Returns (typically): torch.Tensor |
| `MultiHeadAttention.__init__` | Helper within this module. | `self, num_heads, in_features` | Returns context-dependent output or mutates state. |
| `MultiHeadAttention.forward` | Helper within this module. | `self, inputs_q` | Returns (typically): tuple[torch.Tensor, DecodeCache | None] |
| `Transformer.__init__` | Helper within this module. | `self, config` | Returns context-dependent output or mutates state. |
| `Transformer.forward` | Helper within this module. | `self, input_embeddings, patch_mask, decode_cache` | Returns (typically): tuple[torch.Tensor, DecodeCache | None] |

## forecasting/timesfm/src/timesfm/torch/util.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** PyTorch utility functions for TimesFM layers.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `DecodeCache` (object): Cache for decoding.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `update_running_stats` | Updates the running stats. | `n, mu, sigma, x, mask` | Returns (typically): tuple[tuple[torch.Tensor, torch.Tensor, torch.Tensor], tuple[torch.Tensor, torch.Tensor, torch.Tensor]] |
| `revin` | Reversible instance normalization. | `x, mu, sigma, reverse` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/src/timesfm/utils/xreg_lib.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Helper functions for in-context covariates and regression.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `BatchedInContextXRegBase` (object): Helper class for in-context regression covariate formatting.
  - `BatchedInContextXRegLinear` (BatchedInContextXRegBase): Linear in-context regression model.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_unnest` | Helper within this module. | `nested` | Returns (typically): np.ndarray |
| `_repeat` | Helper within this module. | `elements, counts` | Returns (typically): np.ndarray |
| `_to_padded_jax_array` | Helper within this module. | `x` | Returns (typically): jax.Array |
| `normalize` | Normalizes values to canonical shape. | `batch` | Returns context-dependent output or mutates state. |
| `renormalize` | Normalizes values to canonical shape. | `batch, stats` | Returns context-dependent output or mutates state. |
| `BatchedInContextXRegBase.__init__` | Initializes with the exogenous covariate inputs. | `self, targets, train_lens, test_lens, train_dynamic_numerical_covariates, train_dynamic_categorical_covariates, test_dynamic_numerical_covariates, test_dynamic_categorical_covariates, static_numerical_covariates, static_categorical_covariates` | Returns (typically): None |
| `BatchedInContextXRegBase._assert_covariates` | Verifies the validity of the covariate inputs. | `self, assert_covariate_shapes` | Returns (typically): None |
| `BatchedInContextXRegBase.create_covariate_matrix` | Creates target vector and covariate matrices for in context regression. | `self, one_hot_encoder_drop, use_intercept, assert_covariates, assert_covariate_shapes` | Returns (typically): tuple[np.ndarray, np.ndarray, np.ndarray] |
| `BatchedInContextXRegBase.fit` | Helper within this module. | `self` | Returns (typically): Any |
| `BatchedInContextXRegLinear.fit` | Fits a linear model for in-context regression. | `self, ridge, one_hot_encoder_drop, use_intercept, force_on_cpu, max_rows_per_col, max_rows_per_col_sample_seed, debug_info, assert_covariates, assert_covariate_shapes` | Returns (typically): list[np.ndarray] | tuple[list[np.ndarray], list[np.ndarray], jax.Array, jax.Array, jax.Array] |

## forecasting/timesfm/timesfm-forecasting/examples/anomaly-detection/detect_anomalies.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM Anomaly Detection Example — Two-Phase Method
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `detect_context_anomalies` | Linear detrend + Z-score anomaly detection on context period. | `values, dates` | Returns (typically): tuple[list[dict], np.ndarray, np.ndarray, float] |
| `build_synthetic_future` | Build a plausible future with 3 injected anomalies. | `context, n, seed` | Returns (typically): tuple[np.ndarray, list[int]] |
| `detect_forecast_anomalies` | Classify each forecast month by which PI band it falls outside. | `future_values, point, quant_fc, future_dates, injected_at` | Returns (typically): list[dict] |
| `plot_results` | Helper within this module. | `context_dates, context_values, ctx_records, trend_line, residuals, res_std, future_dates, future_values, point_fc, quant_fc, fc_records` | Returns (typically): None |
| `main` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/timesfm-forecasting/examples/covariates-forecasting/demo_covariates.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM Covariates (XReg) Example
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `generate_sales_data` | Generate synthetic retail sales data with covariate components stored separately. | `none` | Returns (typically): dict |
| `create_visualization` | 2x2 figure -- ALL panels share x-axis = weeks 0-35. | `data` | Returns (typically): None |
| `demonstrate_api` | Helper within this module. | `none` | Returns (typically): None |
| `explain_xreg_modes` | Helper within this module. | `none` | Returns (typically): None |
| `main` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/timesfm-forecasting/examples/finetuning/finetune_lora.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Fine-tune TimesFM 2.5 with LoRA using HuggingFace Transformers + PEFT.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimeSeriesRandomWindowDataset` (Dataset): Random-window dataset for time series fine-tuning.
  - `TimeSeriesLastWindowDataset` (Dataset): Validation dataset using the last window of each series.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `load_retail_sales` | Download and prepare the retail sales dataset. | `context_len, horizon_len, num_samples, seed` | Returns (typically): tuple[TimeSeriesRandomWindowDataset, TimeSeriesLastWindowDataset] |
| `train` | Helper within this module. | `args` | Returns (typically): None |
| `evaluate` | Compare zero-shot vs fine-tuned on a subset of stores. | `args` | Returns (typically): None |
| `parse_args` | Parses raw input to structured output. | `none` | Returns (typically): argparse.Namespace |
| `main` | Helper within this module. | `none` | Returns (typically): None |
| `TimeSeriesRandomWindowDataset.__init__` | Helper within this module. | `self, series_list, context_len, horizon_len, num_samples, seed` | Returns context-dependent output or mutates state. |
| `TimeSeriesRandomWindowDataset.__len__` | Helper within this module. | `self` | Returns (typically): int |
| `TimeSeriesRandomWindowDataset.__getitem__` | Fetches data and returns it. | `self, i` | Returns context-dependent output or mutates state. |
| `TimeSeriesLastWindowDataset.__init__` | Helper within this module. | `self, series_list, context_len, horizon_len` | Returns context-dependent output or mutates state. |
| `TimeSeriesLastWindowDataset.__len__` | Helper within this module. | `self` | Returns (typically): int |
| `TimeSeriesLastWindowDataset.__getitem__` | Fetches data and returns it. | `self, i` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/timesfm-forecasting/examples/global-temperature/generate_animation_data.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Generate animation data for interactive forecast visualization.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `main` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/timesfm-forecasting/examples/global-temperature/generate_gif.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Generate animated GIF showing forecast evolution.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `create_frame` | Create a single frame of the animation with fixed axes. | `ax, step_data, actual_data, final_forecast, total_steps, x_min, x_max, y_min, y_max` | Returns (typically): None |
| `main` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/timesfm-forecasting/examples/global-temperature/generate_html.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Generate a self-contained HTML file with embedded animation data.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `main` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/timesfm-forecasting/examples/global-temperature/run_forecast.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Run TimesFM forecast on global temperature anomaly data.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/timesfm-forecasting/examples/global-temperature/visualize_forecast.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Visualize TimesFM forecast results for global temperature anomaly.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `main` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/timesfm-forecasting/scripts/check_system.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM System Requirements Preflight Checker.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `CheckResult` (object): No explicit class-level docstring.
  - `SystemReport` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_get_total_ram_gb` | Return total physical RAM in GB, cross-platform. | `none` | Returns (typically): float |
| `_get_available_ram_gb` | Return available RAM in GB. | `none` | Returns (typically): float |
| `check_ram` | Check if system has enough RAM. | `profile` | Returns (typically): CheckResult |
| `check_gpu` | Check GPU availability and VRAM. | `none` | Returns (typically): CheckResult |
| `check_disk` | Check available disk space for model download. | `profile` | Returns (typically): CheckResult |
| `check_python` | Check Python version >= 3.10. | `none` | Returns (typically): CheckResult |
| `check_package` | Check if a Python package is installed. | `pkg_name, import_name` | Returns (typically): CheckResult |
| `recommend_batch_size` | Recommend per_core_batch_size based on available resources. | `report` | Returns (typically): int |
| `estimate_memory_gb` | Estimate memory requirements for a dataset. | `num_series, context_length, horizon, batch_size, model_version` | Returns (typically): dict[str, float] |
| `check_dataset_fit` | Check if a dataset will fit in available memory. | `num_series, context_length, horizon, batch_size, model_version` | Returns (typically): tuple[bool, str, dict[str, float]] |
| `print_memory_estimate` | Print a detailed memory estimate for a dataset. | `num_series, context_length, horizon, batch_size, model_version` | Returns (typically): None |
| `run_checks` | Run all system checks and return a report. | `model_version` | Returns (typically): SystemReport |
| `print_report` | Print a human-readable report to stdout. | `report` | Returns (typically): None |
| `main` | Helper within this module. | `none` | Returns (typically): None |
| `CheckResult.icon` | Helper within this module. | `self` | Returns (typically): str |
| `CheckResult.__str__` | Helper within this module. | `self` | Returns (typically): str |
| `SystemReport.passed` | Helper within this module. | `self` | Returns (typically): bool |
| `SystemReport.to_dict` | Helper within this module. | `self` | Returns (typically): dict[str, Any] |

## forecasting/timesfm/timesfm-forecasting/scripts/forecast_csv.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** End-to-end CSV forecasting with TimesFM.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `run_preflight` | Run the system preflight check and return the report. | `none` | Returns (typically): dict |
| `load_model` | Load and compile the TimesFM model. | `batch_size` | Returns context-dependent output or mutates state. |
| `load_csv` | Load CSV and identify time series columns. | `path, date_col, value_cols` | Returns (typically): tuple[pd.DataFrame, list[str], str | None] |
| `forecast_series` | Forecast all series and return results dict. | `model, df, value_cols, horizon` | Returns (typically): dict[str, dict] |
| `write_csv_output` | Write forecast results to CSV. | `results, output_path, df, date_col, horizon` | Returns (typically): None |
| `write_json_output` | Write forecast results to JSON. | `results, output_path` | Returns (typically): None |
| `main` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/v1/experiments/baselines/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/v1/experiments/baselines/timegpt_pipeline.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `Forecaster` (object): Borrowed from
  - `TimeGPT` (Forecaster): Borrowed from
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `get_seasonality` | Fetches data and returns it. | `freq` | Returns (typically): int |
| `maybe_convert_col_to_datetime` | Helper within this module. | `df, col_name` | Returns (typically): pd.DataFrame |
| `zero_pad_time_series` | If time_series length is less than min_length, front pad it with zeros. | `df, freq, min_length` | Returns context-dependent output or mutates state. |
| `run_timegpt` | Executes a full runnable flow. | `train_df, horizon, freq, seasonality, level, dataset, model` | Returns (typically): Tuple[pd.DataFrame, float, str] |
| `Forecaster.forecast` | Helper within this module. | `self, df, h, freq` | Returns (typically): pd.DataFrame |
| `Forecaster.cross_validation` | Helper within this module. | `self, df, h, freq, n_windows, step_size` | Returns (typically): pd.DataFrame |
| `TimeGPT.__init__` | Helper within this module. | `self, api_key, base_url, max_retries, model, alias` | Returns context-dependent output or mutates state. |
| `TimeGPT._get_client` | Fetches data and returns it. | `self` | Returns (typically): NixtlaClient |
| `TimeGPT.forecast` | Helper within this module. | `self, df, h, freq, level, chunk_size` | Returns (typically): pd.DataFrame |

## forecasting/timesfm/v1/experiments/extended_benchmarks/run_timegpt.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Evaluation script for timegpt.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `main` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/v1/experiments/extended_benchmarks/run_timesfm.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Evaluation script for timesfm.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `main` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/v1/experiments/extended_benchmarks/utils.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Forked from https://github.com/Nixtla/nixtla/blob/main/experiments/amazon-chronos/src/utils.py.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `ExperimentHandler` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `parallel_transform` | Helper within this module. | `inp` | Returns context-dependent output or mutates state. |
| `quantile_loss` | Helper within this module. | `df, models, q, id_col, target_col` | Returns (typically): pd.DataFrame |
| `ExperimentHandler.__init__` | Helper within this module. | `self, dataset, quantiles, results_dir, models_dir` | Returns context-dependent output or mutates state. |
| `ExperimentHandler._maybe_download_m3_or_m5_file` | Loads configuration/data. | `dataset` | Returns context-dependent output or mutates state. |
| `ExperimentHandler._transform_quantiles_to_levels` | Helper within this module. | `quantiles` | Returns (typically): List[int] |
| `ExperimentHandler._create_dir_if_not_exists` | Creates a new object/resource. | `directory` | Returns context-dependent output or mutates state. |
| `ExperimentHandler._transform_gluonts_instance_to_df` | Helper within this module. | `ts, last_n` | Returns (typically): pd.DataFrame |
| `ExperimentHandler._transform_gluonts_dataset_to_df` | Helper within this module. | `gluonts_dataset, last_n` | Returns (typically): pd.DataFrame |
| `ExperimentHandler.train_df` | Helper within this module. | `self` | Returns (typically): pd.DataFrame |
| `ExperimentHandler.test_df` | Helper within this module. | `self` | Returns (typically): pd.DataFrame |
| `ExperimentHandler.save_dataframe` | Persists changes. | `self, df, file_name` | Returns context-dependent output or mutates state. |
| `ExperimentHandler.save_results` | Persists changes. | `self, fcst_df, total_time, model_name` | Returns context-dependent output or mutates state. |
| `ExperimentHandler.fcst_from_level_to_quantiles` | Helper within this module. | `self, fcst_df, model_name` | Returns (typically): pd.DataFrame |
| `ExperimentHandler.evaluate_models` | Helper within this module. | `self, models` | Returns (typically): pd.DataFrame |
| `ExperimentHandler.evaluate_from_predictions` | Helper within this module. | `self, models, fcsts_df, times_df` | Returns (typically): pd.DataFrame |

## forecasting/timesfm/v1/experiments/long_horizon_benchmarks/run_eval.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Eval pipeline.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `get_forecasts` | Get forecasts. | `model_path, model, past, freq, pred_len` | Returns context-dependent output or mutates state. |
| `_mse` | mse loss. | `y_pred, y_true` | Returns context-dependent output or mutates state. |
| `_mae` | mae loss. | `y_pred, y_true` | Returns context-dependent output or mutates state. |
| `_smape` | _smape loss. | `y_pred, y_true` | Returns context-dependent output or mutates state. |
| `eval` | Eval pipeline. | `none` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/v1/peft/finetune.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Finetune pipeline.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `finetune` | Helper within this module. | `none` | Returns (typically): None |

## forecasting/timesfm/v1/src/adapter/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** adapter init file.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/v1/src/adapter/dora_layers.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `DoraTheta` (base_layer.Theta): No explicit class-level docstring.
  - `DoraThetaDescriptor` (object): Dot syntax accession descriptor.
  - `DoraLinear` (linears.Linear): No explicit class-level docstring.
  - `DoraAttentionProjection` (attentions.AttentionProjection): No explicit class-level docstring.
  - `DoraCombinedQKVProjection` (attentions.CombinedQKVProjectionLayer): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `DoraTheta.__init__` | Helper within this module. | `self, module` | Returns context-dependent output or mutates state. |
| `DoraTheta._dora_initialized` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `DoraTheta._dorafy_var` | Helper within this module. | `self, w` | Returns context-dependent output or mutates state. |
| `DoraTheta.__getattr__` | Fetches data and returns it. | `self, k` | Returns context-dependent output or mutates state. |
| `DoraTheta.__getitem__` | Fetches data and returns it. | `self, k` | Returns context-dependent output or mutates state. |
| `DoraThetaDescriptor.__get__` | Fetches data and returns it. | `self, obj, objtype` | Returns context-dependent output or mutates state. |
| `DoraLinear.setup` | Helper within this module. | `self` | Returns (typically): None |
| `DoraAttentionProjection.setup` | Helper within this module. | `self` | Returns (typically): None |
| `DoraCombinedQKVProjection.setup` | Helper within this module. | `self` | Returns (typically): None |

## forecasting/timesfm/v1/src/adapter/lora_layers.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `LoraTheta` (base_layer.Theta): No explicit class-level docstring.
  - `LoraThetaDescriptor` (object): Dot syntax accession descriptor.
  - `LoraLinear` (linears.Linear): No explicit class-level docstring.
  - `LoraAttentionProjection` (attentions.AttentionProjection): No explicit class-level docstring.
  - `LoraCombinedQKVProjection` (attentions.CombinedQKVProjectionLayer): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `LoraTheta.__init__` | Helper within this module. | `self, module` | Returns context-dependent output or mutates state. |
| `LoraTheta._lora_initialized` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `LoraTheta._lorafy_var` | Helper within this module. | `self, w` | Returns context-dependent output or mutates state. |
| `LoraTheta.__getattr__` | Fetches data and returns it. | `self, k` | Returns context-dependent output or mutates state. |
| `LoraTheta.__getitem__` | Fetches data and returns it. | `self, k` | Returns context-dependent output or mutates state. |
| `LoraThetaDescriptor.__get__` | Fetches data and returns it. | `self, obj, objtype` | Returns context-dependent output or mutates state. |
| `LoraLinear.setup` | Helper within this module. | `self` | Returns (typically): None |
| `LoraAttentionProjection.setup` | Helper within this module. | `self` | Returns (typically): None |
| `LoraCombinedQKVProjection.setup` | Helper within this module. | `self` | Returns (typically): None |

## forecasting/timesfm/v1/src/adapter/utils.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** This file provides functionality for loading and merging adapter weights
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `get_adapter_params` | Extracts adapter parameters from the given model parameters for saving the checkpoint. | `params, lora_target_modules, num_layers, use_dora` | Returns (typically): dict |
| `load_adapter_checkpoint` | Loads an adapter checkpoint and merges it with the original model weights. | `model, adapter_checkpoint_path, lora_rank, lora_target_modules, use_dora` | Returns (typically): None |
| `_merge_adapter_weights` | Merges adapter weights with the original model weights. | `model, adapter_train_state, lora_target_modules, num_layers, use_dora` | Returns (typically): None |
| `_get_adapter_weight_params` | Extracts adapter weight parameters from the given variable weight hyperparameters. | `var_weight_hparams, lora_target_modules, num_layers, use_dora` | Returns (typically): dict |
| `load_adapter_layer` | Updates target modules with adapter layers. | `mdl_vars, model, lora_rank, lora_target_modules, use_dora` | Returns (typically): tuple[pax_fiddle.Config, pax_fiddle.Config] |
| `_initialize_adapter_params` | Initializes and adds adapter parameters to target modules. | `mdl_vars, num_layers, lora_rank, lora_target_modules, use_dora, seed` | Returns (typically): dict |

## forecasting/timesfm/v1/src/finetuning/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/v1/src/finetuning/finetuning_example.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Example usage of the TimesFM Finetuning Framework.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimeSeriesDataset` (Dataset): Dataset for time series data compatible with TimesFM.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `prepare_datasets` | Prepare training and validation datasets from time series data. | `series, context_length, horizon_length, freq_type, train_split` | Returns (typically): Tuple[Dataset, Dataset] |
| `get_model` | Fetches data and returns it. | `load_weights` | Returns context-dependent output or mutates state. |
| `plot_predictions` | Plot model predictions against ground truth for a batch of validation data. | `model, val_dataset, save_path` | Returns (typically): None |
| `get_data` | Fetches data and returns it. | `context_len, horizon_len, freq_type` | Returns (typically): Tuple[Dataset, Dataset] |
| `single_gpu_example` | Basic example of finetuning TimesFM on stock data. | `none` | Returns context-dependent output or mutates state. |
| `setup_process` | Setup process function with optimized CUDA handling. | `rank, world_size, model, config, train_dataset, val_dataset, return_dict` | Returns context-dependent output or mutates state. |
| `multi_gpu_example` | Example of finetuning TimesFM using multiple GPUs with optimized spawn. | `none` | Returns context-dependent output or mutates state. |
| `main` | Main function that selects and runs the appropriate training mode. | `argv` | Returns context-dependent output or mutates state. |
| `TimeSeriesDataset.__init__` | Initialize dataset. | `self, series, context_length, horizon_length, freq_type` | Returns context-dependent output or mutates state. |
| `TimeSeriesDataset._prepare_samples` | Prepare sliding window samples from the time series. | `self` | Returns (typically): None |
| `TimeSeriesDataset.__len__` | Helper within this module. | `self` | Returns (typically): int |
| `TimeSeriesDataset.__getitem__` | Fetches data and returns it. | `self, index` | Returns (typically): Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor] |

## forecasting/timesfm/v1/src/finetuning/finetuning_torch.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM Finetuner: A flexible framework for finetuning TimesFM models on custom datasets.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `MetricsLogger` (ABC): Abstract base class for logging metrics during training.
  - `WandBLogger` (MetricsLogger): Weights & Biases implementation of metrics logging.
  - `DistributedManager` (object): Manages distributed training setup and cleanup.
  - `FinetuningConfig` (object): Configuration for model training.
  - `TimesFMFinetuner` (object): Handles model training and validation.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `MetricsLogger.log_metrics` | Log metrics to the specified backend. | `self, metrics, step` | Returns (typically): None |
| `MetricsLogger.close` | Clean up any resources used by the logger. | `self` | Returns (typically): None |
| `WandBLogger.__init__` | Helper within this module. | `self, project, config, rank` | Returns context-dependent output or mutates state. |
| `WandBLogger.log_metrics` | Log metrics to W&B if on the main process. | `self, metrics, step` | Returns (typically): None |
| `WandBLogger.close` | Finish the W&B run if on the main process. | `self` | Returns (typically): None |
| `DistributedManager.__init__` | Helper within this module. | `self, world_size, rank, master_addr, master_port, backend` | Returns context-dependent output or mutates state. |
| `DistributedManager.setup` | Initialize the distributed environment. | `self` | Returns (typically): None |
| `DistributedManager.cleanup` | Clean up the distributed environment. | `self` | Returns (typically): None |
| `TimesFMFinetuner.__init__` | Helper within this module. | `self, model, config, rank, loss_fn, logger` | Returns context-dependent output or mutates state. |
| `TimesFMFinetuner._setup_distributed_model` | Configure model for distributed training. | `self` | Returns (typically): nn.Module |
| `TimesFMFinetuner._create_dataloader` | Create appropriate DataLoader based on training configuration. | `self, dataset, is_train` | Returns (typically): DataLoader |
| `TimesFMFinetuner._quantile_loss` | Calculates quantile loss. | `self, pred, actual, quantile` | Returns (typically): torch.Tensor |
| `TimesFMFinetuner._process_batch` | Process a single batch of data. | `self, batch` | Returns (typically): tuple |
| `TimesFMFinetuner._train_epoch` | Train for one epoch in a distributed setting. | `self, train_loader, optimizer` | Returns (typically): float |
| `TimesFMFinetuner._validate` | Perform validation. | `self, val_loader` | Returns (typically): float |
| `TimesFMFinetuner.finetune` | Train the model. | `self, train_dataset, val_dataset` | Returns (typically): Dict[str, Any] |

## forecasting/timesfm/v1/src/timesfm/__init__.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM init file.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## forecasting/timesfm/v1/src/timesfm/data_loader.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TF dataloaders for general timeseries datasets.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimeSeriesdata` (object): Data loader class.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `TimeSeriesdata.__init__` | Initialize objects. | `self, data_path, datetime_col, num_cov_cols, cat_cov_cols, ts_cols, train_range, val_range, test_range, hist_len, pred_len, batch_size, freq, normalize, epoch_len, holiday, permute` | Returns context-dependent output or mutates state. |
| `TimeSeriesdata._get_cat_cols` | Get categorical columns. | `self, cat_cov_cols` | Returns context-dependent output or mutates state. |
| `TimeSeriesdata._normalize_data` | Normalizes values to canonical shape. | `self` | Returns context-dependent output or mutates state. |
| `TimeSeriesdata.train_gen` | Generator for training data. | `self` | Returns context-dependent output or mutates state. |
| `TimeSeriesdata.test_val_gen` | Generator for validation/test data. | `self, mode, shift` | Returns context-dependent output or mutates state. |
| `TimeSeriesdata._get_features_and_ts` | Get features and ts in specified windows. | `self, dtimes, tsidx, hist_len` | Returns context-dependent output or mutates state. |
| `TimeSeriesdata.tf_dataset` | Tensorflow Dataset. | `self, mode, shift` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/v1/src/timesfm/patched_decoder.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Pax ML model for patched time-series decoder.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `ResidualBlock` (base_layer.BaseLayer): Simple feedforward block with residual connection.
  - `PatchedTimeSeriesDecoder` (base_layer.BaseLayer): Patch decoder layer for time-series foundation model.
  - `PatchedDecoderFinetuneModel` (base_model.BaseModel): Model class for finetuning patched time-series decoder.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_shift_padded_seq` | Shifts rows of seq based on the first 0 in each row of the mask. | `mask, seq` | Returns (typically): JTensor |
| `_masked_mean_std` | Calculates mean and standard deviation of arr across axis 1. | `inputs, padding` | Returns (typically): Tuple[JTensor, JTensor] |
| `_create_quantiles` | Returns the quantiles for forecasting. | `none` | Returns (typically): list[float] |
| `ResidualBlock.setup` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `ResidualBlock.__call__` | Helper within this module. | `self, inputs` | Returns (typically): JTensor |
| `PatchedTimeSeriesDecoder.setup` | Construct the model. | `self` | Returns (typically): None |
| `PatchedTimeSeriesDecoder.transform_decode_state` | Transforms all decode state variables based on transform_fn. | `self, transform_fn` | Returns (typically): None |
| `PatchedTimeSeriesDecoder._forward_transform` | Input is of shape [B, N, P]. | `self, inputs, patched_pads` | Returns (typically): Tuple[JTensor, Tuple[JTensor, JTensor]] |
| `PatchedTimeSeriesDecoder._reverse_transform` | Output is of shape [B, N, P, Q]. | `self, outputs, stats` | Returns (typically): JTensor |
| `PatchedTimeSeriesDecoder._preprocess_input` | Preprocess input for stacked transformer. | `self, input_ts, input_padding, pos_emb` | Returns (typically): Tuple[JTensor, JTensor, Optional[Tuple[JTensor, JTensor]], JTensor] |
| `PatchedTimeSeriesDecoder._postprocess_output` | Postprocess output of stacked transformer. | `self, model_output, num_outputs, stats` | Returns (typically): JTensor |
| `PatchedTimeSeriesDecoder.__call__` | PatchTST call. | `self, inputs` | Returns (typically): NestedMap |
| `PatchedTimeSeriesDecoder.decode` | Auto-regressive decoding without caching. | `self, inputs, horizon_len, output_patch_len, max_len, return_forecast_on_context` | Returns (typically): tuple[JTensor, JTensor] |
| `PatchedDecoderFinetuneModel.setup` | Helper within this module. | `self` | Returns (typically): None |
| `PatchedDecoderFinetuneModel.compute_predictions` | Helper within this module. | `self, input_batch` | Returns (typically): NestedMap |
| `PatchedDecoderFinetuneModel._quantile_loss` | Calculates quantile loss. | `self, pred, actual, quantile` | Returns (typically): JTensor |
| `PatchedDecoderFinetuneModel.compute_loss` | Helper within this module. | `self, prediction_output, input_batch` | Returns (typically): Tuple[NestedMap, NestedMap] |

## forecasting/timesfm/v1/src/timesfm/pytorch_patched_decoder.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Pytorch version of patched decoder.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFMConfig` (object): Config for initializing timesfm patched_decoder class.
  - `ResidualBlock` (nn.Module): TimesFM residual block.
  - `RMSNorm` (torch.nn.Module): Pax rms norm in pytorch.
  - `TransformerMLP` (nn.Module): Pax transformer MLP in pytorch.
  - `TimesFMAttention` (nn.Module): Implements the attention used in TimesFM.
  - `TimesFMDecoderLayer` (nn.Module): Transformer layer.
  - `StackedDecoder` (nn.Module): Stacked transformer layer.
  - `PositionalEmbedding` (torch.nn.Module): Generates position embedding for a given 1-d sequence.
  - `PatchedTimeSeriesDecoder` (nn.Module): Patched time-series decoder.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `create_quantiles` | Creates a new object/resource. | `none` | Returns (typically): list[float] |
| `_masked_mean_std` | Calculates mean and standard deviation of `inputs` across axis 1. | `inputs, padding` | Returns (typically): tuple[torch.Tensor, torch.Tensor] |
| `_shift_padded_seq` | Shifts rows of seq based on the first 0 in each row of the mask. | `mask, seq` | Returns (typically): torch.Tensor |
| `get_large_negative_number` | Returns a large negative value for the given dtype. | `dtype` | Returns (typically): torch.Tensor |
| `apply_mask_to_logits` | Applies a floating-point mask to a set of logits. | `logits, mask` | Returns (typically): torch.Tensor |
| `convert_paddings_to_mask` | Converts binary paddings to a logit mask ready to add to attention matrix. | `paddings, dtype` | Returns (typically): torch.Tensor |
| `causal_mask` | Computes and returns causal mask. | `input_t` | Returns (typically): torch.Tensor |
| `merge_masks` | Merges 2 masks. | `a, b` | Returns (typically): torch.Tensor |
| `ResidualBlock.__init__` | Helper within this module. | `self, input_dims, hidden_dims, output_dims` | Returns context-dependent output or mutates state. |
| `ResidualBlock.forward` | Helper within this module. | `self, x` | Returns context-dependent output or mutates state. |
| `RMSNorm.__init__` | Helper within this module. | `self, dim, eps, add_unit_offset` | Returns context-dependent output or mutates state. |
| `RMSNorm._norm` | Helper within this module. | `self, x` | Returns context-dependent output or mutates state. |
| `RMSNorm.forward` | Helper within this module. | `self, x` | Returns context-dependent output or mutates state. |
| `TransformerMLP.__init__` | Helper within this module. | `self, hidden_size, intermediate_size` | Returns context-dependent output or mutates state. |
| `TransformerMLP.forward` | Helper within this module. | `self, x, paddings` | Returns context-dependent output or mutates state. |
| `TimesFMAttention.__init__` | Helper within this module. | `self, hidden_size, num_heads, num_kv_heads, head_dim` | Returns context-dependent output or mutates state. |
| `TimesFMAttention._per_dim_scaling` | Helper within this module. | `self, query` | Returns (typically): torch.Tensor |
| `TimesFMAttention.forward` | Helper within this module. | `self, hidden_states, mask, kv_write_indices, kv_cache` | Returns (typically): torch.Tensor |
| `TimesFMDecoderLayer.__init__` | Helper within this module. | `self, hidden_size, intermediate_size, num_heads, num_kv_heads, head_dim, rms_norm_eps` | Returns context-dependent output or mutates state. |
| `TimesFMDecoderLayer.forward` | Helper within this module. | `self, hidden_states, mask, paddings, kv_write_indices, kv_cache` | Returns (typically): torch.Tensor |
| `StackedDecoder.__init__` | Helper within this module. | `self, hidden_size, intermediate_size, num_heads, num_kv_heads, head_dim, num_layers, rms_norm_eps` | Returns context-dependent output or mutates state. |
| `StackedDecoder.forward` | Helper within this module. | `self, hidden_states, paddings, kv_write_indices, kv_caches` | Returns (typically): torch.Tensor |
| `PositionalEmbedding.__init__` | Helper within this module. | `self, embedding_dims, min_timescale, max_timescale` | Returns (typically): None |
| `PositionalEmbedding.forward` | Generates a Tensor of sinusoids with different frequencies. | `self, seq_length, position` | Returns context-dependent output or mutates state. |
| `PatchedTimeSeriesDecoder.__init__` | Helper within this module. | `self, config` | Returns context-dependent output or mutates state. |
| `PatchedTimeSeriesDecoder._forward_transform` | Input is of shape [B, N, P]. | `self, inputs, patched_pads` | Returns (typically): tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]] |
| `PatchedTimeSeriesDecoder._reverse_transform` | Output is of shape [B, N, P, Q]. | `self, outputs, stats` | Returns (typically): torch.Tensor |
| `PatchedTimeSeriesDecoder._preprocess_input` | Preprocess input for stacked transformer. | `self, input_ts, input_padding` | Returns (typically): tuple[torch.Tensor, torch.Tensor, tuple[torch.Tensor, torch.Tensor] | None, torch.Tensor] |
| `PatchedTimeSeriesDecoder._postprocess_output` | Postprocess output of stacked transformer. | `self, model_output, num_outputs, stats` | Returns (typically): torch.Tensor |
| `PatchedTimeSeriesDecoder.forward` | Helper within this module. | `self, input_ts, input_padding, freq` | Returns (typically): torch.Tensor |
| `PatchedTimeSeriesDecoder.decode` | Auto-regressive decoding without caching. | `self, input_ts, paddings, freq, horizon_len, output_patch_len, max_len, return_forecast_on_context` | Returns (typically): tuple[torch.Tensor, torch.Tensor] |

## forecasting/timesfm/v1/src/timesfm/time_features.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Directory to extract time covariates.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimeCovariates` (object): Extract all time covariates except for holidays.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_distance_to_holiday` | Return distance to given holiday. | `holiday` | Returns context-dependent output or mutates state. |
| `TimeCovariates.__init__` | Init function. | `self, datetimes, normalized, holiday` | Returns context-dependent output or mutates state. |
| `TimeCovariates._minute_of_hour` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates._hour_of_day` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates._day_of_week` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates._day_of_month` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates._day_of_year` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates._month_of_year` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates._week_of_year` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates._get_holidays` | Fetches data and returns it. | `self` | Returns context-dependent output or mutates state. |
| `TimeCovariates.get_covariates` | Get all time covariates. | `self` | Returns context-dependent output or mutates state. |

## forecasting/timesfm/v1/src/timesfm/timesfm_base.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Base class for TimesFM inference. This will be common to PAX and Pytorch.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFmHparams` (object): Hparams used to initialize a TimesFM model for inference.
  - `TimesFmCheckpoint` (object): Checkpoint used to initialize a TimesFM model for inference.
  - `TimesFmBase` (object): Base TimesFM forecast API for inference.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `process_group` | Runs a major processing step. | `key, group, value_name, forecast_context_len` | Returns context-dependent output or mutates state. |
| `moving_average` | Calculates the moving average using NumPy's convolution function. | `arr, window_size` | Returns context-dependent output or mutates state. |
| `freq_map` | Returns the frequency map for the given frequency string. | `freq` | Returns context-dependent output or mutates state. |
| `strip_leading_nans` | Removes contiguous NaN values from the beginning of a NumPy array. | `arr` | Returns context-dependent output or mutates state. |
| `linear_interpolation` | Performs linear interpolation to fill NaN values in a 1D numpy array. | `arr` | Returns context-dependent output or mutates state. |
| `_normalize` | Normalizes values to canonical shape. | `batch` | Returns context-dependent output or mutates state. |
| `_renormalize` | Normalizes values to canonical shape. | `batch, stats` | Returns context-dependent output or mutates state. |
| `TimesFmBase._logging` | Helper within this module. | `self, s` | Returns context-dependent output or mutates state. |
| `TimesFmBase.__post_init__` | Additional initialization for subclasses before checkpoint loading. | `self` | Returns (typically): None |
| `TimesFmBase.__init__` | Initializes the TimesFM forecast API. | `self, hparams, checkpoint` | Returns (typically): None |
| `TimesFmBase.load_from_checkpoint` | Loads a checkpoint and compiles the decoder. | `self, checkpoint` | Returns (typically): None |
| `TimesFmBase._preprocess` | Formats and pads raw inputs to feed into the model. | `self, inputs, freq` | Returns (typically): tuple[np.ndarray, np.ndarray, np.ndarray, int] |
| `TimesFmBase._forecast` | Forecasts on a list of time series. | `self, inputs, freq, window_size, forecast_context_len, return_forecast_on_context` | Returns (typically): tuple[np.ndarray, np.ndarray] |
| `TimesFmBase.forecast` | Forecasts on a list of time series. | `self, inputs, freq, window_size, forecast_context_len, return_forecast_on_context, normalize` | Returns (typically): tuple[np.ndarray, np.ndarray] |
| `TimesFmBase.forecast_with_covariates` | Forecasts on a list of time series with covariates. | `self, inputs, dynamic_numerical_covariates, dynamic_categorical_covariates, static_numerical_covariates, static_categorical_covariates, freq, window_size, forecast_context_len, xreg_mode, normalize_xreg_target_per_input, ridge, max_rows_per_col, force_on_cpu` | Returns context-dependent output or mutates state. |
| `TimesFmBase.forecast_on_df` | Forecasts on a list of time series. | `self, inputs, freq, forecast_context_len, value_name, model_name, window_size, num_jobs, normalize, verbose` | Returns (typically): pd.DataFrame |

## forecasting/timesfm/v1/src/timesfm/timesfm_jax.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM JAX forecast API for inference.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFmJax` (timesfm_base.TimesFmBase): TimesFM forecast API for inference.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `TimesFmJax._get_sample_inputs` | Fetches data and returns it. | `self` | Returns context-dependent output or mutates state. |
| `TimesFmJax.__post_init__` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimesFmJax.load_from_checkpoint` | Loads a checkpoint and compiles the decoder. | `self, checkpoint` | Returns (typically): None |
| `TimesFmJax.jit_decode` | Jitting decoding function. | `self` | Returns context-dependent output or mutates state. |
| `TimesFmJax._forecast` | Forecasts on a list of time series. | `self, inputs, freq, window_size, forecast_context_len, return_forecast_on_context` | Returns (typically): tuple[np.ndarray, np.ndarray] |

## forecasting/timesfm/v1/src/timesfm/timesfm_torch.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** TimesFM pytorch forecast API for inference.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFmTorch` (timesfm_base.TimesFmBase): TimesFM forecast API for inference.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `TimesFmTorch.__post_init__` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TimesFmTorch.load_from_checkpoint` | Loads a checkpoint and compiles the decoder. | `self, checkpoint` | Returns (typically): None |
| `TimesFmTorch._forecast` | Forecasts on a list of time series. | `self, inputs, freq, window_size, forecast_context_len, return_forecast_on_context` | Returns (typically): tuple[np.ndarray, np.ndarray] |

## forecasting/timesfm/v1/src/timesfm/xreg_lib.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Helper functions for in-context covariates and regression.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `BatchedInContextXRegBase` (object): Helper class for in-context regression covariate formatting.
  - `BatchedInContextXRegLinear` (BatchedInContextXRegBase): Linear in-context regression model.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_unnest` | Helper within this module. | `nested` | Returns (typically): np.ndarray |
| `_repeat` | Helper within this module. | `elements, counts` | Returns (typically): np.ndarray |
| `_to_padded_jax_array` | Helper within this module. | `x` | Returns (typically): jax.Array |
| `BatchedInContextXRegBase.__init__` | Initializes with the exogenous covariate inputs. | `self, targets, train_lens, test_lens, train_dynamic_numerical_covariates, train_dynamic_categorical_covariates, test_dynamic_numerical_covariates, test_dynamic_categorical_covariates, static_numerical_covariates, static_categorical_covariates` | Returns (typically): None |
| `BatchedInContextXRegBase._assert_covariates` | Verifies the validity of the covariate inputs. | `self, assert_covariate_shapes` | Returns (typically): None |
| `BatchedInContextXRegBase.create_covariate_matrix` | Creates target vector and covariate matrices for in context regression. | `self, one_hot_encoder_drop, use_intercept, assert_covariates, assert_covariate_shapes` | Returns (typically): tuple[np.ndarray, np.ndarray, np.ndarray] |
| `BatchedInContextXRegBase.fit` | Helper within this module. | `self` | Returns (typically): Any |
| `BatchedInContextXRegLinear.fit` | Fits a linear model for in-context regression. | `self, ridge, one_hot_encoder_drop, use_intercept, force_on_cpu, max_rows_per_col, max_rows_per_col_sample_seed, debug_info, assert_covariates, assert_covariate_shapes` | Returns (typically): list[np.ndarray] | tuple[list[np.ndarray], list[np.ndarray], jax.Array, jax.Array, jax.Array] |

## forecasting/timesfm_service.py
- **Responsibility:** Forecasting pipeline/service code.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Forecasting Logic
- **Important Classes:**
  - `TimesFMServiceError` (Exception): No explicit class-level docstring.
  - `_ModelBundle` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_forecasting_root` | Helper within this module. | `none` | Returns (typically): Path |
| `_ensure_timesfm_import_path` | Helper within this module. | `none` | Returns (typically): None |
| `_resolve_model_source` | Helper within this module. | `none` | Returns (typically): str |
| `_int_env` | Helper within this module. | `name, default` | Returns (typically): int |
| `_read_timesfm_version` | Helper within this module. | `timesfm_module` | Returns (typically): str |
| `_load_timesfm_v2_model` | Loads configuration/data. | `none` | Returns (typically): _ModelBundle | None |
| `_load_timesfm_v1_model` | Loads configuration/data. | `none` | Returns (typically): _ModelBundle | None |
| `get_model` | Fetches data and returns it. | `none` | Returns (typically): Any |
| `_default_horizon` | Helper within this module. | `none` | Returns (typically): int |
| `_forecast_with_timesfm` | Helper within this module. | `series, horizon` | Returns (typically): dict[str, Any] |
| `_forecast_with_prophet` | Helper within this module. | `series, horizon` | Returns (typically): dict[str, Any] |
| `_forecast_with_naive` | Helper within this module. | `series, horizon` | Returns (typically): dict[str, Any] |
| `forecast` | Helper within this module. | `values, horizon` | Returns (typically): dict[str, Any] |
| `TimesFMServiceError.__init__` | Helper within this module. | `self, code, message` | Returns (typically): None |
| `TimesFMServiceError.to_dict` | Helper within this module. | `self` | Returns (typically): dict[str, Any] |

## intent_extraction/__init__.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## intent_extraction/error_handler.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:**
  - `IntentExtractionError` (Exception): Base exception for intent extraction failures.
  - `IntentExtractionInputError` (IntentExtractionError): Input query or schema is invalid.
  - `IntentExtractionSystemError` (IntentExtractionError): Runtime system issue (timeouts, transient dependency errors).
  - `IntentExtractionModelOutputError` (IntentExtractionError): Model returned invalid or malformed output.
  - `IntentExtractionSchemaMismatchError` (IntentExtractionError): Extracted intent does not align with ClickHouse schema.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `classify_intent_extraction_error` | Extracts structured information. | `exception` | Returns (typically): IntentExtractionErrorType |
| `decide_intent_extraction_action` | Extracts structured information. | `none` | Returns (typically): IntentExtractionActionType |

## intent_extraction/intent_extraction_task.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_utc_now` | Helper within this module. | `none` | Returns (typically): str |
| `_schema_column_names` | Helper within this module. | `schema` | Returns (typically): list[str] |
| `_phrase_query_from_hints` | Helper within this module. | `preprocess_hints` | Returns (typically): str | None |
| `_apply_time_semantics_only` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `_apply_time_semantics_and_chart` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `_get_logger` | Fetches data and returns it. | `none` | Returns (typically): logging.Logger |
| `_log_event` | Helper within this module. | `logger, level, message` | Returns (typically): None |
| `_validate_inputs` | Validates input/business constraints. | `query, schema` | Returns (typically): tuple[str, dict[str, list[dict[str, Any]]]] |
| `_coerce_canonical_aggregation` | Helper within this module. | `raw` | Returns (typically): str | None |
| `_coerce_canonical_operator` | Helper within this module. | `raw` | Returns (typically): str |
| `_intent_dict_to_canonical_payload` | Translate the dict-shaped IR into a payload that ``CanonicalIntent`` | `none` | Returns (typically): dict[str, Any] |
| `_validate_canonical_intent` | Validate the dict-shaped intent against ``CanonicalIntent``. | `none` | Returns (typically): tuple[CanonicalIntent | None, str] |
| `_next_step_for_intent_type` | Helper within this module. | `intent_type` | Returns (typically): NextStepType |
| `_apply_chart_intent_fallback` | Helper within this module. | `none` | Returns (typically): tuple[dict[str, Any], str] |
| `_extract_and_validate` | Validates input/business constraints. | `none` | Returns (typically): tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]] |
| `_fallback_extract_and_validate` | Validates input/business constraints. | `none` | Returns (typically): tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]] |
| `_rules_first_extract_and_validate` | Validates input/business constraints. | `none` | Returns (typically): tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]] |
| `run_intent_extraction_stage` | Stage runtime for: | `query, schema, route, preprocess_hints` | Returns (typically): dict[str, Any] |
| `run_intent_extraction` | Full runtime for legacy contract: | `query, schema` | Returns (typically): dict |
| `_attach_fn_compat` | Keep compatibility for existing call sites/tests that use Prefect's `.fn`. | `func` | Returns context-dependent output or mutates state. |
| `intent_extraction_task` | Extracts structured information. | `query, schema` | Returns (typically): dict |

## intent_extraction/llm_extractor.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** LLM-driven structured intent extractor (Phase 5 / CRIT-14).
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_allowed_chart_values` | All canonical chart-type tokens the platform recognises. | `none` | Returns (typically): set[str] |
| `_allowed_chart_prompt_list` | Returns list-like data. | `none` | Returns (typically): str |
| `_schema_to_prompt` | Helper within this module. | `schema` | Returns (typically): str |
| `_build_extraction_prompt` | Builds payload/contract/structured data. | `none` | Returns (typically): str |
| `_extract_json` | Extracts structured information. | `raw_output` | Returns (typically): dict[str, Any] |
| `_normalize_string_list` | Returns list-like data. | `value` | Returns (typically): list[str] |
| `_normalize_filters` | Normalizes values to canonical shape. | `value` | Returns (typically): list[dict[str, Any]] |
| `_normalize_metric_specs` | Normalizes values to canonical shape. | `value` | Returns (typically): list[dict[str, Any]] |
| `_normalize_order_by` | Normalizes values to canonical shape. | `value` | Returns (typically): list[dict[str, str]] |
| `_normalize_limit` | Normalizes values to canonical shape. | `value` | Returns (typically): int | None |
| `_as_metric_specs_from_columns` | Helper within this module. | `metrics, aggregation` | Returns (typically): list[dict[str, Any]] |
| `_is_relationship_query` | Helper within this module. | `query` | Returns (typically): bool |
| `_detect_chart_semantics` | Detect chart semantics using the canonical ``ChartTypeEnum`` taxonomy. | `query, payload` | Returns (typically): tuple[str, str] |
| `_relationship_ready_metrics` | Helper within this module. | `none` | Returns (typically): list[str] |
| `_enrich_with_semantic_ir` | Helper within this module. | `none` | Returns (typically): StructuredIntent |
| `infer_intent_type` | Decide whether a question is analytical or predictive. | `none` | Returns (typically): IntentType |
| `_call_ollama` | Helper within this module. | `none` | Returns (typically): str |
| `_call_openrouter` | Determines the next processing route. | `none` | Returns (typically): str |
| `extract_structured_intent` | Extracts structured information. | `none` | Returns (typically): StructuredIntent | tuple[StructuredIntent, dict[str, Any]] |

## intent_extraction/predictive_parser.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** Deterministic predictive intent parser (Phase 5 / CRIT-14).
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:**
  - `PredictiveSchemaError` (ValueError): Raised when a predictive question cannot be bound to schema columns.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_tokenize` | Helper within this module. | `value` | Returns (typically): set[str] |
| `_parse_date_like` | Parses raw input to structured output. | `value` | Returns (typically): bool |
| `_normalize_phrase` | Normalizes values to canonical shape. | `value` | Returns (typically): str |
| `_semantic_role_for_column` | Helper within this module. | `column` | Returns (typically): str |
| `_resolve_horizon_and_granularity` | Resolve forecast horizon and grain from user phrasing. | `query` | Returns (typically): tuple[int, str] |
| `_best_table` | Helper within this module. | `schema, query` | Returns (typically): str |
| `_is_time_like_column` | Helper within this module. | `column` | Returns (typically): bool |
| `_best_time_column` | Helper within this module. | `columns` | Returns (typically): str |
| `_best_metric_column` | Helper within this module. | `columns, query` | Returns (typically): str |
| `parse_predictive_intent` | Bind a predictive question to a schema-aware forecast spec. | `none` | Returns (typically): dict[str, Any] |
| `PredictiveSchemaError.__init__` | Helper within this module. | `self, code, message` | Returns (typically): None |

## intent_extraction/routing.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_coerce_metrics_to_objects_for_sql_compiler` | ``compile_sql`` requires ``metrics`` as list[dict]; validation may leave string columns. | `intent` | Returns (typically): None |
| `_qualify_with_workspace_db` | Phase 6 / CRIT-05: qualify a bare table name with the workspace DB. | `table_name` | Returns (typically): str |
| `_compile_ch_settings_comment` | Compiles query/contract/prompt. | `none` | Returns (typically): str |
| `_is_string_like_type` | Helper within this module. | `column_type` | Returns (typically): bool |
| `_normalize_clickhouse_date_casts` | Normalizes values to canonical shape. | `sql_expr` | Returns (typically): str |
| `_build_predictive_time_expr` | Builds payload/contract/structured data. | `none` | Returns (typically): str |
| `_string_time_parse_expr` | Parses raw input to structured output. | `column_name` | Returns (typically): str |
| `_build_query_builder_payload` | Loads configuration/data. | `intent` | Returns (typically): dict[str, Any] |
| `_is_schema_mismatch_message` | Helper within this module. | `message` | Returns (typically): bool |
| `build_sql_from_intent` | Builds payload/contract/structured data. | `none` | Returns (typically): tuple[dict[str, Any], str] |
| `_resolve_schema_table` | Helper within this module. | `schema, requested_table` | Returns (typically): str |
| `_resolve_schema_table_for_predictive` | Helper within this module. | `none` | Returns (typically): str |
| `_resolve_schema_column` | Helper within this module. | `none` | Returns (typically): str |
| `_build_historical_forecast_sql` | Builds payload/contract/structured data. | `none` | Returns (typically): tuple[dict[str, Any], str] |
| `route_intent` | Build SQL for a validated intent and wrap it in the routing payload. | `none` | Returns (typically): dict[str, Any] |

## intent_extraction/schemas.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:**
  - `StructuredIntent` (TypedDict): No explicit class-level docstring.
  - `IntentExtractionTaskResult` (TypedDict): No explicit class-level docstring.
  - `IntentExtractionConfig` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_env_int` | Helper within this module. | `name, default` | Returns (typically): int |
| `_env_float` | Helper within this module. | `name, default` | Returns (typically): float |
| `build_intent_extraction_success_result` | Builds payload/contract/structured data. | `none` | Returns (typically): IntentExtractionTaskResult |
| `build_intent_extraction_failed_result` | Builds payload/contract/structured data. | `none` | Returns (typically): IntentExtractionTaskResult |
| `IntentExtractionConfig.from_env` | Helper within this module. | `cls` | Returns (typically): 'IntentExtractionConfig' |

## intent_extraction/validation.py
- **Responsibility:** Intent extraction domain logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_allowed_chart_values` | Phase 5 / CRIT-14: the chart taxonomy is sourced from | `none` | Returns (typically): set[str] |
| `_resolve_table_name` | Helper within this module. | `none` | Returns (typically): str |
| `_dedupe_preserve_order` | Helper within this module. | `items` | Returns (typically): list[str] |
| `_pick_default_metric` | Helper within this module. | `table_columns` | Returns (typically): str |
| `_normalize_limit_value` | Normalizes values to canonical shape. | `value` | Returns (typically): int | None |
| `_derive_operations` | Helper within this module. | `none` | Returns (typically): list[str] |
| `_derive_primary_intent` | Helper within this module. | `operations` | Returns (typically): str |
| `_normalized_metric_type` | Normalizes values to canonical shape. | `intent` | Returns (typically): str |
| `_normalized_chart_contract` | Normalizes values to canonical shape. | `intent, dimensions, metric_type` | Returns (typically): dict[str, Any] |
| `_infer_semantic_flags` | Infers values from context. | `intent, metric_type` | Returns (typically): dict[str, bool] |
| `_supports_hour_column_type` | Helper within this module. | `col_type` | Returns (typically): bool |
| `validate_structured_intent` | Validates input/business constraints. | `none` | Returns (typically): StructuredIntent |

## llm_app/__init__.py
- **Responsibility:** LLM integration app (prompting/parsing/service APIs).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## llm_app/admin.py
- **Responsibility:** Django admin configuration.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## llm_app/apps.py
- **Responsibility:** Django app registration.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:**
  - `LlmAppConfig` (AppConfig): No explicit class-level docstring.
- **Important Functions/Methods:** none

## llm_app/intent_service.py
- **Responsibility:** LLM integration app (prompting/parsing/service APIs).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `extract_intent` | Extracts structured information. | `question` | Returns (typically): dict[str, Any] |

## llm_app/llm_client.py
- **Responsibility:** LLM integration app (prompting/parsing/service APIs).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `get_openrouter_diagnostics` | Fetches data and returns it. | `none` | Returns (typically): dict[str, str | bool] |
| `call_llm` | Helper within this module. | `prompt` | Returns (typically): str |

## llm_app/migrations/__init__.py
- **Responsibility:** Django migration schema file.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## llm_app/models.py
- **Responsibility:** Data model layer.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## llm_app/prompt_builder.py
- **Responsibility:** LLM integration app (prompting/parsing/service APIs).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `build_prompt` | Builds payload/contract/structured data. | `question, schema` | Returns (typically): str |

## llm_app/response_parser.py
- **Responsibility:** LLM integration app (prompting/parsing/service APIs).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_extract_json_blob` | Extracts structured information. | `text` | Returns (typically): str |
| `safe_json_parse` | Parses raw input to structured output. | `text` | Returns (typically): dict |

## llm_app/schema_provider.py
- **Responsibility:** LLM integration app (prompting/parsing/service APIs).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `sanitize_sql_for_http` | Helper within this module. | `sql` | Returns (typically): str |
| `get_query_clickhouse_client` | Fetches data and returns it. | `none` | Returns context-dependent output or mutates state. |
| `_classify_column` | Classifies input into categories. | `column, col_type` | Returns (typically): dict[str, Any] |
| `_fetch_schema_from_clickhouse` | Helper within this module. | `none` | Returns (typically): dict[str, list[dict[str, Any]]] |
| `get_schema` | Fetches data and returns it. | `none` | Returns (typically): dict[str, list[dict[str, Any]]] |
| `get_schema_for_dataset` | Fetches data and returns it. | `none` | Returns (typically): dict[str, list[dict[str, Any]]] |
| `is_question_matching_schema` | Helper within this module. | `question, schema` | Returns (typically): bool |

## llm_app/urls.py
- **Responsibility:** API route mapping.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## llm_app/views.py
- **Responsibility:** API view/controller layer.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** API Views, AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_load_forecasting_symbols` | Loads configuration/data. | `none` | Returns context-dependent output or mutates state. |
| `_canonical_status` | Helper within this module. | `status_value` | Returns (typically): str |
| `_canonical_classification` | Helper within this module. | `classification_payload` | Returns (typically): dict |
| `_canonical_chart_contract` | Helper within this module. | `chart_contract` | Returns (typically): dict |
| `_canonical_sql_review` | Helper within this module. | `review_payload` | Returns (typically): dict |
| `intent_test_view` | Helper within this module. | `request` | Returns context-dependent output or mutates state. |
| `forecast_detect_view` | Helper within this module. | `request` | Returns context-dependent output or mutates state. |
| `forecast_dataset_view` | Helper within this module. | `request` | Returns context-dependent output or mutates state. |

## manage.py
- **Responsibility:** Runtime bootstrap/entry point.
- **Role in System:** Django's command-line utility for administrative tasks.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `main` | Run administrative tasks. | `none` | Returns context-dependent output or mutates state. |

## preprocessing_high/__init__.py
- **Responsibility:** High-level schema-aware preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `__getattr__` | Fetches data and returns it. | `name` | Returns context-dependent output or mutates state. |

## preprocessing_high/diagnostics.py
- **Responsibility:** High-level schema-aware preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_supported_temporal_phrase_terms` | Helper within this module. | `query_text` | Returns (typically): set[str] |
| `_is_analytical_language_term` | Helper within this module. | `term` | Returns (typically): bool |
| `_is_non_schema_language_term` | Helper within this module. | `term` | Returns (typically): bool |
| `_is_non_schema_noise_term` | Helper within this module. | `term` | Returns (typically): bool |
| `_safe_singular_forms` | Helper within this module. | `value` | Returns (typically): list[str] |
| `_safe_plural_forms` | Helper within this module. | `value` | Returns (typically): list[str] |
| `_normalize_phrase` | Normalizes values to canonical shape. | `value` | Returns (typically): str |
| `_schema_tables` | Helper within this module. | `loaded_schema` | Returns (typically): list[str] |
| `_schema_columns_by_table` | Helper within this module. | `loaded_schema` | Returns (typically): dict[str, list[str]] |
| `_column_lookup` | Helper within this module. | `columns_by_table` | Returns (typically): dict[str, list[str]] |
| `_column_token_lookup` | Helper within this module. | `columns_by_table` | Returns (typically): dict[str, list[str]] |
| `_column_alias_lookup` | Helper within this module. | `columns_by_table` | Returns (typically): dict[str, list[tuple[str, str]]] |
| `_extract_explicit_column_matches` | Extracts structured information. | `none` | Returns (typically): list[dict[str, str]] |
| `_extract_residual_terms` | Extracts structured information. | `none` | Returns (typically): list[str] |
| `_extract_literal_filter_terms` | Extracts structured information. | `query_text` | Returns (typically): set[str] |
| `_best_typo_candidate` | Helper within this module. | `none` | Returns (typically): tuple[str, float, bool] |
| `_has_any_datetime_columns` | Helper within this module. | `loaded_schema` | Returns (typically): bool |
| `_mapping_resolution_map` | Helper within this module. | `mappings` | Returns (typically): dict[str, dict[str, Any]] |
| `_selected_table_for_matches` | Helper within this module. | `none` | Returns (typically): tuple[str, list[str], list[str], dict[str, int]] |
| `build_schema_resolution_diagnostics` | Builds payload/contract/structured data. | `none` | Returns (typically): dict[str, Any] |

## preprocessing_high/error_handler.py
- **Responsibility:** High-level schema-aware preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `PreprocessHighError` (Exception): Base exception for high-level preprocessing failures.
  - `PreprocessHighInputError` (PreprocessHighError): Invalid high-level preprocessing input.
  - `PreprocessHighSystemError` (PreprocessHighError): Transient system/runtime failure.
  - `PreprocessHighSchemaLoadError` (PreprocessHighError): Schema loading failure from ClickHouse.
  - `PreprocessHighLLMError` (PreprocessHighError): LLM returned invalid or unusable content.
  - `PreprocessHighMissingColumnError` (PreprocessHighError): Business rejection when a referenced column cannot be resolved.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `classify_preprocess_high_error` | Classifies input into categories. | `exception` | Returns (typically): HighPreprocessErrorType |
| `decide_preprocess_high_action` | Runs a major processing step. | `none` | Returns (typically): HighPreprocessActionType |
| `PreprocessHighMissingColumnError.__init__` | Helper within this module. | `self, missing_column, message` | Returns (typically): None |

## preprocessing_high/llm_client.py
- **Responsibility:** High-level schema-aware preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_schema_for_prompt` | Helper within this module. | `loaded_schema` | Returns (typically): str |
| `_extract_ollama_error_message` | Extracts structured information. | `response` | Returns (typically): str |
| `_call_ollama` | Helper within this module. | `none` | Returns (typically): str |
| `_build_correction_prompt` | Builds payload/contract/structured data. | `none` | Returns (typically): str |
| `_normalize_correction_output` | Normalizes values to canonical shape. | `raw_output` | Returns (typically): str |
| `_extract_query_shape` | Extracts structured information. | `query` | Returns (typically): dict[str, Any] |
| `_is_correction_structure_safe` | Helper within this module. | `original_query, corrected_query` | Returns (typically): bool |
| `correct_query_terms` | Helper within this module. | `none` | Returns (typically): str |
| `_extract_json_object` | Extracts structured information. | `raw_output` | Returns (typically): dict |
| `_build_validation_prompt` | Builds payload/contract/structured data. | `none` | Returns (typically): str |
| `_is_derivable_request` | Helper within this module. | `term` | Returns (typically): bool |
| `_build_mapping` | Builds payload/contract/structured data. | `none` | Returns (typically): ValidationMapping |
| `_resolve_reference` | Helper within this module. | `none` | Returns (typically): tuple[bool, ValidationMapping, str] |
| `_find_direct_schema_mentions` | Helper within this module. | `none` | Returns (typically): list[ValidationMapping] |
| `_token_forms` | Helper within this module. | `token` | Returns (typically): set[str] |
| `_expanded_token_forms` | Helper within this module. | `token` | Returns (typically): set[str] |
| `_find_semantic_schema_mentions` | Helper within this module. | `none` | Returns (typically): list[ValidationMapping] |
| `_infer_preferred_table_from_query` | Infers values from context. | `none` | Returns (typically): str | None |
| `build_deterministic_schema_validation_result` | Builds payload/contract/structured data. | `none` | Returns (typically): SchemaValidationResult |
| `validate_query_schema_usage` | Validates input/business constraints. | `none` | Returns (typically): SchemaValidationResult |

## preprocessing_high/preprocess_high_task.py
- **Responsibility:** High-level schema-aware preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_resolve_forecast_columns` | Resolve the forecast date/target columns from the loaded schema. | `none` | Returns (typically): tuple[str, str, str] |
| `_utc_now` | Helper within this module. | `none` | Returns (typically): str |
| `_get_logger` | Fetches data and returns it. | `none` | Returns (typically): logging.Logger |
| `_log_event` | Helper within this module. | `logger, level, message` | Returns (typically): None |
| `_validate_inputs` | Validates input/business constraints. | `cleaned_text, user_id` | Returns (typically): tuple[str, str] |
| `_extract_skipped_forecast_terms` | Extracts structured information. | `query` | Returns (typically): list[str] |
| `_recommended_columns_text` | Helper within this module. | `schema` | Returns (typically): str |
| `_attach_intent_query_metadata` | Helper within this module. | `payload` | Returns (typically): None |
| `_schema_token_vocabulary` | Helper within this module. | `loaded_schema` | Returns (typically): set[str] |
| `_schema_column_phrase_lookup` | Helper within this module. | `loaded_schema` | Returns (typically): dict[str, str] |
| `_best_fuzzy_candidate` | Helper within this module. | `term, candidates` | Returns (typically): tuple[str, float] |
| `_apply_fuzzy_phrase_corrections` | Helper within this module. | `none` | Returns (typically): tuple[str, list[dict[str, str]]] |
| `_apply_fuzzy_token_corrections` | Helper within this module. | `none` | Returns (typically): tuple[str, list[dict[str, str]]] |
| `_apply_business_term_normalization` | Helper within this module. | `query` | Returns (typically): tuple[str, list[dict[str, str]]] |
| `_resolved_term_aliases` | Helper within this module. | `corrections` | Returns (typically): set[str] |
| `_filter_resolved_diagnostics` | Helper within this module. | `diagnostics, corrections, validation_result` | Returns (typically): dict[str, object] |
| `_should_skip_llm_schema_validation` | Helper within this module. | `none` | Returns (typically): bool |
| `run_preprocess_high` | Shared runtime function so this module can be reused by Dagster assets and direct callers. | `cleaned_text, user_id, route, dataset_scope` | Returns (typically): PreprocessHighResult |
| `_attach_fn_compat` | Keep compatibility for existing call sites/tests that use Prefect's `.fn`. | `func` | Returns context-dependent output or mutates state. |
| `preprocess_high_task` | Runs a major processing step. | `cleaned_text, user_id, route, dataset_scope` | Returns (typically): dict |

## preprocessing_high/schema_loader.py
- **Responsibility:** High-level schema-aware preprocessing logic.
- **Role in System:** Schema loader (Phase 13 / GAP-01).
- **Important Classes:**
  - `ColumnReference` (object): No explicit class-level docstring.
  - `LoadedUserSchema` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `schema_fingerprint` | Return a deterministic SHA-256 prefix of the schema content. | `schema` | Returns (typically): str |
| `invalidate_schema_cache` | Invalidate every cached schema for a user (and optional database). | `none` | Returns (typically): int |
| `invalidate_all_schema_caches` | Drop every cached schema. Returns the number of entries dropped. | `none` | Returns (typically): int |
| `_sanitize_user_id` | Helper within this module. | `user_id` | Returns (typically): str |
| `_ensure_safe_identifier` | Helper within this module. | `identifier` | Returns (typically): str |
| `_resolve_database_name` | Helper within this module. | `user_id, config` | Returns (typically): str |
| `_cache_key` | Helper within this module. | `user_id, database` | Returns (typically): str |
| `_build_clickhouse_client` | Builds payload/contract/structured data. | `config` | Returns context-dependent output or mutates state. |
| `_fetch_user_schema_rows` | Helper within this module. | `none` | Returns (typically): list[tuple[str, str, str]] |
| `_build_loaded_schema` | Loads configuration/data. | `none` | Returns (typically): LoadedUserSchema |
| `load_user_schema` | Loads configuration/data. | `none` | Returns (typically): LoadedUserSchema |
| `find_column_matches` | Helper within this module. | `none` | Returns (typically): list[ColumnReference] |
| `get_fallback_derivable_column` | Fetches data and returns it. | `loaded_schema` | Returns (typically): ColumnReference | None |
| `LoadedUserSchema.total_columns` | Helper within this module. | `self` | Returns (typically): int |

## preprocessing_high/schemas.py
- **Responsibility:** High-level schema-aware preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `SchemaColumn` (TypedDict): No explicit class-level docstring.
  - `UserSchema` (TypedDict): No explicit class-level docstring.
  - `ValidationMapping` (TypedDict): No explicit class-level docstring.
  - `SchemaValidationResult` (TypedDict): No explicit class-level docstring.
  - `PreprocessHighResult` (TypedDict): No explicit class-level docstring.
  - `HighPreprocessConfig` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_env_int` | Helper within this module. | `name, default` | Returns (typically): int |
| `_env_float` | Helper within this module. | `name, default` | Returns (typically): float |
| `_env_bool` | Helper within this module. | `name, default` | Returns (typically): bool |
| `build_preprocess_high_success_result` | Builds payload/contract/structured data. | `final_query` | Returns (typically): PreprocessHighResult |
| `build_preprocess_high_failed_result` | Builds payload/contract/structured data. | `none` | Returns (typically): PreprocessHighResult |
| `build_preprocess_high_rejected_result` | Builds payload/contract/structured data. | `none` | Returns (typically): PreprocessHighResult |
| `HighPreprocessConfig.from_env` | Helper within this module. | `cls` | Returns (typically): 'HighPreprocessConfig' |

## preprocessing_low/__init__.py
- **Responsibility:** Low-level text preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
- **Important Functions/Methods:** none

## preprocessing_low/cleaners.py
- **Responsibility:** Low-level text preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_collect_matches` | Helper within this module. | `pattern, text` | Returns (typically): list[str] |
| `_append_change` | Helper within this module. | `changes` | Returns (typically): None |
| `_reduce_repeated_characters` | Helper within this module. | `text, max_repeats` | Returns (typically): str |
| `_normalize_casing` | Normalizes values to canonical shape. | `text` | Returns (typically): str |
| `_singular_variants` | Helper within this module. | `token` | Returns (typically): set[str] |
| `_is_boundary_known_piece` | Helper within this module. | `token` | Returns (typically): bool |
| `_segment_alpha_token` | Helper within this module. | `token` | Returns (typically): list[str] |
| `_repair_token_boundaries` | Helper within this module. | `text` | Returns (typically): tuple[str, list[dict[str, str]]] |
| `_conservative_spelling_correction` | Helper within this module. | `text` | Returns (typically): tuple[str, list[dict[str, str]]] |
| `_is_numeric_only_input` | Helper within this module. | `text` | Returns (typically): bool |
| `_is_noise_like_input` | Helper within this module. | `text` | Returns (typically): bool |
| `_rule_based_clean_with_changes` | Helper within this module. | `text` | Returns (typically): tuple[str, list[dict[str, str]], dict[str, bool]] |
| `_rule_based_clean_text` | Helper within this module. | `text` | Returns (typically): str |

## preprocessing_low/error_handler.py
- **Responsibility:** Low-level text preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `PreprocessError` (Exception): Base exception for text preprocessing failures.
  - `PreprocessInputError` (PreprocessError): Invalid text input for preprocessing.
  - `PreprocessModelOutputError` (PreprocessError): Invalid or meaningless model output.
  - `PreprocessInfrastructureError` (PreprocessError): Unavailable Ollama runtime or networking dependency.
  - `PreprocessTimeoutError` (PreprocessError): Ollama inference timed out.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `classify_preprocess_error` | Classifies input into categories. | `exception` | Returns (typically): PreprocessErrorType |
| `_decide_preprocess_action` | Runs a major processing step. | `error_type, retry_count, config` | Returns (typically): PreprocessActionType |

## preprocessing_low/llm_client.py
- **Responsibility:** Low-level text preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_build_preprocess_prompt` | Builds payload/contract/structured data. | `raw_text` | Returns (typically): str |
| `_is_meaningful_cleaned_output` | Helper within this module. | `text` | Returns (typically): bool |
| `_extract_ollama_error_message` | Extracts structured information. | `response` | Returns (typically): str |
| `_call_ollama_prompt` | Helper within this module. | `prompt, config, logger, log_event` | Returns (typically): str |
| `_call_ollama_preprocessor` | Runs a major processing step. | `text, config, logger, log_event` | Returns (typically): str |

## preprocessing_low/preprocess_task.py
- **Responsibility:** Low-level text preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `detect_language_simple` | Return a coarse-grained language tag for ``text``. | `text` | Returns (typically): str |
| `_utc_now` | Helper within this module. | `none` | Returns (typically): str |
| `_get_logger` | Fetches data and returns it. | `none` | Returns (typically): logging.Logger |
| `_log_event` | Helper within this module. | `logger, level, message` | Returns (typically): None |
| `_attach_spelling_trace_fields` | Helper within this module. | `payload` | Returns (typically): None |
| `_extract_removed_filler_words` | Extracts structured information. | `detected_changes` | Returns (typically): list[str] |
| `_change_type_labels` | Helper within this module. | `detected_changes` | Returns (typically): list[str] |
| `_token_set` | Helper within this module. | `text` | Returns (typically): set[str] |
| `_has_protected_loss` | Helper within this module. | `before, after` | Returns (typically): bool |
| `_snake_case_tokens` | Helper within this module. | `text` | Returns (typically): list[str] |
| `_snake_case_changed` | Helper within this module. | `before, after` | Returns (typically): bool |
| `run_preprocess_text` | Runtime entrypoint for language-agnostic text preprocessing. | `text` | Returns (typically): dict |
| `_attach_fn_compat` | Keep compatibility for existing call sites/tests that use Prefect's `.fn`. | `func` | Returns context-dependent output or mutates state. |
| `preprocess_text_task` | Runs a major processing step. | `text` | Returns (typically): dict |

## preprocessing_low/schemas.py
- **Responsibility:** Low-level text preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `PreprocessResult` (TypedDict): No explicit class-level docstring.
  - `TextPreprocessConfig` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_env_float` | Helper within this module. | `name, default` | Returns (typically): float |
| `_default_preprocess_ollama_timeout` | Runs a major processing step. | `none` | Returns (typically): float |
| `build_preprocess_success_result` | Builds payload/contract/structured data. | `cleaned_text` | Returns (typically): PreprocessResult |
| `build_preprocess_failed_result` | Builds payload/contract/structured data. | `error_type, action_taken` | Returns (typically): PreprocessResult |
| `TextPreprocessConfig.from_env` | Helper within this module. | `cls` | Returns (typically): 'TextPreprocessConfig' |

## preprocessing_low/spell_corrector.py
- **Responsibility:** Low-level text preprocessing logic.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `SpellingCorrectionResult` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_normalize_whitespace` | Normalizes values to canonical shape. | `text` | Returns (typically): str |
| `_word_tokens` | Helper within this module. | `text` | Returns (typically): list[str] |
| `_is_protected_token` | Helper within this module. | `token` | Returns (typically): bool |
| `_has_protected_token_changes` | Helper within this module. | `original, corrected` | Returns (typically): bool |
| `_build_spelling_prompt` | Builds payload/contract/structured data. | `text` | Returns (typically): str |
| `correct_spelling_llm` | Helper within this module. | `text, llm_client` | Returns (typically): str |
| `detect_spelling_changes` | Helper within this module. | `original, corrected` | Returns (typically): list[dict[str, str]] |
| `_tokenize_words_preserve_case` | Helper within this module. | `text` | Returns (typically): list[str] |
| `_token_set_lower` | Helper within this module. | `text` | Returns (typically): set[str] |
| `_has_protected_keyword_removal` | Helper within this module. | `original, corrected` | Returns (typically): bool |
| `_snake_case_tokens` | Helper within this module. | `text` | Returns (typically): list[str] |
| `_snake_case_changed` | Helper within this module. | `original, corrected` | Returns (typically): bool |
| `_token_change_ratio` | Helper within this module. | `original, corrected` | Returns (typically): float |
| `_has_unrelated_additions` | Helper within this module. | `original, corrected, changes` | Returns (typically): bool |
| `_is_high_confidence_typo_changes` | Helper within this module. | `changes` | Returns (typically): bool |
| `apply_spelling_correction` | Helper within this module. | `text, llm_client` | Returns (typically): SpellingCorrectionResult |

## reasoning_app/__init__.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## reasoning_app/admin.py
- **Responsibility:** Django admin configuration.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## reasoning_app/apps.py
- **Responsibility:** Django app registration.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:**
  - `ReasoningAppConfig` (AppConfig): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `ReasoningAppConfig.ready` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |

## reasoning_app/debug_openrouter.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `debug_openrouter_env` | Determines the next processing route. | `none` | Returns (typically): None |

## reasoning_app/graph.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `build_graph` | Builds payload/contract/structured data. | `none` | Returns context-dependent output or mutates state. |

## reasoning_app/intent_classification_task.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Intent classification task (Phase 4 / CRIT-06).
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:**
  - `IntentClassificationResult` (TypedDict): No explicit class-level docstring.
  - `IntentClassificationError` (Exception): Base exception for intent classification task failures.
  - `IntentInputError` (IntentClassificationError): Input text cannot be classified.
  - `IntentLogicError` (IntentClassificationError): Unexpected return shape from existing classifier wrapper.
  - `IntentModelOutputError` (IntentClassificationError): Classifier output values are malformed.
  - `IntentTaskConfig` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_utc_now` | Helper within this module. | `none` | Returns (typically): str |
| `_get_logger` | Fetches data and returns it. | `none` | Returns (typically): logging.Logger |
| `_log_event` | Helper within this module. | `logger, level, message` | Returns (typically): None |
| `classify_intent_task_error` | Classifies input into categories. | `exception` | Returns (typically): IntentErrorType |
| `_decide_intent_action` | Helper within this module. | `error_type, retry_count, config` | Returns (typically): IntentActionType |
| `_validate_cleaned_text` | Validates input/business constraints. | `cleaned_text` | Returns (typically): None |
| `_normalize_intent_text` | Normalizes values to canonical shape. | `text` | Returns (typically): str |
| `_contains_phrase` | Helper within this module. | `text, phrase` | Returns (typically): bool |
| `_detect_rule_based_analytical` | Helper within this module. | `text` | Returns (typically): dict[str, Any] |
| `_detect_rule_based_predictive` | Phase 4 / CRIT-06: delegate to the canonical shared detector. | `text` | Returns (typically): dict[str, Any] |
| `_enforce_predictive_consistency` | Helper within this module. | `payload` | Returns (typically): dict[str, Any] |
| `_is_strong_conversational_signal` | Helper within this module. | `text` | Returns (typically): bool |
| `_extract_classifier_label` | Extracts structured information. | `classifier_output` | Returns (typically): tuple[str, bool] |
| `_log_intent_detection_summary` | Helper within this module. | `none` | Returns (typically): None |
| `run_intent_classification` | Always-on LLM intent classification with fail-safe fallback. | `cleaned_text, raw_text` | Returns (typically): dict |
| `_attach_fn_compat` | Keep compatibility for existing call sites/tests that use Prefect's `.fn`. | `func` | Returns context-dependent output or mutates state. |
| `intent_classification_task` | Helper within this module. | `cleaned_text` | Returns (typically): dict |
| `route_intent_classification` | Decision-based routing after intent classification. | `cleaned_text, classification_result, user_id` | Returns (typically): dict[str, Any] |
| `IntentTaskConfig.from_env` | Helper within this module. | `cls` | Returns (typically): 'IntentTaskConfig' |

## reasoning_app/llm_intent_client.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** LLM-backed intent classifier (Phase 4 / CRIT-06).
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_normalize_text` | Normalizes values to canonical shape. | `value` | Returns (typically): str |
| `_get_ollama_url` | Fetches data and returns it. | `none` | Returns (typically): str |
| `_get_ollama_model` | Resolve the classification model. | `none` | Returns (typically): str |
| `_get_timeout_seconds` | Fetches data and returns it. | `none` | Returns (typically): int |
| `_get_min_confidence` | Fetches data and returns it. | `none` | Returns (typically): float |
| `_classification_for_label` | Helper within this module. | `label` | Returns (typically): str |
| `_build_decision_payload` | Loads configuration/data. | `none` | Returns (typically): Dict[str, Any] |
| `_matches_non_data` | Helper within this module. | `question` | Returns (typically): bool |
| `_matches_analytical_signal` | Helper within this module. | `question` | Returns (typically): bool |
| `_deterministic_pre_check` | Return a decision payload when the question can be classified without | `question` | Returns (typically): Optional[Dict[str, Any]] |
| `_build_prompt` | Builds payload/contract/structured data. | `question` | Returns (typically): str |
| `_strip_markdown_json_fence` | Helper within this module. | `text` | Returns (typically): str |
| `_parse_llm_payload` | Loads configuration/data. | `raw_output` | Returns (typically): Dict[str, Any] |
| `_call_ollama_classifier` | Helper within this module. | `none` | Returns (typically): str |
| `classify_question` | Classify a BI question. | `question` | Returns (typically): Dict[str, Any] |

## reasoning_app/migrations/__init__.py
- **Responsibility:** Django migration schema file.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## reasoning_app/nodes/__init__.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## reasoning_app/nodes/intent_llm_node.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `intent_llm_node` | Helper within this module. | `state` | Returns (typically): QueryState |

## reasoning_app/nodes/routing_node.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `routing_node` | Decide graph routing based on intent classification | `state` | Returns (typically): str |

## reasoning_app/runner.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `run_reasoning` | Executes a full runnable flow. | `text` | Returns (typically): QueryState |

## reasoning_app/states.py
- **Responsibility:** Reasoning/classification app and graph execution.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:**
  - `QueryState` (TypedDict): No explicit class-level docstring.
- **Important Functions/Methods:** none

## reasoning_app/urls.py
- **Responsibility:** API route mapping.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** AI Pipeline Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## reasoning_app/views.py
- **Responsibility:** API view/controller layer.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** API Views, AI Pipeline Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `reasoning_test_view` | Test endpoint for reasoning layer | `request` | Returns context-dependent output or mutates state. |

## shared/__init__.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## shared/analytical_time_semantics.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Deterministic analytical time semantics (phrase detection + intent repair).
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `question_requests_analytical_time` | Helper within this module. | `question` | Returns (typically): bool |
| `infer_time_grain_from_question` | Infers values from context. | `question` | Returns (typically): str |
| `_schema_has_ds` | Helper within this module. | `schema` | Returns (typically): bool |
| `_numeric_columns` | Helper within this module. | `schema` | Returns (typically): set[str] |
| `apply_deterministic_analytical_time_repair` | Force time-series IR when the question contains analytical time phrases. | `none` | Returns (typically): dict[str, Any] |

## shared/bi_llm_core_policy.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Core BI LLM policy injected into intent extraction and classification prompts.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
- **Important Functions/Methods:** none

## shared/chart_contract.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic, Chart Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_list_of_strings` | Returns list-like data. | `value` | Returns (typically): List[str] |
| `_first_non_blank` | Helper within this module. | `none` | Returns (typically): str |
| `_explicit_chart_from_text` | Helper within this module. | `query_text` | Returns (typically): str |
| `_metric_aliases` | Helper within this module. | `intent_payload` | Returns (typically): list[str] |
| `_prefer_value_metric` | Helper within this module. | `metric_aliases, metric_type` | Returns (typically): str | None |
| `_dedupe_non_blank` | Helper within this module. | `values` | Returns (typically): list[str] |
| `build_chart_contract_from_intent` | Builds payload/contract/structured data. | `intent, schema, result_shape, user_text, visualization, final_route` | Returns (typically): Dict[str, Any] |
| `validate_chart_sql_alignment` | Fail-fast checks: time-based charts require GROUP BY in SQL. | `none` | Returns (typically): list[str] |

## shared/chart_recommender.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic, Chart Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_is_numeric_like` | Helper within this module. | `value` | Returns (typically): bool |
| `_extract_rows_and_columns` | Extracts structured information. | `dataframe` | Returns (typically): tuple[list[dict[str, Any]], list[Any]] |
| `_column_name` | Helper within this module. | `column` | Returns (typically): str |
| `_column_type` | Helper within this module. | `column` | Returns (typically): str |
| `_type_is_numeric` | Helper within this module. | `column_type` | Returns (typically): bool |
| `_column_profiles` | Helper within this module. | `rows, columns, metadata` | Returns (typically): dict[str, Any] |
| `_intent_text` | Helper within this module. | `intent, metadata` | Returns (typically): str |
| `_metric_alias` | Helper within this module. | `metric` | Returns (typically): str |
| `_has_combo_intent` | Helper within this module. | `text` | Returns (typically): bool |
| `_result` | Helper within this module. | `chart_type, confidence, reasoning` | Returns (typically): dict[str, Any] |
| `recommend_chart` | Structured chart recommendation engine. | `dataframe, intent, metadata, data` | Returns (typically): dict[str, Any] |

## shared/chart_types.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Canonical chart taxonomy for ai-service.
- **Architectural Goal:** Shared Core Logic, Chart Logic
- **Important Classes:**
  - `ChartType` (str, Enum): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `normalize_chart_type` | Normalizes values to canonical shape. | `raw_chart_type` | Returns (typically): str |
| `validate_chart_type` | Validates input/business constraints. | `raw_chart_type` | Returns (typically): str |
| `to_metabase_display` | Helper within this module. | `chart_type` | Returns (typically): str |

## shared/confidence.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `clamp_confidence` | Helper within this module. | `value, default` | Returns (typically): float |
| `stage_confidence` | Helper within this module. | `payload` | Returns (typically): float |
| `preprocessing_low_confidence` | Runs a major processing step. | `payload` | Returns (typically): float |
| `schema_confidence` | Helper within this module. | `payload` | Returns (typically): float |
| `forecasting_confidence` | Helper within this module. | `payload` | Returns (typically): float |
| `pipeline_confidence` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |

## shared/dataset_binding.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:**
  - `DatasetBindingError` (ValueError): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `normalize_identifier` | Strip whitespace and common SQL/ClickHouse quoting from identifiers. | `value` | Returns (typically): str |
| `normalize_dataset_context` | Normalizes values to canonical shape. | `payload` | Returns (typically): dict[str, str] |
| `validate_dataset_context` | Validates input/business constraints. | `context` | Returns (typically): dict[str, str] |
| `has_complete_dataset_context` | Helper within this module. | `context` | Returns (typically): bool |

## shared/deterministic_chart_selector.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Deterministic chart selection (intent stage only; not overridden downstream).
- **Architectural Goal:** Shared Core Logic, Chart Logic
- **Important Classes:**
  - `ChartSelection` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_lower` | Helper within this module. | `q` | Returns (typically): str |
| `_explicit_chart_from_query` | Helper within this module. | `query_text` | Returns (typically): str |
| `_list_metric_entries` | Returns list-like data. | `intent` | Returns (typically): list[Any] |
| `_metric_count` | Helper within this module. | `intent` | Returns (typically): int |
| `_dimensions` | Helper within this module. | `intent` | Returns (typically): list[str] |
| `_time_like_dimension` | Helper within this module. | `name, time_column` | Returns (typically): bool |
| `_categorical_dimension_count` | Helper within this module. | `intent` | Returns (typically): int |
| `_is_time_series` | Helper within this module. | `intent, query_lower` | Returns (typically): bool |
| `_raw_table_requested` | Helper within this module. | `query_lower, intent` | Returns (typically): bool |
| `_geo_requested` | Helper within this module. | `query_lower, intent` | Returns (typically): bool |
| `_percentage_semantics` | Helper within this module. | `query_lower, intent` | Returns (typically): bool |
| `_trend_semantics` | Helper within this module. | `query_lower` | Returns (typically): bool |
| `_distribution_semantics` | Helper within this module. | `query_lower, intent` | Returns (typically): bool |
| `_stacked_semantics` | Helper within this module. | `query_lower` | Returns (typically): bool |
| `_combo_semantics` | Helper within this module. | `query_lower` | Returns (typically): bool |
| `_relationship_semantics` | Helper within this module. | `query_lower, intent, is_ts` | Returns (typically): bool |
| `_has_grouping` | Helper within this module. | `intent` | Returns (typically): bool |
| `select_chart_from_intent` | Rule-based chart selection; sole authority for default chart_type at intent stage. | `intent` | Returns (typically): ChartSelection |
| `select_chart_deterministic` | Backward-compatible entry: synthesize minimal intent for tests. | `is_time_series, number_of_metrics, has_categorical_dimension, has_grouping` | Returns (typically): ChartSelection |
| `extract_chart_selection_inputs` | Extracts structured information. | `intent, user_query` | Returns (typically): dict[str, Any] |
| `apply_chart_selection` | Helper within this module. | `intent` | Returns (typically): dict[str, Any] |
| `enforce_chart_lock` | Helper within this module. | `intent_chart_type, chart_lock, downstream_chart_type` | Returns (typically): str |
| `ChartSelection.to_dict` | Helper within this module. | `self` | Returns (typically): dict[str, Any] |

## shared/error_response.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `make_error` | Helper within this module. | `code, message` | Returns (typically): dict[str, Any] |

## shared/input_classifier.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Input classifier (Phase 4 / CRIT-06).
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_normalize_text` | Normalizes values to canonical shape. | `value` | Returns (typically): str |
| `_contains_hint` | Helper within this module. | `text, hint` | Returns (typically): bool |
| `_is_punctuation_only` | Helper within this module. | `text` | Returns (typically): bool |
| `_is_empty_or_silence` | Helper within this module. | `text` | Returns (typically): bool |
| `_is_numeric_only` | Helper within this module. | `text` | Returns (typically): bool |
| `_is_noise_like` | Helper within this module. | `text` | Returns (typically): bool |
| `classify_input` | Classifies input into categories. | `none` | Returns (typically): dict[str, Any] |

## shared/intent_normalizer.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `normalize_intent` | Normalizes values to canonical shape. | `intent, schema` | Returns (typically): dict |

## shared/intent_sanitizer.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_detect_aggregation_type` | Detect aggregation type from question text. | `question_lower` | Returns (typically): str | None |
| `_is_numeric_type` | Check if a column type is numeric based on ClickHouse type names. | `col_type` | Returns (typically): bool |
| `_is_string_type` | Check if a column type is a string type. | `col_type` | Returns (typically): bool |
| `_extract_metric_intent_sanitizer` | 🔴 Extract metric-specific semantic intent from question (sanitizer version). | `question_lower` | Returns (typically): list[str] |
| `_calculate_intra_domain_score` | 🔴 Calculate intra-domain semantic score for metric resolution. | `col, metric_intents, question_tokens` | Returns (typically): int |
| `_infer_metric_from_question` | Infer a metric from the question when sanitization removed all metrics. | `question, numeric_columns, categorical_columns, schema_columns` | Returns (typically): dict | None |
| `_identify_question_domain` | Identify the domain/topic of the question for semantic matching. | `question_lower` | Returns (typically): str | None |
| `_identify_column_domain` | Identify the domain of a column based on its name. | `col_lower` | Returns (typically): str | None |
| `resolve_entity_dimension` | Resolve linguistic entities (e.g. customer, product, user) | `question, schema, table` | Returns context-dependent output or mutates state. |
| `sanitize_intent` | Dataset-agnostic and question-agnostic intent sanitizer. | `intent, schema, question` | Returns (typically): dict |

## shared/intent_schema.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:**
  - `Metric` (BaseModel): No explicit class-level docstring.
  - `Filter` (BaseModel): No explicit class-level docstring.
  - `Intent` (BaseModel): No explicit class-level docstring.
- **Important Functions/Methods:** none

## shared/intent_validator.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Multi-Pass Intent & SQL Validation System
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_identify_question_domain` | Identify the domain/topic of the question for semantic matching. | `question_lower` | Returns (typically): str | None |
| `_identify_column_domain` | Identify the domain of a column based on its name. | `col_lower` | Returns (typically): str | None |
| `_extract_metric_intent` | 🔴 STEP 2: Extract metric-specific semantic intent from question. | `question_lower` | Returns (typically): list[str] |
| `_calculate_semantic_score` | 🔴 STEP 4: Calculate semantic relevance score for intra-domain metric matching. | `column_name, metric_intents, question_tokens` | Returns (typically): int |
| `validate_intent_semantics` | Pass 1: Domain & Intent Validation with Intra-Domain Semantic Resolution | `intent, question, schema` | Returns (typically): dict |
| `validate_schema_and_types` | Pass 2: Schema & Type Validation with Type Repair | `intent, schema` | Returns (typically): dict |
| `validate_sql_executability` | Pass 3: SQL Executability Validation | `sql, intent, schema` | Returns (typically): dict |
| `_is_string_type` | Check if column type is a string type. | `col_type` | Returns (typically): bool |
| `_is_numeric_type` | Check if column type is numeric. | `col_type` | Returns (typically): bool |
| `_infer_target_cast` | Infer appropriate ClickHouse cast function based on column type and name. | `col_type, col_name` | Returns (typically): str |
| `perform_multi_pass_validation` | Perform all three validation passes and return comprehensive results. | `intent, sql, question, schema` | Returns (typically): dict |

## shared/internal_api_auth.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Internal API key authentication for ai-service endpoints.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_auth_required` | Helper within this module. | `none` | Returns (typically): bool |
| `_accepted_secrets` | Return the list of currently-accepted internal API keys. | `none` | Returns (typically): List[str] |
| `_matches_any` | Helper within this module. | `provided, accepted` | Returns (typically): bool |
| `require_internal_api_key` | Helper within this module. | `view_func` | Returns (typically): Callable[..., Any] |

## shared/llm_chart_selector.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic, Chart Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_to_bool` | Helper within this module. | `value` | Returns (typically): bool |
| `_extract_json_block` | Extracts structured information. | `raw_text` | Returns (typically): dict[str, Any] |
| `_schema_columns` | Helper within this module. | `columns` | Returns (typically): list[dict[str, str]] |
| `_prompt` | Helper within this module. | `none` | Returns (typically): str |
| `_deterministic_fallback` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `recommend_chart_with_gemma` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |

## shared/ollama_env.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Shared Ollama timeout defaults (OLLAMA_TIMEOUT_SECONDS).
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `global_ollama_read_timeout_seconds` | Default read timeout for Ollama HTTP calls when a feature-specific env var is unset. | `none` | Returns (typically): float |
| `ollama_retry_backoff_seconds` | Pause between preprocessing_low Ollama retries (timeouts / transient failures). | `none` | Returns (typically): float |

## shared/pipeline_guards.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `is_technical_column_name` | Helper within this module. | `column_name` | Returns (typically): bool |
| `time_column_validator` | Helper within this module. | `none` | Returns (typically): tuple[bool, str] |
| `forecasting_validator` | Validate forecasting input. | `none` | Returns (typically): tuple[bool, str] |
| `dataset_scope_guard` | Helper within this module. | `none` | Returns (typically): tuple[dict[str, list[dict[str, Any]]], dict[str, Any]] |

## shared/pipeline_trace.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Pipeline trace builder (Phase 10).
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `utc_now_iso` | Helper within this module. | `none` | Returns (typically): str |
| `_duration_ms` | Helper within this module. | `started_at, finished_at` | Returns (typically): int | None |
| `_empty_attempt_template` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `make_attempt` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `create_stage_section` | Creates a new object/resource. | `name` | Returns (typically): dict[str, Any] |
| `set_stage_from_values` | Helper within this module. | `section` | Returns (typically): dict[str, Any] |
| `build_pipeline_trace_template` | Builds payload/contract/structured data. | `request_metadata` | Returns (typically): dict[str, Any] |
| `attach_schema_provenance` | Persist schema-provenance metadata onto the trace (audit §12.5). | `trace` | Returns (typically): None |
| `parse_trace_version` | Parse ``trace_version`` into a comparable tuple. | `trace` | Returns (typically): tuple[int, int] |
| `select_trace_for_persistence` | Pick the trace that should be persisted. | `none` | Returns (typically): dict[str, Any] | None |
| `attach_stage` | Helper within this module. | `trace, section_name, stage_payload` | Returns (typically): None |
| `finalize_trace` | Helper within this module. | `trace` | Returns (typically): dict[str, Any] |
| `stage_payload` | Loads configuration/data. | `none` | Returns (typically): dict[str, Any] |

## shared/preprocessing_transparency.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_default_preprocessing_low` | Runs a major processing step. | `text` | Returns (typically): dict[str, Any] |
| `_default_preprocessing_high` | Runs a major processing step. | `corrected_query` | Returns (typically): dict[str, Any] |
| `_tokenize` | Helper within this module. | `text` | Returns (typically): list[str] |
| `_join_tokens` | Helper within this module. | `tokens` | Returns (typically): str |
| `_classify_low_change` | Classifies input into categories. | `before, after` | Returns (typically): str |
| `_build_low_changes` | Builds payload/contract/structured data. | `original_text, cleaned_text` | Returns (typically): list[dict[str, str]] |
| `_extract_schema_used` | Extracts structured information. | `raw_schema` | Returns (typically): dict[str, list[str]] |
| `_extract_term_corrections` | Extracts structured information. | `mappings` | Returns (typically): list[dict[str, str]] |
| `_extract_schema_adjustments` | Extracts structured information. | `mappings` | Returns (typically): list[dict[str, str]] |
| `_build_preprocessing_high_payload` | Loads configuration/data. | `preprocess_high_result` | Returns (typically): dict[str, Any] |
| `build_preprocessing_metadata` | Builds payload/contract/structured data. | `text` | Returns (typically): tuple[dict[str, Any], dict[str, Any]] |

## shared/query_planner.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic, SQL Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `build_schema_metadata` | Builds payload/contract/structured data. | `schema` | Returns (typically): dict[str, dict[str, Any]] |
| `_looks_temporal_column_name` | Helper within this module. | `column_name` | Returns (typically): bool |
| `_is_relationship_question` | Helper within this module. | `question_lower` | Returns (typically): bool |
| `_is_distribution_question` | Helper within this module. | `question_lower` | Returns (typically): bool |
| `_resolve_numeric_hint` | Helper within this module. | `hint, table_meta, ambiguities` | Returns (typically): str | None |
| `_derive_metric_by_token_groups` | Helper within this module. | `none` | Returns (typically): dict[str, Any] | None |
| `_infer_derived_metric` | Infers values from context. | `none` | Returns (typically): dict[str, Any] | None |
| `_infer_relationship_metrics` | Infers values from context. | `none` | Returns (typically): list[dict[str, Any]] |
| `normalize_analytical_intent` | Normalizes values to canonical shape. | `none` | Returns (typically): dict[str, Any] |
| `_is_overall_total_request` | Helper within this module. | `question_lower` | Returns (typically): bool |
| `_infer_time_granularity` | Infers values from context. | `question_lower` | Returns (typically): str |
| `_is_trend_over_time_question` | Helper within this module. | `question_lower` | Returns (typically): bool |
| `_select_time_column` | Helper within this module. | `table_meta` | Returns (typically): str |
| `_time_dimension_expression` | Helper within this module. | `none` | Returns (typically): str |
| `_string_time_parse_expr` | Parses raw input to structured output. | `column_name` | Returns (typically): str |
| `_source_grain_matches_requested` | Infer whether the selected time column is already at the requested analysis grain. | `none` | Returns (typically): bool |
| `_supports_hour_granularity` | Helper within this module. | `none` | Returns (typically): bool |
| `_normalize_dimension_ambiguities` | Normalizes values to canonical shape. | `ambiguities` | Returns (typically): list[dict[str, Any]] |
| `_time_column_priority` | Helper within this module. | `column_name` | Returns (typically): int |
| `_categorical_column_priority` | Helper within this module. | `column_name` | Returns (typically): int |
| `_auto_select_ranking_dimension` | Helper within this module. | `none` | Returns (typically): str | None |
| `_resolve_table` | Helper within this module. | `question, raw_intent, schema_metadata` | Returns (typically): str | None |
| `_resolve_column_name` | Helper within this module. | `candidate, columns` | Returns (typically): str | None |
| `_resolve_column_name_with_ambiguity` | Helper within this module. | `none` | Returns (typically): str | None |
| `_expand_tokens` | Helper within this module. | `tokens` | Returns (typically): set[str] |
| `_detect_rank_direction` | Helper within this module. | `question_lower` | Returns (typically): str | None |
| `_extract_limit` | Extracts structured information. | `question_lower, raw_intent` | Returns (typically): tuple[int | None, bool] |
| `_infer_ranking` | Infers values from context. | `none` | Returns (typically): dict[str, Any] |
| `_detect_explicit_aggregation` | Helper within this module. | `question_lower` | Returns (typically): str | None |
| `_is_rate_like` | Helper within this module. | `column_name` | Returns (typically): bool |
| `_is_avg_like` | Helper within this module. | `column_name` | Returns (typically): bool |
| `_looks_additive` | Helper within this module. | `column_name` | Returns (typically): bool |
| `_looks_identifier_like` | Helper within this module. | `column_name` | Returns (typically): bool |
| `_is_business_metric_column` | Helper within this module. | `column_name` | Returns (typically): bool |
| `_is_explicit_row_count_request` | Helper within this module. | `question_lower` | Returns (typically): bool |
| `_aggregation_for_ranking` | Helper within this module. | `column_name, question_lower, has_dimensions` | Returns (typically): str | None |
| `_has_grouping_intent` | Helper within this module. | `question_lower` | Returns (typically): bool |
| `_metric_alias` | Helper within this module. | `aggregation, column` | Returns (typically): str |
| `_score_metric_column` | Helper within this module. | `column_name, question_tokens` | Returns (typically): int |
| `_extract_metric_hints_from_question` | Extracts structured information. | `question` | Returns (typically): list[str] |
| `_iter_raw_metric_candidates` | Helper within this module. | `raw_intent` | Returns (typically): list[tuple[str, str | None]] |
| `_infer_metrics` | Infers values from context. | `none` | Returns (typically): list[dict[str, Any]] |
| `_clean_dimension_phrase` | Helper within this module. | `phrase` | Returns (typically): str |
| `_clean_metric_hint` | Helper within this module. | `phrase` | Returns (typically): str |
| `_extract_dimension_hints` | Extracts structured information. | `question` | Returns (typically): list[str] |
| `_infer_dimensions` | Infers values from context. | `question, raw_intent, table_meta` | Returns (typically): list[str] |
| `_normalize_numeric_filter_value` | Normalizes values to canonical shape. | `raw_value` | Returns (typically): int | float |
| `_filter_column_candidates` | Helper within this module. | `candidate_column` | Returns (typically): list[str] |
| `_resolve_filter_column` | Helper within this module. | `candidate_column, all_columns, column_map` | Returns (typically): str | None |
| `_normalize_filters` | Normalizes values to canonical shape. | `question, raw_intent, table_meta` | Returns (typically): list[dict[str, Any]] |
| `_infer_year_filter` | Infers values from context. | `question_lower, table_meta` | Returns (typically): dict[str, Any] | None |
| `_normalize_order_by` | Normalizes values to canonical shape. | `raw_intent, table_meta` | Returns (typically): list[dict[str, str]] |
| `_derive_operations` | Helper within this module. | `none` | Returns (typically): list[str] |
| `_infer_primary_intent` | Infers values from context. | `none` | Returns (typically): str |

## shared/query_service_auth.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Bearer token resolution for query-service (Dagster pipeline + sql_review).
- **Architectural Goal:** Shared Core Logic, SQL Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `set_forwarded_query_service_bearer_token` | Store a user JWT from the pipeline request (same worker / thread as downstream assets). | `token` | Returns (typically): None |
| `_forwarded_bearer` | Helper within this module. | `none` | Returns (typically): str |
| `_strip_bearer_prefix` | Helper within this module. | `raw` | Returns (typically): str |
| `_django_settings_internal_token` | Helper within this module. | `none` | Returns (typically): str |
| `_service_internal_token_from_env` | Primary shared secret for service-to-service query-service calls. | `none` | Returns (typically): str |
| `resolve_query_service_bearer_token` | Return bearer secret for query-service: internal token first, then forwarded user JWT. | `none` | Returns (typically): str |
| `bearer_matches_configured_internal_secret` | True when ``token`` (with or without ``Bearer ``) equals the configured internal S2S secret. | `token` | Returns (typically): bool |
| `require_query_service_bearer_token` | Fail fast when no token is available for query-service HTTP (no silent unauthenticated calls). | `none` | Returns (typically): str |

## shared/schema_filtering.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_normalized_table_name` | Normalizes values to canonical shape. | `table_name` | Returns (typically): str |
| `is_technical_table_name` | Helper within this module. | `table_name` | Returns (typically): bool |
| `_technical_column_count` | Helper within this module. | `columns` | Returns (typically): int |
| `filter_business_schema` | Helper within this module. | `schema` | Returns (typically): tuple[dict[str, list[dict[str, Any]]], dict[str, Any]] |
| `rank_tables_for_question` | Helper within this module. | `none` | Returns (typically): list[str] |

## shared/schema_utils.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `tokenize` | Helper within this module. | `text` | Returns (typically): set[str] |
| `normalize_column_type` | Normalizes values to canonical shape. | `col_type` | Returns (typically): str |
| `is_numeric_type` | Helper within this module. | `col_type` | Returns (typically): bool |
| `is_date_type` | Helper within this module. | `col_type` | Returns (typically): bool |
| `is_dimension_type` | Helper within this module. | `col_type` | Returns (typically): bool |
| `build_table_metadata` | Builds payload/contract/structured data. | `columns` | Returns (typically): dict[str, Any] |
| `_split_table_parts` | Helper within this module. | `table_name` | Returns (typically): list[str] |
| `normalize_table_name` | Normalize table names to ClickHouse-safe `database.table` form. | `table_name, default_db` | Returns (typically): str |
| `unqualify_table_name` | Return plain table name with database prefix removed when present. | `table_name` | Returns (typically): str |

## shared/semantic_contract_validator.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_question_has_any` | Helper within this module. | `question, tokens` | Returns (typically): bool |
| `_dedupe` | Helper within this module. | `items` | Returns (typically): list[str] |
| `_metric_columns` | Helper within this module. | `intent` | Returns (typically): list[str] |
| `_as_metric_specs` | Helper within this module. | `metrics, fallback_aggregation` | Returns (typically): list[dict[str, Any]] |
| `_sql_has_group_by` | Helper within this module. | `sql` | Returns (typically): bool |
| `_schema_column_info` | Helper within this module. | `schema` | Returns (typically): dict[str, Any] |
| `_resolve_selected_columns` | Helper within this module. | `selected_columns, schema_info` | Returns (typically): list[str] |
| `_question_mentions_column` | Helper within this module. | `question, column_name` | Returns (typically): bool |
| `_infer_time_grain` | Infers values from context. | `question, default` | Returns (typically): str |
| `_infer_explicit_chart_request` | Infers values from context. | `question` | Returns (typically): str |
| `_pick_time_column` | Helper within this module. | `intent, schema_info, selected_columns` | Returns (typically): str |
| `_pick_group_dimension` | Helper within this module. | `intent, schema_info, selected_columns` | Returns (typically): str |
| `_ensure_metric_specs` | Helper within this module. | `intent` | Returns (typically): None |
| `_chart_for_intent` | Helper within this module. | `intent, question` | Returns (typically): str |
| `recover_intent_from_question` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `validate_semantic_contract` | Validates input/business constraints. | `none` | Returns (typically): dict[str, Any] |

## shared/sql_compiler.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic, SQL Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_format_ch_settings` | Produce the canonical ``/* ch_settings: ... */`` header. | `settings` | Returns (typically): str |
| `_resolve_workspace_db` | Resolve the per-tenant ClickHouse database used to qualify the table. | `none` | Returns (typically): str |
| `compile_sql` | Compile structured intent into a ClickHouse-flavoured SQL statement. | `intent, schema` | Returns (typically): str |
| `_resolve_schema_table_name` | Helper within this module. | `table_name, schema` | Returns (typically): str | None |
| `_normalize_and_validate_table_name` | Validates input/business constraints. | `table_name, default_db` | Returns (typically): str |
| `_default_metric_alias` | Helper within this module. | `aggregation, column` | Returns (typically): str |
| `_build_type_cast_map` | Builds payload/contract/structured data. | `type_casting` | Returns (typically): dict[str, str] |
| `_metric_expression` | Helper within this module. | `none` | Returns (typically): str |
| `_resolve_formula_operand_expression` | Helper within this module. | `none` | Returns (typically): tuple[str, bool] |
| `_compile_formula_expression` | Compiles query/contract/prompt. | `none` | Returns (typically): tuple[str, bool] |
| `_format_filter_value` | Helper within this module. | `value` | Returns (typically): str |
| `_build_where_clause` | Builds payload/contract/structured data. | `filters, column_map, type_cast_map` | Returns (typically): str |
| `_build_order_clause` | Builds payload/contract/structured data. | `order_by, column_map, metric_aliases, dimension_aliases` | Returns (typically): str |
| `_build_limit_clause` | Builds payload/contract/structured data. | `limit` | Returns (typically): str |
| `_format_select_clause` | Helper within this module. | `select_parts` | Returns (typically): str |
| `_validate_sql_structure` | Validates input/business constraints. | `sql` | Returns (typically): None |
| `_is_string_like_type` | Helper within this module. | `column_type` | Returns (typically): bool |
| `_is_business_metric_column_name` | Helper within this module. | `column_name` | Returns (typically): bool |
| `_normalize_clickhouse_date_casts` | Normalizes values to canonical shape. | `sql` | Returns (typically): str |
| `_build_time_dimension_expression` | Builds payload/contract/structured data. | `none` | Returns (typically): str |
| `_string_time_parse_expr` | Parses raw input to structured output. | `column_name` | Returns (typically): str |
| `_infer_groupable_dimension` | Infers values from context. | `columns` | Returns (typically): str | None |

## shared/sql_parser.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Shared Core Logic, SQL Logic
- **Important Classes:**
  - `SqlParserStatus` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_fallback_allowed` | Helper within this module. | `none` | Returns (typically): bool |
| `ensure_sql_parser_ready` | Parses raw input to structured output. | `none` | Returns (typically): SqlParserStatus |
| `SqlParserStatus.__init__` | Helper within this module. | `self, parser, available, degraded` | Returns context-dependent output or mutates state. |

## shared/sql_review.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** SQL review and correction stage (Phase 6 / CRIT-04 + CRIT-05).
- **Architectural Goal:** Shared Core Logic, SQL Logic
- **Important Classes:**
  - `SqlReviewConfig` (object): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `get_last_query_service_auth_status` | Auth outcome of the most recent query-service validate call (for pipeline trace). | `none` | Returns (typically): str |
| `_set_query_service_auth_status` | Helper within this module. | `value` | Returns (typically): None |
| `query_validate_request_context` | Bind workspace_id and Bearer token for nested :func:`validate_sql` / ``_query_service_validate`` calls. | `none` | Returns (typically): Iterator[None] |
| `_validation_workspace_id` | Helper within this module. | `none` | Returns (typically): str |
| `_validation_bearer_token` | Helper within this module. | `none` | Returns (typically): str |
| `bind_query_service_validation_for_pipeline` | Set validation ContextVars; pair with :func:`reset_query_service_validation_for_pipeline`. | `none` | Returns (typically): Tuple[Any, Any] |
| `reset_query_service_validation_for_pipeline` | Helper within this module. | `handles` | Returns (typically): None |
| `_query_service_validate` | Call query-service /query/validate/ and cache for the pipeline run. | `sql` | Returns (typically): tuple[bool, str] |
| `validate_sql` | Replacement for the deleted regex-based shared.sql_validator.validate_sql. | `sql` | Returns (typically): None |
| `_schema_to_prompt` | Helper within this module. | `schema` | Returns (typically): str |
| `_build_review_prompt` | Builds payload/contract/structured data. | `none` | Returns (typically): str |
| `_parse_json_payload` | Loads configuration/data. | `raw_output` | Returns (typically): dict[str, Any] |
| `_call_openrouter` | Determines the next processing route. | `prompt` | Returns (typically): str |
| `_call_ollama` | Helper within this module. | `prompt, config` | Returns (typically): str |
| `_deterministic_review` | Helper within this module. | `question, generated_sql` | Returns (typically): dict[str, Any] |
| `_sql_mentions_token` | Helper within this module. | `sql_upper, token` | Returns (typically): bool |
| `_validate_sql_against_intent` | Validates input/business constraints. | `sql, validated_intent` | Returns (typically): list[str] |
| `_is_row_count_request` | Helper within this module. | `question` | Returns (typically): bool |
| `_is_predictive_question` | Phase 6 / CRIT-06: delegate to the canonical shared detector. | `question` | Returns (typically): bool |
| `_normalize_clickhouse_date_casts` | Normalizes values to canonical shape. | `sql` | Returns (typically): str |
| `_apply_output_sanity_checks` | Checks health/validity/status. | `none` | Returns (typically): tuple[str, list[str]] |
| `review_and_correct_sql` | Helper within this module. | `none` | Returns (typically): dict[str, Any] |
| `SqlReviewConfig.from_env` | Helper within this module. | `cls` | Returns (typically): 'SqlReviewConfig' |

## shared/stage_contract.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Stage status contract (Phase 9 / Phase 10).
- **Architectural Goal:** Shared Core Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `normalize_stage_status` | Normalizes values to canonical shape. | `status` | Returns (typically): str |
| `stage_allows_progress` | Phase 9: ``delegated`` allows downstream stages to continue, like | `status` | Returns (typically): bool |

## shared/time_aware_sql_generator.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Time-aware SQL generation (PART 2 - ENFORCE TIME-AWARE SQL).
- **Architectural Goal:** Shared Core Logic, SQL Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `enforce_time_series_sql_structure` | Enforce time-series SQL structure. | `sql, time_column, time_granularity, metrics` | Returns (typically): str |
| `_build_time_expression` | Build time expression for SELECT clause. | `time_column, time_granularity` | Returns (typically): str |
| `validate_time_series_sql` | Validate that SQL has proper time-series structure. | `sql, time_column` | Returns (typically): tuple[bool, str] |
| `enrich_intent_for_time_series_sql` | Enrich intent with SQL generation hints for time-series. | `intent` | Returns (typically): dict[str, Any] |

## shared/time_semantics_detector.py
- **Responsibility:** Shared contracts, validators, SQL/chart policies.
- **Role in System:** Deterministic time semantics detection (PART 1 - CRITICAL AI LOGIC).
- **Architectural Goal:** Shared Core Logic
- **Important Classes:**
  - `TimeSemantics` (object): Time semantics detection result.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `extract_longest_time_keyword` | Return the longest TIME_KEYWORDS substring found in ``question`` (for diagnostics / repair hints). | `question` | Returns (typically): str |
| `detect_time_semantics` | Detect time-series intent from raw user question. | `question, available_columns` | Returns (typically): TimeSemantics |
| `preserve_time_expressions` | Ensure time expressions are NEVER removed during preprocessing. | `question` | Returns (typically): str |
| `enrich_intent_with_time_semantics` | Enrich intent JSON with time semantics metadata. | `intent, time_semantics` | Returns (typically): dict[str, Any] |
| `TimeSemantics.to_dict` | Helper within this module. | `self` | Returns (typically): dict[str, Any] |

## tests/test_ai_sql_parser_startup.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** SQL Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `test_ai_sql_parser_available_or_degraded_with_override` | Parses raw input to structured output. | `monkeypatch` | Returns context-dependent output or mutates state. |
| `test_ai_sql_parser_strict_raises_when_missing` | Parses raw input to structured output. | `monkeypatch` | Returns context-dependent output or mutates state. |

## tests/test_bi_hardening.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `BIHardeningTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `BIHardeningTests.test_correlation_impact_intent_sql_chart` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_distribution_intent_sql_chart` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_time_series_intent_sql_chart` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_daily_trend_preserves_daily_grain_metric_without_sum` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_weekly_total_rollup_still_aggregates` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_compare_two_metrics_per_week_remains_time_series` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_distribution_across_weeks_keeps_time_grouping` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_average_per_day_on_daily_grain_uses_line_without_sum` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_kpi_derived_metric_intent_sql_chart` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `BIHardeningTests.test_invalid_input_safety_intent_sql_chart` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |

## tests/test_canonical_pipeline_contract.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `test_non_data_classification_is_rejected_before_sql_generation` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_sql_review_prompt_receives_chart_contract` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## tests/test_chart_contract.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Chart Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `test_explicit_pie_contract` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_forecast_forces_line_contract` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_histogram_contract_autofills_x_axis` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_pie_contract_autofills_label_and_value` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## tests/test_chart_recommender_intelligence.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Chart Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_result` | Helper within this module. | `columns, rows` | Returns context-dependent output or mutates state. |
| `test_recommender_time_single_metric_line` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_recommender_time_multi_metric_line_multi` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_recommender_category_multi_metric_grouped_bar` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_recommender_geo_map` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_recommender_empty_dataset_table` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_recommender_detects_line_and_bars_as_combo` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_recommender_honors_explicit_stacked_intent` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## tests/test_chart_taxonomy.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Chart Logic
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `test_validate_chart_type_accepts_canonical` | Validates input/business constraints. | `none` | Returns context-dependent output or mutates state. |
| `test_validate_chart_type_maps_legacy_values` | Validates input/business constraints. | `none` | Returns context-dependent output or mutates state. |
| `test_validate_chart_type_raises_on_unknown_without_default` | Validates input/business constraints. | `none` | Returns context-dependent output or mutates state. |
| `test_metabase_display_mapping_supports_new_types` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## tests/test_deterministic_chart_selector.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Tests for deterministic chart selector.
- **Architectural Goal:** Chart Logic
- **Important Classes:**
  - `TestDeterministicChartSelector` (object): Test deterministic chart selection.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `TestDeterministicChartSelector.test_time_series_multi_metric_line_multi` | Test time series + multi-metric → line_multi (LOCKED). | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_time_series_single_metric_line` | Test time series + single metric → line (LOCKED). | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_categorical_multi_metric_bar_grouped` | Test categorical + multi-metric → bar_grouped. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_categorical_single_metric_bar` | Test categorical + single metric → bar. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_single_value_card` | Test single value → card. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_fallback_table` | Test fallback → table. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_apply_chart_selection` | Test applying chart selection to intent. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_percentage_overrides_time_series` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_distribution_overrides_time_series` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_relationship_priority_uses_scatter` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_explicit_pie_chart_lock_prevents_line_override` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_percentage_trend_over_time_prefers_line` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_enforce_chart_lock_locked` | Test chart lock enforcement when locked. | `self` | Returns context-dependent output or mutates state. |
| `TestDeterministicChartSelector.test_enforce_chart_lock_unlocked` | Test chart lock enforcement when unlocked. | `self` | Returns context-dependent output or mutates state. |

## tests/test_final_system_hardening.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `_FakeLogger` (object): No explicit class-level docstring.
  - `_FakeContext` (object): No explicit class-level docstring.
  - `FinalSystemHardeningTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_FakeLogger.info` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `_FakeLogger.warning` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `_FakeLogger.error` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `_FakeContext.__init__` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `FinalSystemHardeningTests.test_schema_deferred_analytical_query_proceeds_to_intent_validation` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `FinalSystemHardeningTests.test_confidence_penalizes_schema_deferred_and_forecast_fallback` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |

## tests/test_forecasting_pipeline.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `ForecastingPipelineTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `ForecastingPipelineTests.test_predictive_invariant_forces_requires_forecast` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_actual_vs_forecast_visualization_has_explicit_series_metadata` | Helper within this module. | `self, mock_forecast` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_forecasting_handler_preserves_chart_series_config` | Handles an operation/exception path. | `self, mock_build_forecast_dataset` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_time_column_selection_skips_metadata_and_falls_back_historical_when_insufficient` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_inconsistent_spacing_returns_historical_only_mode` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_technical_time_column_hint_is_rejected_and_business_time_is_used` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_predictive_sql_builder_enforces_ds_value_group_and_order` | Builds payload/contract/structured data. | `self` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_predictive_sql_builder_does_not_wrap_ds_in_todate` | Builds payload/contract/structured data. | `self` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_population_dataset_does_not_switch_tables_for_sales_question` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_predictive_sql_builder_auto_selects_best_table_when_not_provided` | Builds payload/contract/structured data. | `self, _mock_validate_sql` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_forecasting_handler_marks_forecast_error_as_degraded` | Handles an operation/exception path. | `self, mock_build_forecast_dataset` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_predict_next_7_days_returns_90_actual_plus_7_forecast_sorted_daily` | Helper within this module. | `self, mock_forecast` | Returns context-dependent output or mutates state. |
| `ForecastingPipelineTests.test_forecasting_handler_visualization_payload_line_and_daily` | Loads configuration/data. | `self, mock_forecast` | Returns context-dependent output or mutates state. |

## tests/test_intent_semantic_regressions.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_skip_remote_sql_validate` | Validates input/business constraints. | `none` | Returns (typically): None |
| `_metric_columns` | Helper within this module. | `intent` | Returns (typically): list[str] |
| `_run_pipeline` | Executes a full runnable flow. | `question` | Returns (typically): tuple[dict, str, dict] |
| `test_compare_sales_and_customers_over_time_generates_line_multi_grouped_sql` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_compare_sales_stripped_query_uses_original_question_for_time` | Simulates preprocessing that drops 'over time' from the working query. | `none` | Returns context-dependent output or mutates state. |
| `test_percentage_share_by_month_as_pie_stays_grouped_not_scalar` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_relationship_between_sales_and_orders_keeps_scatter_axes` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_show_total_sales_over_time_is_line_with_sum` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_compare_total_sales_and_customers_weekly_uses_week_bucket` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_show_total_sales_and_customers_without_time_is_not_line_multi` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_compare_total_sales_across_weeks_generates_line_week_grouping` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_compare_total_sales_across_months_generates_line_month_grouping` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_show_orders_by_month_is_grouped_and_not_card` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_distribution_of_customers_by_month_is_grouped_and_not_card` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_total_sales_scalar_kpi_allows_card` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## tests/test_llm_and_fallback_resilience.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_schema` | Helper within this module. | `none` | Returns (typically): LoadedUserSchema |
| `test_openrouter_diagnostics_have_sanitized_key_fields` | Determines the next processing route. | `none` | Returns context-dependent output or mutates state. |
| `test_preprocess_high_uses_deterministic_first_and_skips_ollama_for_exact_schema` | Runs a major processing step. | `mock_correct_query_terms, mock_load_user_schema` | Returns context-dependent output or mutates state. |
| `test_intent_extraction_openrouter_failure_uses_charted_deterministic_fallback` | Extracts structured information. | `mock_extract_and_validate` | Returns context-dependent output or mutates state. |

## tests/test_pipeline_guards.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `PipelineGuardTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `PipelineGuardTests.test_time_column_validator_rejects_technical_metadata` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PipelineGuardTests.test_dataset_scope_guard_prefers_explicit_table_name` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PipelineGuardTests.test_dataset_scope_guard_matches_qualified_table_binding` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PipelineGuardTests.test_forecasting_validator_blocks_insufficient_history` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PipelineGuardTests.test_dataset_scope_guard_raises_on_mismatch_when_strict` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |

## tests/test_pipeline_integration.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `_FakeLogger` (object): No explicit class-level docstring.
  - `_FakeContext` (object): No explicit class-level docstring.
  - `PipelineIntegrationTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_FakeLogger.info` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `_FakeLogger.warning` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `_FakeLogger.error` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `_FakeContext.__init__` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PipelineIntegrationTests.test_query_execution_asset_returns_sql_ready_without_clickhouse_execution` | Helper within this module. | `self, mock_build_sql, mock_review` | Returns context-dependent output or mutates state. |
| `PipelineIntegrationTests.test_query_execution_asset_rejects_when_upstream_rejected` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PipelineIntegrationTests.test_visualization_asset_finalizes_chart_contract` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PipelineIntegrationTests.test_distribution_query_generates_histogram_contract` | Helper within this module. | `self, mock_build_sql, mock_review` | Returns context-dependent output or mutates state. |
| `PipelineIntegrationTests.test_forecasting_asset_delegates_to_voice_service` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |

## tests/test_predictive_parser.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `test_predict_orders_next_week_detects_ds_and_orders` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |
| `test_predict_total_sales_next_7_days_uses_date_like_string_column` | Helper within this module. | `none` | Returns context-dependent output or mutates state. |

## tests/test_preprocessing_high_recovery.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `PreprocessHighRecoveryTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_loaded_schema_fixture` | Loads configuration/data. | `none` | Returns (typically): LoadedUserSchema |
| `PreprocessHighRecoveryTests.test_fuzzy_phrase_correction_maps_totol_sales_to_total_sales` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_fuzzy_token_correction_maps_custmers_to_customers` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_semantic_normalization_maps_impact_to_relationship` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_common_question_words_are_not_unresolved_schema_terms` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_conversational_and_misspelled_analytical_words_are_not_unresolved` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_evolution_language_is_not_flagged_as_schema_error` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_relational_connector_language_is_not_flagged_as_schema_error` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_visualization_and_aggregation_intent_words_are_not_unresolved` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_contribution_and_activity_words_are_not_unresolved` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_cumulative_and_noise_tokens_are_not_unresolved` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_stacked_chart_word_is_not_unresolved` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_month_and_action_words_are_not_unresolved` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_run_preprocess_high_recovers_typo_without_rejection` | Runs a major processing step. | `self, mock_validate_query_schema_usage, mock_correct_query_terms, mock_load_user_schema` | Returns context-dependent output or mutates state. |
| `PreprocessHighRecoveryTests.test_deferred_schema_validation_is_degraded_and_schema_invalid` | Helper within this module. | `self, mock_build_schema_resolution_diagnostics, mock_validate_query_schema_usage, mock_correct_query_terms, mock_load_user_schema` | Returns context-dependent output or mutates state. |

## tests/test_preprocessing_low_spelling.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `PreprocessingLowSpellingTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `PreprocessingLowSpellingTests._assert_preclassified_analytical` | Helper within this module. | `self, raw_text, cleaned_text` | Returns (typically): None |
| `PreprocessingLowSpellingTests.test_regression_highest_customers_typos_corrected_before_classification` | Helper within this module. | `self, _mock_clean_llm` | Returns context-dependent output or mutates state. |
| `PreprocessingLowSpellingTests.test_regression_filler_and_typos_corrected_before_classification` | Helper within this module. | `self, _mock_clean_llm` | Returns context-dependent output or mutates state. |
| `PreprocessingLowSpellingTests.test_regression_average_orders_typo_corrected_before_classification` | Helper within this module. | `self, _mock_clean_llm` | Returns context-dependent output or mutates state. |
| `PreprocessingLowSpellingTests.test_regression_predict_monthly_typo_corrected_before_classification` | Helper within this module. | `self, _mock_clean_llm` | Returns context-dependent output or mutates state. |
| `PreprocessingLowSpellingTests.test_spelling_pass_corrects_typos_when_cleaner_output_still_contains_mistakes` | Helper within this module. | `self, _mock_clean_llm, _mock_spelling_llm` | Returns context-dependent output or mutates state. |
| `PreprocessingLowSpellingTests.test_fallback_uses_rule_based_cleaner_when_llm_fails` | Helper within this module. | `self, _mock_clean_llm` | Returns context-dependent output or mutates state. |

## tests/test_stage_contracts.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `StageContractTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `StageContractTests.test_normalize_stage_status_maps_legacy_routed_to_success` | Normalizes values to canonical shape. | `self` | Returns context-dependent output or mutates state. |
| `StageContractTests.test_stage_allows_progress_for_degraded` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |

## tests/test_time_semantics_detector.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Tests for time semantics detector.
- **Important Classes:**
  - `TestTimeSemanticsDetector` (object): Test time semantics detection.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `TestTimeSemanticsDetector.test_detect_over_time` | Test detection of 'over time' phrase. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_detect_trend` | Test detection of 'trend' keyword. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_detect_daily` | Test detection of 'daily' with correct granularity. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_detect_weekly` | Test detection of 'weekly' with correct granularity. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_detect_monthly` | Test detection of 'monthly' with correct granularity. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_detect_by_date` | Helper within this module. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_no_time_keywords` | Test non-time-series query. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_time_column_from_schema` | Test time column detection from available columns. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_enrich_intent` | Test intent enrichment with time semantics. | `self` | Returns context-dependent output or mutates state. |
| `TestTimeSemanticsDetector.test_multiple_time_keywords` | Test detection with multiple time keywords. | `self` | Returns context-dependent output or mutates state. |

## tests/test_whisper_llm_chart_propagation.py
- **Responsibility:** Support module inside ai-service.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** Chart Logic
- **Important Classes:**
  - `WhisperLlmChartPropagationTests` (unittest.TestCase): No explicit class-level docstring.
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `WhisperLlmChartPropagationTests.test_selected_chart_type_is_applied_to_chart_payload` | Loads configuration/data. | `self` | Returns context-dependent output or mutates state. |

## whisper_app/__init__.py
- **Responsibility:** Transcription app (Whisper-related endpoints/tasks).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
- **Important Functions/Methods:** none

## whisper_app/admin.py
- **Responsibility:** Django admin configuration.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
- **Important Functions/Methods:** none

## whisper_app/apps.py
- **Responsibility:** Django app registration.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `WhisperAppConfig` (AppConfig): No explicit class-level docstring.
- **Important Functions/Methods:** none

## whisper_app/migrations/__init__.py
- **Responsibility:** Django migration schema file.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
- **Important Functions/Methods:** none

## whisper_app/models.py
- **Responsibility:** Data model layer.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
- **Important Functions/Methods:** none

## whisper_app/transcription_task.py
- **Responsibility:** Transcription app (Whisper-related endpoints/tasks).
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:**
  - `TranscriptionResult` (TypedDict): No explicit class-level docstring.
  - `TranscriptionError` (Exception): Base exception for transcription step failures.
  - `SystemResourceError` (TranscriptionError): Resource exhaustion (OOM/CPU pressure/temporary exhaustion).
  - `ConcurrencyError` (TranscriptionError): Queue, lock, or contention related error.
  - `InputValidationError` (TranscriptionError): Input file quality/shape/format issue.
  - `ModelError` (TranscriptionError): Model loading/inference/runtime issue.
  - `ModelTimeoutError` (ModelError): Whisper inference timed out.
  - `InfrastructureError` (TranscriptionError): Runtime infrastructure dependency issue.
  - `Decision` (object): No explicit class-level docstring.
  - `PipelineConfig` (object): No explicit class-level docstring.
  - `TranscriptionRequest` (object): No explicit class-level docstring.
  - `LockLease` (object): No explicit class-level docstring.
  - `WhisperModelManager` (object): No explicit class-level docstring.
  - `RedisTranscriptionQueue` (object): No explicit class-level docstring.
  - `TranscriptionService` (object): Service layer owns execution semantics (retry, queueing, locking, idempotency).
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_env_int` | Helper within this module. | `name, default` | Returns (typically): int |
| `_env_float` | Helper within this module. | `name, default` | Returns (typically): float |
| `_utc_now` | Helper within this module. | `none` | Returns (typically): str |
| `_get_logger` | Fetches data and returns it. | `none` | Returns (typically): logging.Logger |
| `_log_event` | Helper within this module. | `logger, level, message` | Returns (typically): None |
| `_build_request_id` | Builds payload/contract/structured data. | `audio_path` | Returns (typically): str |
| `_exponential_backoff` | Helper within this module. | `retry_count, config` | Returns (typically): float |
| `classify_error` | Classify transcription errors for policy-based handling. | `exception` | Returns (typically): ErrorType |
| `_decide_action` | Helper within this module. | `error_type, retry_count, config` | Returns (typically): Decision |
| `_validate_input` | Validates input/business constraints. | `audio_path, config` | Returns (typically): None |
| `_validate_infrastructure` | Validates input/business constraints. | `none` | Returns (typically): None |
| `_build_success_result` | Builds payload/contract/structured data. | `text, retry_count` | Returns (typically): TranscriptionResult |
| `_build_failed_result` | Builds payload/contract/structured data. | `error_type, action_taken, retry_count` | Returns (typically): TranscriptionResult |
| `_execute_transcription` | Helper within this module. | `request, config, logger` | Returns (typically): TranscriptionResult |
| `_attach_fn_compat` | Keep compatibility for existing call sites/tests that use Prefect's `.fn`. | `func` | Returns context-dependent output or mutates state. |
| `transcribe_audio_task` | Runtime transcription step: voice-to-text transcription using local Whisper model. | `audio_path, request_id, language, initial_prompt` | Returns (typically): TranscriptionResult |
| `whisper_transcription_flow` | Dagster orchestration entrypoint for transcription only. | `audio_path, request_id, language, initial_prompt` | Returns (typically): TranscriptionResult |
| `_run_legacy_whisper_transcription_preprocess_intent` | Runs a major processing step. | `none` | Returns (typically): dict[str, Any] |
| `whisper_transcription_preprocess_intent_flow` | Dagster orchestration entrypoint for: | `audio_path, request_id, language, initial_prompt, user_id, manager_id, dataset_id, source_id, workspace_id, report_id, table_name` | Returns (typically): dict[str, Any] |
| `full_audio_transcription` | Backward-compatible helper that runs only the transcription step. | `audio_bytes` | Returns (typically): str |
| `PipelineConfig.from_env` | Helper within this module. | `cls` | Returns (typically): 'PipelineConfig' |
| `WhisperModelManager.__init__` | Helper within this module. | `self, config, logger` | Returns (typically): None |
| `WhisperModelManager._load_model` | Loads configuration/data. | `self` | Returns (typically): Any |
| `WhisperModelManager.get_model` | Fetches data and returns it. | `self` | Returns (typically): Any |
| `WhisperModelManager.reload_model` | Loads configuration/data. | `self` | Returns (typically): None |
| `WhisperModelManager.transcribe` | Helper within this module. | `self, request` | Returns (typically): str |
| `RedisTranscriptionQueue.__init__` | Helper within this module. | `self, config, logger` | Returns (typically): None |
| `RedisTranscriptionQueue._result_key` | Helper within this module. | `self, job_id` | Returns (typically): str |
| `RedisTranscriptionQueue._dedupe_key` | Helper within this module. | `self, job_id` | Returns (typically): str |
| `RedisTranscriptionQueue._heartbeat_key` | Helper within this module. | `self, job_id` | Returns (typically): str |
| `RedisTranscriptionQueue._enqueued_key` | Helper within this module. | `self, job_id` | Returns (typically): str |
| `RedisTranscriptionQueue.enqueue_once` | Atomically enqueue only once using Redis SET NX + queue push. | `self, job_id` | Returns (typically): bool |
| `RedisTranscriptionQueue.wait_for_result` | Helper within this module. | `self, job_id, timeout_seconds` | Returns (typically): Optional[TranscriptionResult] |
| `RedisTranscriptionQueue.get_cached_success_result` | Idempotency gate: | `self, job_id` | Returns (typically): Optional[TranscriptionResult] |
| `RedisTranscriptionQueue._evict_cached_result_key` | Helper within this module. | `self, result_key, job_id` | Returns (typically): None |
| `RedisTranscriptionQueue._recover_stale_head` | Helper within this module. | `self, head_job_id` | Returns (typically): None |
| `RedisTranscriptionQueue.wait_for_turn` | Helper within this module. | `self, job_id, timeout_seconds` | Returns (typically): LockLease |
| `RedisTranscriptionQueue._start_lock_heartbeat` | Helper within this module. | `self, job_id, token` | Returns (typically): LockLease |
| `RedisTranscriptionQueue.complete_job` | Helper within this module. | `self, lease` | Returns (typically): None |
| `RedisTranscriptionQueue.abandon_job` | Best-effort cleanup for a queued job that never reached lock ownership. | `self, job_id` | Returns (typically): None |
| `RedisTranscriptionQueue._cleanup_job_keys` | Helper within this module. | `self, job_id` | Returns (typically): None |
| `RedisTranscriptionQueue.store_result` | Helper within this module. | `self, job_id, result` | Returns (typically): None |
| `TranscriptionService.__init__` | Helper within this module. | `self, config, logger` | Returns (typically): None |
| `TranscriptionService.execute` | Helper within this module. | `self, request` | Returns (typically): TranscriptionResult |

## whisper_app/urls.py
- **Responsibility:** API route mapping.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Important Classes:** none
- **Important Functions/Methods:** none

## whisper_app/views.py
- **Responsibility:** API view/controller layer.
- **Role in System:** Supports the module-level responsibility in the ai-service execution flow.
- **Architectural Goal:** API Views
- **Important Classes:** none
| Function / Method | What It Does | Typical Inputs | Return / Effect |
|---|---|---|---|
| `_build_reasoning_from_pipeline` | Builds payload/contract/structured data. | `pipeline_result` | Returns (typically): dict |
| `_build_llm_from_pipeline` | Builds payload/contract/structured data. | `pipeline_result` | Returns (typically): dict | None |
| `transcribe_view` | Helper within this module. | `request` | Returns context-dependent output or mutates state. |

# Architecture Notes
- **Orchestration:** `dagster_pipeline` defines stage ordering and execution contracts for transcription -> preprocessing -> classification -> intent -> SQL/execution/visualization payload readiness.
- **AI/LLM Core:** `llm_app`, `reasoning_app`, and `intent_extraction` jointly handle prompt generation, model calls, intent normalization, and routing decisions.
- **Forecasting Layer:** `forecasting` adds predictive-series generation (TimesFM-based) used when the request is classified as predictive/forecasting.
- **Shared Policy Layer:** `shared` centralizes SQL safety/review, chart contract logic, confidence/scoring, and pipeline guardrails so multiple apps use one rule source.
- **Transcription Layer:** `whisper_app` handles speech-to-text entry paths and task orchestration for audio-first requests.

# Important Flows
1. Request enters Django endpoint (`llm_app`/`reasoning_app`/`whisper_app` depending on mode).
2. Input is normalized and guarded using shared policies (`shared/*`).
3. Dagster assets run stage-by-stage: transcription (if audio), preprocessing-low, classification/routing, preprocessing-high, intent extraction.
4. Intent is validated and converted into SQL planning structures; SQL policies/review run through shared modules.
5. For predictive routes, forecasting pipeline enriches output with forecast rows/metadata.
6. Service returns canonical payload (intent/sql/chart contract/trace metadata) for downstream services (especially voice-service).

# Refactor / Cleanup Notes
- Large embedded third-party subtree (`forecasting/timesfm/*`) increases maintenance surface; isolate vendor code or pin as external dependency when possible.
- Multiple apps include overlapping LLM-client/response parsing logic (`llm_app`, `reasoning_app`, `preprocessing_*`); consider shared abstraction to reduce duplication.
- Routing/classification logic appears in several places (`dagster assets`, `reasoning_app`, `intent_extraction`, `shared`); consolidate canonical decision source to avoid drift.
- Example/experiment scripts inside production service tree can blur boundaries; consider moving non-runtime examples to a separate docs/examples package.
- Some Django apps contain mostly utility/service code but still include full app scaffolding; evaluate modular simplification where DB models are minimal/unused.