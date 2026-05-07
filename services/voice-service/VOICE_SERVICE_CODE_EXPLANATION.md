# Project Overview
`voice-service` is the execution-facing service for voice/text BI requests in the BI Agentic Platform. It receives user requests, creates async pipeline jobs, coordinates AI + SQL + visualization stages, and exposes job/report status APIs.

# Folder Structure
- `service_config/`: Django/Celery bootstrap and project settings.
- `users/`: authentication, verification, profile, and account lifecycle endpoints.
- `workspace/`: workspace ownership, membership, invitation lifecycle, and role controls.
- `voice_reports/`: core voice analytics pipeline domain, APIs, orchestration, and tracing.
- `voice_reports/application/`: application-level job orchestration helpers.
- `voice_reports/infrastructure/`: cross-service clients/adapters (AI, query, visualization, workspace).
- `voice_reports/services/`: specialized processing/integration services (AI client, forecasting, metabase, etc.).
- `voice_reports/domain/`: domain constants/errors/statuses and chart-contract derivation logic.
- `voice_reports/utils/`: reusable utility functions (trace extraction, SQL normalization, chart inference).
- `*/migrations/`: schema evolution history.

# File Explanations
## manage.py
- **Responsibility:** Runtime/bootstrap file.
- **Role in System:** Django's command-line utility for administrative tasks.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `main` | Run administrative tasks. | `none` | Returns context-dependent output or mutates state. |

## service_config/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** voice-service Django project package.
- **Classes:** none
- **Functions/Methods:** none

## service_config/asgi.py
- **Responsibility:** Runtime/bootstrap file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## service_config/celery.py
- **Responsibility:** Runtime/bootstrap file.
- **Role in System:** Celery application bootstrap for voice-service.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `healthcheck` | Checks health/access/validity. | `self` | Returns (typically): str |

## service_config/settings.py
- **Responsibility:** Global Django and integration settings.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## service_config/urls.py
- **Responsibility:** Defines API routes and binds them to views.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## service_config/wsgi.py
- **Responsibility:** Runtime/bootstrap file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## users/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## users/admin.py
- **Responsibility:** Django Admin configuration.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `UserAdmin` (BaseUserAdmin): Admin configuration for custom User model.
- **Functions/Methods:** none

## users/apps.py
- **Responsibility:** Django AppConfig declaration.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `UsersConfig` (AppConfig): No explicit class docstring.
- **Functions/Methods:** none

## users/auth_urls.py
- **Responsibility:** Support file inside the service.
- **Role in System:** URL configuration for authentication endpoints.
- **Classes:** none
- **Functions/Methods:** none

## users/migrations/0001_initial.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.CreateModel
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## users/migrations/0002_profile_fields_and_password_reset_codes.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** _add_column_if_missing, _add_column_if_missing, _add_column_if_missing, _add_column_if_missing, migrations.CreateModel, migrations.AddIndex, migrations.AddIndex, migrations.AddIndex
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_add_column_if_missing` | Helper function within this module. | `name, sql_type, field` | Returns context-dependent output or mutates state. |

## users/migrations/__init__.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** none
- **Classes:** none
- **Functions/Methods:** none

## users/models.py
- **Responsibility:** Database models and relations.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** data model layer.
- **Classes:**
  - `UserManager` (BaseUserManager): Custom user manager for email-based authentication.
  - `User` (AbstractBaseUser, PermissionsMixin): Custom User model with email as the unique identifier.
  - `PasswordResetCode` (models.Model): Password reset verification code lifecycle.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `UserManager.create_user` | Create and return a regular user with an email and password. | `self, email, password, **extra_fields` | Returns context-dependent output or mutates state. |
| `UserManager.create_superuser` | Create and return a superuser with an email and password. | `self, email, password, **extra_fields` | Returns context-dependent output or mutates state. |
| `User.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `PasswordResetCode.is_expired` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |

## users/permissions.py
- **Responsibility:** Permission exports or local permission mapping.
- **Role in System:** voice-service users.permissions
- **Classes:** none
- **Functions/Methods:** none

## users/serializers.py
- **Responsibility:** Validation and data serialization/deserialization.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `SignUpSerializer` (serializers.Serializer): Serializer for user sign up.
  - `UserSerializer` (serializers.ModelSerializer): Serializer for User model.
  - `LoginSerializer` (serializers.Serializer): Serializer for user login with JWT token generation.
  - `LogoutSerializer` (serializers.Serializer): Serializer for user logout with JWT token blacklisting.
  - `ProfileSerializer` (serializers.ModelSerializer): Serializer for viewing user profile.
  - `UpdateProfileSerializer` (serializers.Serializer): Serializer for updating user profile (name and email only).
  - `DeactivateAccountSerializer` (serializers.Serializer): Serializer for deactivating user account.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `SignUpSerializer.validate_email` | Validate that email is unique. | `self, value` | Returns context-dependent output or mutates state. |
| `SignUpSerializer.validate_password` | Validate password strength using Django's password validators. | `self, value` | Returns context-dependent output or mutates state. |
| `SignUpSerializer.validate` | Validate signup data and handle invitation token. | `self, attrs` | Returns context-dependent output or mutates state. |
| `SignUpSerializer.create` | Create user and auto-create workspace if role is manager. | `self, validated_data` | Returns context-dependent output or mutates state. |
| `LoginSerializer.validate` | Validate login credentials and generate JWT tokens. | `self, attrs` | Returns context-dependent output or mutates state. |
| `LogoutSerializer.validate_refresh` | Validate that the refresh token is provided and valid. | `self, value` | Returns context-dependent output or mutates state. |
| `LogoutSerializer.save` | Blacklist the refresh token to invalidate it. | `self` | State/DB side effects (return value not primary). |
| `ProfileSerializer.get_workspace` | Get workspace info based on user role. | `self, obj` | Returns context-dependent output or mutates state. |
| `UpdateProfileSerializer.validate_email` | Validate that new email is unique. | `self, value` | Returns context-dependent output or mutates state. |
| `UpdateProfileSerializer.update` | Update user profile. | `self, instance, validated_data` | Returns context-dependent output or mutates state. |
| `DeactivateAccountSerializer.validate_refresh` | Validate that refresh token is provided. | `self, value` | Returns context-dependent output or mutates state. |
| `DeactivateAccountSerializer.save` | Deactivate user account and blacklist refresh token. | `self` | State/DB side effects (return value not primary). |

## users/user_urls.py
- **Responsibility:** Support file inside the service.
- **Role in System:** URL configuration for user profile endpoints.
- **Classes:** none
- **Functions/Methods:** none

## users/utils.py
- **Responsibility:** Support file inside the service.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `generate_verification_token` | Generate a signed verification token for email verification. | `user_id` | Returns context-dependent output or mutates state. |
| `verify_token` | Verify a signed token and extract the user ID. | `token, max_age` | Returns context-dependent output or mutates state. |
| `verify_email_token` | Verify email verification token and return detailed result. | `token, max_age` | Returns context-dependent output or mutates state. |
| `send_verification_email` | Send verification email to the user. | `user_email, user_name, token` | Returns context-dependent output or mutates state. |
| `generate_invitation_token` | Generate a simple unique token for workspace invitation. | `none` | Returns context-dependent output or mutates state. |
| `send_invitation_email` | Send workspace invitation email to the invited user. | `invited_email, inviter_name, workspace_name, token, role` | Returns context-dependent output or mutates state. |

## users/views.py
- **Responsibility:** API layer: handles HTTP requests/responses and permissions.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** API views.
- **Classes:**
  - `SignUpView` (APIView): API endpoint for user sign up.
  - `EmailVerificationView` (APIView): API endpoint for email verification.
  - `LoginView` (APIView): API endpoint for user login.
  - `LogoutView` (APIView): API endpoint for user logout.
  - `ProfileView` (APIView): API endpoint for viewing and updating user profile.
  - `DeactivateAccountView` (APIView): API endpoint for deactivating user account.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `SignUpView.post` | Handle user sign up request. | `self, request` | State/DB side effects (return value not primary). |
| `EmailVerificationView.get` | Handle email verification request. | `self, request` | Returns context-dependent output or mutates state. |
| `LoginView.post` | Handle user login request. | `self, request` | State/DB side effects (return value not primary). |
| `LogoutView.post` | Handle user logout request. | `self, request` | State/DB side effects (return value not primary). |
| `ProfileView.get` | Get authenticated user's profile. | `self, request` | Returns context-dependent output or mutates state. |
| `ProfileView.put` | Update authenticated user's profile. | `self, request` | State/DB side effects (return value not primary). |
| `DeactivateAccountView.delete` | Deactivate authenticated user's account. | `self, request` | State/DB side effects (return value not primary). |

## voice_reports/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/admin.py
- **Responsibility:** Django Admin configuration.
- **Role in System:** Voice Reports Admin
- **Classes:**
  - `VoiceReportAdmin` (admin.ModelAdmin): Admin interface for Voice Reports.
  - `SQLEditHistoryAdmin` (admin.ModelAdmin): Admin interface for SQL Edit History.
  - `DashboardPageAdmin` (admin.ModelAdmin): Admin interface for Dashboard Pages.
  - `ReportPageAssignmentAdmin` (admin.ModelAdmin): Admin interface for Report Page Assignments.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `SQLEditHistoryAdmin.has_add_permission` | Helper function within this module. | `self, request` | Returns context-dependent output or mutates state. |

## voice_reports/application/__init__.py
- **Responsibility:** Application orchestration/use-case layer.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** orchestration layer.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/application/job_service.py
- **Responsibility:** Application orchestration/use-case layer.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** orchestration layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `create_pipeline_job` | Creates a new object or DB row. | `report, input_type, original_question, payload` | Returns (typically): VoicePipelineJob |
| `mark_job_stage` | Marks job stage/status updates. | `job, status, stage, progress, error_code, error_message` | Returns (typically): VoicePipelineJob |

## voice_reports/application/orchestration_service.py
- **Responsibility:** Application orchestration/use-case layer.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** orchestration layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_safe_float` | Helper function within this module. | `value, default` | Returns (typically): float |
| `_classification_payload` | Helper function within this module. | `ai_result` | Returns (typically): dict[str, Any] |
| `_ai_sql_gate` | Helper function within this module. | `ai_result` | Returns (typically): tuple[bool, str, str] |
| `_is_predictive_request` | Helper function within this module. | `ai_result, intent` | Returns (typically): bool |
| `_forecast_horizon` | Helper function within this module. | `intent` | Returns (typically): int | None |
| `_forecasting_config` | Helper function within this module. | `forecast_dataset` | Returns (typically): dict[str, Any] |
| `_visualization_chart_config` | Helper function within this module. | `viz, chart_contract` | Returns (typically): dict[str, Any] |
| `_align_chart_contract_with_result` | Bind chart axes to actual result columns without changing chart type. | `chart_contract, columns, rows` | Returns (typically): dict[str, Any] |
| `_append_trace` | Helper function within this module. | `job, stage, status, details` | Returns (typically): None |
| `_build_report_ai_trace` | Builds a payload/contract/structure. | `report` | Returns (typically): dict[str, Any] |
| `_trace_version_tuple` | Phase 10 / §12.3: parse the ``trace_version`` field of a trace. | `trace` | Returns (typically): tuple[int, int] |
| `_select_trace_for_persistence` | Pick the freshest valid trace. | `existing_trace, ai_result` | Returns (typically): dict[str, Any] |
| `_finalize_failure` | Helper function within this module. | `job, report, error_code, message, fallback_trace` | Returns (typically): VoicePipelineJob |
| `process_pipeline_job` | Runs the main processing step. | `job_id` | Returns (typically): VoicePipelineJob |
| `_dispatch_pipeline_async` | Dispatch the pipeline to Celery (CRIT-02 of the audit). | `job_id` | Returns (typically): None |
| `enqueue_text_job` | Creates and queues async work. | `request, workspace, text, payload` | Returns (typically): tuple[VoiceReport, VoicePipelineJob] |
| `enqueue_audio_job` | Creates and queues async work. | `request, workspace, audio_path, payload` | Returns (typically): tuple[VoiceReport, VoicePipelineJob] |

## voice_reports/apps.py
- **Responsibility:** Django AppConfig declaration.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `VoiceReportsConfig` (AppConfig): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/chart_recovery.py
- **Responsibility:** Support file inside the service.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `infer_chart_type_from_shape` | Infers a value from context/data. | `columns, rows, intent` | Returns (typically): tuple[str, str] |

## voice_reports/chart_state.py
- **Responsibility:** Support file inside the service.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `merge_chart_config_with_fresh` | Helper function within this module. | `stored_chart_config, fresh_chart_contract` | Returns (typically): dict |

## voice_reports/constants/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** voice-service voice_reports.constants.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `validate_chart_type` | Validates incoming data. | `raw_chart_type, default` | Returns context-dependent output or mutates state. |

## voice_reports/domain/__init__.py
- **Responsibility:** Domain-level constants/rules, mostly framework-light.
- **Role in System:** Domain helpers (Django-free where possible).
- **Architectural Goal:** domain rule layer.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/domain/chart_from_ai_result.py
- **Responsibility:** Domain-level constants/rules, mostly framework-light.
- **Role in System:** Derive a :class:`~bi_platform_shared.contracts.chart.ChartContract` dict from ai-service payloads.
- **Architectural Goal:** domain rule layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_intent_chart_contract_candidates` | Build chart-contract fields from ``validated_intent`` / ``extracted_intent``. | `intent` | Returns (typically): dict[str, Any] |
| `contract_dict_from_ai_result` | Strict: require a valid chart contract from ai-service (no table fallback). | `ai_result` | Returns (typically): dict[str, Any] |

## voice_reports/domain/errors.py
- **Responsibility:** Domain-level constants/rules, mostly framework-light.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** domain rule layer.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/domain/statuses.py
- **Responsibility:** Domain-level constants/rules, mostly framework-light.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** domain rule layer.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/infrastructure/__init__.py
- **Responsibility:** Infrastructure adapter/client for external services.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** integration client layer.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/infrastructure/ai_client.py
- **Responsibility:** Infrastructure adapter/client for external services.
- **Role in System:** voice-service ⇄ ai-service convenience facade.
- **Architectural Goal:** integration client layer.
- **Classes:**
  - `AIClient` (object): Thin adapter around :class:`AIServiceClient`.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `get_ai_client` | Fetches and returns data. | `none` | Returns (typically): AIClient |
| `AIClient.__init__` | Helper function within this module. | `self` | Returns (typically): None |
| `AIClient.process_text` | Runs the main processing step. | `self, text, user_id, workspace_id, manager_id, dataset_id, source_id, table_name, report_id` | Returns context-dependent output or mutates state. |
| `AIClient.process_audio` | Runs the main processing step. | `self, audio_file, user_id, workspace_id, manager_id, dataset_id, source_id, table_name, report_id` | Returns context-dependent output or mutates state. |

## voice_reports/infrastructure/auth_context.py
- **Responsibility:** Infrastructure adapter/client for external services.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** integration client layer.
- **Classes:**
  - `IdentityContext` (object): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `extract_identity_context` | Extracts structured data from payload/input. | `request` | Returns (typically): IdentityContext |

## voice_reports/infrastructure/query_client.py
- **Responsibility:** Infrastructure adapter/client for external services.
- **Role in System:** voice-service ⇄ query-service client.
- **Architectural Goal:** integration client layer.
- **Classes:**
  - `QueryClient` (object): Thin wrapper for query-service ``/query/execute/`` calls.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_configured_internal_query_secret` | Helper function within this module. | `none` | Returns (typically): str |
| `_attach_voice_internal_service_header` | Set ``X-Internal-Service`` only when the bearer is the shared internal secret (not a user JWT). | `headers, bearer_token` | Returns (typically): None |
| `_query_service_url` | Helper function within this module. | `none` | Returns (typically): str |
| `validate_sql_via_query_service` | Validate SQL by calling query-service /query/validate/. | `sql, token, workspace_id` | Returns (typically): Tuple[bool, str, str] |
| `get_query_client` | Fetches and returns data. | `none` | Returns (typically): QueryClient |
| `QueryClient.execute` | Executes an operation (often SQL/HTTP). | `self, sql, authorization_header, workspace_id, workspace_database` | Returns context-dependent output or mutates state. |

## voice_reports/infrastructure/visualization_client.py
- **Responsibility:** Infrastructure adapter/client for external services.
- **Role in System:** voice-service ⇄ visualization-service HTTP client.
- **Architectural Goal:** integration client layer.
- **Classes:**
  - `VisualizationClient` (object): HTTP client for visualization-service.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_service_internal_authorization_header` | Bearer used for every visualization-service request (service-to-service). | `none` | Returns (typically): str |
| `_coerce_chart_contract_dict` | Normalize whatever the orchestrator forwarded into a flat contract dict. | `chart_payload` | Returns (typically): Dict[str, Any] |
| `get_visualization_client` | Process-wide singleton accessor for the visualization client. | `none` | Returns (typically): VisualizationClient |
| `VisualizationClient.__init__` | Helper function within this module. | `self` | Returns (typically): None |
| `VisualizationClient._headers` | Helper function within this module. | `authorization_header` | Returns (typically): Dict[str, str] |
| `VisualizationClient.create_visualization` | Creates a new object or DB row. | `self, report, sql, chart_payload, authorization_header` | Returns (typically): Dict[str, Any] |
| `VisualizationClient.create_empty_state_card` | GAP-04 helper for the orchestration empty-result branch. | `self, sql, message, authorization_header, name` | Returns (typically): Dict[str, Any] |
| `VisualizationClient.get_question_embed_url` | Fetches and returns data. | `self, question_id, authorization_header` | Returns (typically): str |
| `VisualizationClient.get_dashboard_embed_url` | Fetches and returns data. | `self, dashboard_id, authorization_header` | Returns (typically): str |
| `VisualizationClient.health` | Helper function within this module. | `self` | Returns (typically): bool |

## voice_reports/infrastructure/workspace_client.py
- **Responsibility:** Infrastructure adapter/client for external services.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** integration client layer.
- **Classes:**
  - `WorkspaceContext` (object): No explicit class docstring.
  - `WorkspaceClient` (object): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `get_workspace_client` | Fetches and returns data. | `none` | Returns (typically): WorkspaceClient |
| `WorkspaceClient.__init__` | Helper function within this module. | `self` | Returns (typically): None |
| `WorkspaceClient._headers` | Helper function within this module. | `self, authorization_header` | Returns (typically): dict[str, str] |
| `WorkspaceClient._get` | Fetches and returns data. | `self, url, headers, timeout` | Returns context-dependent output or mutates state. |
| `WorkspaceClient.resolve` | Resolves required context identifiers. | `self, request, workspace_hint, user_id, allow_local_resolver` | Returns (typically): WorkspaceContext |

## voice_reports/management/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/management/commands/__init__.py
- **Responsibility:** Operational Django management command.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/management/commands/process_voice_jobs.py
- **Responsibility:** Operational Django management command.
- **Role in System:** Management command to redispatch stuck voice pipeline jobs.
- **Classes:**
  - `Command` (BaseCommand): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `Command.add_arguments` | Helper function within this module. | `self, parser` | Returns context-dependent output or mutates state. |
| `Command.handle` | Helper function within this module. | `self, *args, **options` | Returns context-dependent output or mutates state. |

## voice_reports/migrations/0001_initial.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.CreateModel, migrations.CreateModel, migrations.CreateModel, migrations.CreateModel, migrations.AddIndex, migrations.AddIndex, migrations.AddIndex, migrations.AlterUniqueTogether, migrations.AlterUniqueTogether
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/migrations/0002_add_sql_editing_fields.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AddField, migrations.AddField, migrations.AlterField
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/migrations/0003_update_chart_and_status_lifecycle.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AlterField, migrations.AlterField
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/migrations/0004_add_preprocessing_metadata.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AddField, migrations.AddField
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/migrations/0005_add_pipeline_trace.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AddField
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/migrations/0006_add_ai_trace.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AddField
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/migrations/0007_voicepipelinejob.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.CreateModel, migrations.AddIndex, migrations.AddIndex, migrations.AddIndex
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## voice_reports/migrations/__init__.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** none
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/models.py
- **Responsibility:** Database models and relations.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** data model layer.
- **Classes:**
  - `VoiceReport` (models.Model): Voice-driven BI report with full audit trail.
  - `SQLEditHistory` (models.Model): Track all SQL edits for audit purposes.
  - `DashboardPage` (models.Model): Dashboard pages/tabs for organizing reports.
  - `ReportPageAssignment` (models.Model): Many-to-many relationship between reports and dashboard pages.
  - `VoicePipelineJob` (models.Model): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `VoiceReport.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `VoiceReport.can_edit_transcription` | Check if user can edit transcription. | `self, user` | Returns context-dependent output or mutates state. |
| `VoiceReport.can_edit_sql` | Check if user can edit SQL. | `self, user` | Returns context-dependent output or mutates state. |
| `VoiceReport.can_delete` | Check if user can delete report. | `self, user` | Returns context-dependent output or mutates state. |
| `SQLEditHistory.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `DashboardPage.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `ReportPageAssignment.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `VoicePipelineJob.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |

## voice_reports/services/__init__.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Active voice-service helpers.
- **Architectural Goal:** service layer.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/services/ai_service_client.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** voice-service ⇄ ai-service HTTP client.
- **Architectural Goal:** service layer.
- **Classes:**
  - `AIServiceClient` (object): Client for the ai-service AI pipeline.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_normalize_question_type` | Normalizes values to a canonical shape. | `value` | Returns (typically): str |
| `_adapt_canonical_ai_response` | Helper function within this module. | `payload, fallback_text` | Returns (typically): dict |
| `get_ai_service_client` | Process-wide singleton accessor for the AI service client. | `none` | Returns (typically): AIServiceClient |
| `AIServiceClient.__init__` | Helper function within this module. | `self` | Returns (typically): None |
| `AIServiceClient._headers` | Helper function within this module. | `self` | Returns (typically): Dict[str, str] |
| `AIServiceClient.check_health` | Checks health/access/validity. | `self` | Returns (typically): bool |
| `AIServiceClient._prepare_files` | Helper function within this module. | `self, audio_file` | Returns context-dependent output or mutates state. |
| `AIServiceClient.process_audio` | Runs the main processing step. | `self, audio_file, user_id, workspace_id, manager_id, dataset_id, source_id, table_name, report_id` | Returns (typically): Dict[str, Any] |
| `AIServiceClient._adapt_legacy_audio_response` | Helper function within this module. | `self, result` | Returns (typically): Dict[str, Any] |
| `AIServiceClient.process_text` | Runs the main processing step. | `self, text, user_id, workspace_id, manager_id, dataset_id, source_id, table_name, report_id` | Returns (typically): Dict[str, Any] |

## voice_reports/services/ai_trace_service.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** service layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_now_iso` | Helper function within this module. | `none` | Returns (typically): str |
| `_safe_dict` | Helper function within this module. | `payload` | Returns (typically): dict[str, Any] |
| `_safe_list` | Helper function within this module. | `payload` | Returns (typically): list[Any] |
| `_coerce_positive_int` | Helper function within this module. | `value` | Returns (typically): int | None |
| `_normalize_trace_stage_aliases` | Normalizes values to a canonical shape. | `trace` | Returns (typically): dict[str, Any] |
| `_normalize_status` | Normalizes values to a canonical shape. | `value` | Returns (typically): str |
| `_sample_rows` | Helper function within this module. | `rows, limit` | Returns (typically): list[dict[str, Any]] |
| `_extract_stage` | Extracts structured data from payload/input. | `trace, stage_name` | Returns (typically): tuple[dict[str, Any], dict[str, Any]] |
| `_extract_stage_any` | Extracts structured data from payload/input. | `trace, stage_names` | Returns (typically): tuple[dict[str, Any], dict[str, Any], bool] |
| `_status_from_stage` | Helper function within this module. | `stage_payload, stage_exists` | Returns (typically): str |
| `_normalize_question_type` | Normalizes values to a canonical shape. | `intent_json, classification_final, routing_final, forecasting_payload` | Returns (typically): str |
| `_extract_forecasting` | Extracts structured data from payload/input. | `chart_config, query_result, question_type` | Returns (typically): dict[str, Any] | None |
| `_collect_errors` | Helper function within this module. | `trace, report_error_message, forecasting_trace` | Returns (typically): list[dict[str, Any]] |
| `_extract_preprocessing_corrections` | Runs the main processing step. | `preprocess_high` | Returns (typically): list[dict[str, str]] |
| `_build_chart_decision_trace` | Builds a payload/contract/structure. | `chart_type, chart_config, visualization_stage` | Returns (typically): dict[str, Any] |
| `build_ai_trace_payload` | Builds a payload/contract/structure. | `report_id, transcription, preprocessing_low, preprocessing_high, intent_json, pipeline_trace, generated_sql, reviewed_sql, query_result, execution_time_ms, row_count, chart_type, metabase_question_id, metabase_dashboard_id, embed_url, chart_config, error_message` | Returns (typically): dict[str, Any] |

## voice_reports/services/audio_validation.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Audio upload validation (CRIT-11 hardening).
- **Architectural Goal:** service layer.
- **Classes:**
  - `AudioValidationResult` (object): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_max_size_bytes` | Helper function within this module. | `none` | Returns (typically): int |
| `_max_duration_seconds` | Helper function within this module. | `none` | Returns (typically): int |
| `_read_size` | Return the size of an UploadedFile-like object without exhausting it. | `uploaded_file` | Returns (typically): int |
| `_read_prefix` | Helper function within this module. | `uploaded_file, size` | Returns (typically): bytes |
| `_magic_looks_supported` | Helper function within this module. | `prefix, extension` | Returns (typically): bool |
| `_scan_with_clamav` | Return ``(clean, message)``. | `uploaded_file` | Returns (typically): tuple[bool, str] |
| `_measure_duration_seconds` | Best-effort duration measurement. | `uploaded_file, extension` | Returns (typically): Optional[float] |
| `validate_audio_upload` | Run the full hardened audio validation pipeline. | `uploaded_file` | Returns (typically): AudioValidationResult |

## voice_reports/services/clickhouse_executor.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** ClickHouse Executor
- **Architectural Goal:** service layer.
- **Classes:**
  - `ClickHouseExecutor` (object): Execute SELECT queries on ClickHouse using HTTP protocol (port 8123).
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_normalize_invalid_casts` | Global fix: Replace invalid ClickHouse functions with valid ones. | `sql` | Returns (typically): str |
| `sanitize_sql_for_http` | Sanitize SQL for ClickHouse HTTP execution. | `sql` | Returns (typically): str |
| `sanitize_numeric_value` | 🔒 NaN-SAFE: Sanitize a single numeric value to ensure JSON compatibility. | `value` | Returns (typically): Any |
| `sanitize_query_results` | 🔒 NaN-SAFE: Sanitize query results to ensure JSON compatibility. | `rows` | Returns (typically): List[Dict] |
| `get_clickhouse_executor` | Get or create ClickHouse executor singleton. | `none` | Returns (typically): ClickHouseExecutor |
| `ClickHouseExecutor.__init__` | Initialize ClickHouse executor with environment configuration. | `self` | Returns context-dependent output or mutates state. |
| `ClickHouseExecutor.execute_query` | Execute SQL query on ClickHouse. | `self, sql` | Returns (typically): Dict |
| `ClickHouseExecutor.test_connection` | Test ClickHouse connection. | `self` | Returns (typically): bool |
| `ClickHouseExecutor.get_tables` | Get list of tables in database. | `self, database` | Returns (typically): List[str] |
| `ClickHouseExecutor.get_table_schema` | Get schema for a table. | `self, table_name, database` | Returns (typically): Dict |

## voice_reports/services/forecasting_bridge.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** service layer.
- **Classes:**
  - `ForecastingBridgeError` (Exception): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_ai_service_base_url` | Helper function within this module. | `none` | Returns (typically): str |
| `_request_timeout_seconds` | Helper function within this module. | `none` | Returns (typically): int |
| `_headers` | Helper function within this module. | `none` | Returns (typically): dict[str, str] |
| `_post_json` | Helper function within this module. | `path, payload` | Returns (typically): dict[str, Any] |
| `detect_forecast_metadata` | Helper function within this module. | `intent, question_type, final_route` | Returns (typically): dict[str, Any] |
| `build_forecast_payload` | Builds a payload/contract/structure. | `columns, rows, intent, horizon` | Returns (typically): dict[str, Any] |
| `ForecastingBridgeError.__init__` | Helper function within this module. | `self, code, message, details` | Returns (typically): None |

## voice_reports/services/jwt_embedding.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** JWT Embedding Service (Metabase Self-Hosted)
- **Architectural Goal:** service layer.
- **Classes:**
  - `JWTEmbeddingService` (object): JWT token generation for Metabase self-hosted embedding.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `get_jwt_service` | Get or create JWT service singleton. | `none` | Returns (typically): JWTEmbeddingService |
| `JWTEmbeddingService.__init__` | Initialize from environment (METABASE_SECRET_KEY required for embedding). | `self` | Returns context-dependent output or mutates state. |
| `JWTEmbeddingService._ensure_secret` | Helper function within this module. | `self` | Returns (typically): None |
| `JWTEmbeddingService._to_metabase_resource` | Normalize resource payload to Metabase signed-embed format: | `self, resource` | Returns (typically): Dict[str, int] |
| `JWTEmbeddingService._validate_resource` | Validates incoming data. | `self, resource` | Returns (typically): None |
| `JWTEmbeddingService._validate_payload` | Validate JWT payload structure before signing. | `self, payload` | Returns (typically): None |
| `JWTEmbeddingService.generate_embed_token` | Generate JWT token for embedding. | `self, resource, params, exp_seconds` | Returns (typically): str |
| `JWTEmbeddingService.generate_dashboard_token` | Generate token specifically for dashboard embedding. | `self, dashboard_id, params` | Returns (typically): str |
| `JWTEmbeddingService.generate_question_token` | Generate token specifically for question embedding. | `self, question_id, params` | Returns (typically): str |
| `JWTEmbeddingService.get_embed_url` | Get full embed URL with JWT token (requires METABASE_SECRET_KEY). | `self, resource_type, resource_id, params` | Returns (typically): str |
| `JWTEmbeddingService.get_dashboard_embed_url` | Dashboard URL using secure JWT embed only. | `self, dashboard_id` | Returns (typically): str |
| `JWTEmbeddingService.get_question_embed_url` | Question URL using secure JWT embed only. | `self, question_id` | Returns (typically): str |
| `JWTEmbeddingService.verify_token` | Verify and decode JWT token; returns None if secret not set or invalid. | `self, token` | Returns (typically): Optional[Dict] |
| `JWTEmbeddingService.is_token_expired` | Check if token is expired. | `self, token` | Returns (typically): bool |

## voice_reports/services/metabase_service.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Metabase Self-Hosted Integration Service
- **Architectural Goal:** service layer.
- **Classes:**
  - `MetabaseService` (object): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_shared_request` | Helper that prefers the shared HTTP client and falls back to ``requests``. | `method, url, headers, json, timeout` | Returns context-dependent output or mutates state. |
| `_metabase_base_url` | Helper function within this module. | `none` | Returns (typically): str |
| `_metabase_embed_base_url` | Helper function within this module. | `none` | Returns (typically): str |
| `_credentials` | Helper function within this module. | `none` | Returns (typically): tuple[Optional[str], Optional[str]] |
| `check_metabase_health` | Checks health/access/validity. | `retries` | Returns (typically): bool |
| `get_metabase_session` | Fetches and returns data. | `force_refresh` | Returns (typically): Optional[str] |
| `clear_metabase_session` | Helper function within this module. | `none` | Returns (typically): None |
| `get_metabase_headers` | Fetches and returns data. | `none` | Returns (typically): Dict[str, str] |
| `get_metabase_service` | Fetches and returns data. | `none` | Returns (typically): MetabaseService |
| `MetabaseService.__init__` | Helper function within this module. | `self` | Returns (typically): None |
| `MetabaseService._clean_non_blank_string` | Helper function within this module. | `value` | Returns (typically): Optional[str] |
| `MetabaseService._extract_error_details` | Extracts structured data from payload/input. | `response` | Returns (typically): str |
| `MetabaseService._set_last_error` | Helper function within this module. | `self, message` | Returns (typically): None |
| `MetabaseService._string_list` | Helper function within this module. | `values` | Returns (typically): list[str] |
| `MetabaseService._normalize_display` | Normalizes values to a canonical shape. | `value` | Returns (typically): Optional[str] |
| `MetabaseService._safe_display_from_shape` | Helper function within this module. | `self, settings` | Returns (typically): str |
| `MetabaseService._prepare_visualization_settings` | Helper function within this module. | `self, visualization_settings` | Returns (typically): tuple[str, Dict[str, Any]] |
| `MetabaseService.health_check` | Checks health/access/validity. | `self` | Returns (typically): bool |
| `MetabaseService._headers` | Helper function within this module. | `self` | Returns (typically): Dict[str, str] |
| `MetabaseService._request` | Helper function within this module. | `self, method, path, json, retry_on_401` | Returns (typically): Optional[requests.Response] |
| `MetabaseService.authenticate` | Helper function within this module. | `self, username, password` | Returns (typically): bool |
| `MetabaseService.create_question` | Creates a new object or DB row. | `self, name, sql, description, visualization_settings` | Returns (typically): Optional[int] |
| `MetabaseService.update_question` | Updates existing data/state. | `self, card_id, name, sql, description, visualization_settings` | Returns (typically): bool |
| `MetabaseService.create_dashboard` | Creates a new object or DB row. | `self, name, description` | Returns (typically): Optional[int] |
| `MetabaseService.update_dashboard` | Updates existing data/state. | `self, dashboard_id, name, description` | Returns (typically): bool |
| `MetabaseService.add_question_to_dashboard` | Helper function within this module. | `self, question_id, dashboard_id, row, col, size_x, size_y` | Returns (typically): bool |
| `MetabaseService.get_dashboard` | Fetches and returns data. | `self, dashboard_id` | Returns (typically): Optional[Dict] |
| `MetabaseService.get_card` | Fetches and returns data. | `self, card_id` | Returns (typically): Optional[Dict] |
| `MetabaseService.delete_question` | Deletes or removes an entity. | `self, question_id` | Returns (typically): bool |
| `MetabaseService.enable_dashboard_embedding` | Helper function within this module. | `self, dashboard_id` | Returns (typically): bool |
| `MetabaseService.enable_question_embedding` | Helper function within this module. | `self, question_id` | Returns (typically): bool |
| `MetabaseService.get_question_embed_url` | Fetches and returns data. | `self, question_id, params` | Returns (typically): Optional[str] |
| `MetabaseService.get_dashboard_embed_url` | Fetches and returns data. | `self, dashboard_id, params` | Returns (typically): Optional[str] |

## voice_reports/services/notification_client.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Notification service client (voice-service).
- **Architectural Goal:** service layer.
- **Classes:**
  - `NotificationClient` (object): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `get_notification_client` | Fetches and returns data. | `none` | Returns (typically): NotificationClient |
| `NotificationClient.__init__` | Helper function within this module. | `self` | Returns (typically): None |
| `NotificationClient.send_event` | Sends data to another service. | `self, event_type, payload, event_key` | Returns (typically): Dict[str, Any] |
| `NotificationClient._post` | Helper function within this module. | `self, url, json, headers` | Returns context-dependent output or mutates state. |

## voice_reports/services/query_execution_service.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Voice-service ⇄ query-service execution helper (Phase 7 / CRIT-05).
- **Architectural Goal:** service layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `execute_sql_with_query_service` | Executes an operation (often SQL/HTTP). | `clean_sql, headers, workspace_id, query_service_url, timeout_seconds, workspace_database` | Returns (typically): dict[str, Any] |

## voice_reports/services/subscription_client.py
- **Responsibility:** Service/business helper for integrations or processing logic.
- **Role in System:** Subscription service client.
- **Architectural Goal:** service layer.
- **Classes:**
  - `SubscriptionClient` (object): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `get_subscription_client` | Fetches and returns data. | `none` | Returns context-dependent output or mutates state. |
| `SubscriptionClient.__init__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `SubscriptionClient.check_access` | Checks health/access/validity. | `self, workspace_id, authorization_header, consume` | Returns context-dependent output or mutates state. |

## voice_reports/tasks.py
- **Responsibility:** Support file inside the service.
- **Role in System:** Celery tasks for the voice pipeline.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `run_pipeline_async` | Run the voice pipeline for ``job_id``. | `self, job_id` | Returns context-dependent output or mutates state. |

## voice_reports/urls.py
- **Responsibility:** Defines API routes and binds them to views.
- **Role in System:** Voice Reports URLs
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/utils/__init__.py
- **Responsibility:** Reusable utility helpers.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** shared utility layer.
- **Classes:** none
- **Functions/Methods:** none

## voice_reports/utils/chart_selection.py
- **Responsibility:** Reusable utility helpers.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** shared utility layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_is_numeric_like` | Helper function within this module. | `value` | Returns (typically): bool |
| `_column_name` | Helper function within this module. | `column` | Returns (typically): str |
| `_column_type` | Helper function within this module. | `column` | Returns (typically): str |
| `_type_is_numeric` | Helper function within this module. | `column_type` | Returns (typically): bool |
| `profile_result_shape` | Helper function within this module. | `columns, rows` | Returns (typically): dict[str, Any] |
| `extract_upstream_chart_type` | Extracts structured data from payload/input. | `chart_config, pipeline_trace` | Returns (typically): str |
| `infer_chart_with_reason` | Infers a value from context/data. | `columns, rows, intent, preferred_chart_type` | Returns (typically): dict[str, str] |
| `infer_chart_type` | Infers a value from context/data. | `columns, rows, intent, preferred_chart_type` | Returns (typically): str |

## voice_reports/utils/sql_normalization.py
- **Responsibility:** Reusable utility helpers.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** shared utility layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `normalize_table_name` | Normalize table names to ClickHouse-safe form. | `table_name, default_db` | Returns (typically): str |
| `normalize_sql_table_references` | Normalize physical table references in SELECT/WITH SQL without rewriting CTE aliases. | `sql, default_db` | Returns (typically): str |

## voice_reports/utils/trace_builder.py
- **Responsibility:** Reusable utility helpers.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** shared utility layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `stage_trace` | Helper function within this module. | `stage, status, details` | Returns (typically): dict[str, Any] |

## voice_reports/utils/trace_extraction.py
- **Responsibility:** Reusable utility helpers.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** shared utility layer.
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `_safe_dict` | Helper function within this module. | `value` | Returns (typically): dict[str, Any] |
| `is_valid_trace` | Helper function within this module. | `trace` | Returns (typically): bool |
| `_payload_already_flat_pipeline_trace` | True when ``payload`` is a persisted pipeline_trace object (not an API envelope). | `payload` | Returns (typically): bool |
| `extract_pipeline_trace` | Extract a full pipeline trace from ai-service responses. | `response` | Returns (typically): dict[str, Any] |

## voice_reports/views.py
- **Responsibility:** API layer: handles HTTP requests/responses and permissions.
- **Role in System:** Voice Reports Views
- **Architectural Goal:** API views.
- **Classes:**
  - `VoiceUploadView` (APIView): Accept an audio request and run the canonical BI pipeline.
  - `TextQueryView` (APIView): Accept text and run the canonical BI pipeline.
  - `QueryExecuteView` (APIView): Re-execute a stored SQL report through query-service and visualization-service.
  - `SQLEditView` (APIView): Edit SQL query (Analyst only).
  - `ReportListView` (APIView): List all reports for workspace.
  - `ReportDetailView` (APIView): Get detailed report information.
  - `AITraceDetailView` (APIView): Analyst-facing explainability payload for the full AI pipeline.
  - `WorkspaceDashboardView` (APIView): Get workspace dashboard for embedded viewing (Executive).
  - `DashboardStatsView` (APIView): Return dashboard counters for the current user scope.
  - `JobStatusView` (APIView): Canonical async job status endpoint (CRIT-02).
  - `HealthCheckView` (APIView): Health check for all services.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `build_report_ai_trace` | Builds a payload/contract/structure. | `report, embed_url` | Returns (typically): dict |
| `_build_async_accepted_response` | CRIT-02: voice-service now returns 202 Accepted immediately. | `report, job` | Returns context-dependent output or mutates state. |
| `get_user_workspace` | Get the user's workspace based on their role. | `user` | Returns context-dependent output or mutates state. |
| `get_report_embed_url` | Generate a fresh question embed URL through visualization-service. | `report, metabase_service, authorization_header` | Returns context-dependent output or mutates state. |
| `_service_headers_with_auth` | Helper function within this module. | `request` | Returns context-dependent output or mutates state. |
| `_resolve_dataset_binding_context` | Resolve dataset binding from explicit request fields only. | `request, workspace_id, manager_id, explicit_dataset_id, explicit_source_id, explicit_table_name` | Returns (typically): dict[str, str] |
| `build_default_preprocessing_low` | Runs the main processing step. | `original_text` | Returns (typically): dict |
| `build_default_preprocessing_high` | Runs the main processing step. | `corrected_query` | Returns (typically): dict |
| `build_default_pipeline_trace` | Builds a payload/contract/structure. | `none` | Returns (typically): dict |
| `normalize_pipeline_trace` | Return persisted pipeline trace for API consumers without destroying in-flight shapes. | `payload` | Returns (typically): dict |
| `extract_pipeline_contract` | Extracts structured data from payload/input. | `pipeline_trace, confidence, confidence_breakdown, degraded` | Returns (typically): dict |
| `extract_report_contract` | Extracts structured data from payload/input. | `report` | Returns (typically): dict |
| `_flatten_schema_columns` | Helper function within this module. | `columns_payload` | Returns (typically): list[str] |
| `_dedupe_non_empty` | Helper function within this module. | `values` | Returns (typically): list[str] |
| `_extract_term_corrections_from_mappings` | Extracts structured data from payload/input. | `mappings` | Returns (typically): list[dict] |
| `_extract_schema_adjustments_from_mappings` | Extracts structured data from payload/input. | `mappings` | Returns (typically): list[dict] |
| `_extract_schema_usage_from_mappings` | Extracts structured data from payload/input. | `mappings` | Returns (typically): tuple[list[str], list[str]] |
| `normalize_preprocessing_low` | Runs the main processing step. | `payload, fallback_text` | Returns (typically): dict |
| `normalize_preprocessing_high` | Runs the main processing step. | `payload, fallback_query` | Returns (typically): dict |
| `_view_is_predictive` | Helper function within this module. | `intent` | Returns (typically): bool |
| `_view_forecast_horizon` | Helper function within this module. | `intent` | Returns (typically): int | None |
| `_view_forecasting_config` | Helper function within this module. | `forecast_dataset` | Returns (typically): dict |
| `VoiceUploadView.post` | Helper function within this module. | `self, request` | State/DB side effects (return value not primary). |
| `TextQueryView.post` | Helper function within this module. | `self, request` | State/DB side effects (return value not primary). |
| `QueryExecuteView.post` | Helper function within this module. | `self, request, report_id` | State/DB side effects (return value not primary). |
| `SQLEditView.put` | Helper function within this module. | `self, request, report_id` | State/DB side effects (return value not primary). |
| `ReportListView.get` | Fetches and returns data. | `self, request` | Returns context-dependent output or mutates state. |
| `ReportDetailView.get` | Fetches and returns data. | `self, request, report_id` | Returns context-dependent output or mutates state. |
| `ReportDetailView.delete` | Delete report (Manager only). | `self, request, report_id` | State/DB side effects (return value not primary). |
| `AITraceDetailView.get` | Fetches and returns data. | `self, request, report_id` | Returns context-dependent output or mutates state. |
| `WorkspaceDashboardView.get` | Fetches and returns data. | `self, request` | Returns context-dependent output or mutates state. |
| `DashboardStatsView.get` | Fetches and returns data. | `self, request` | Returns context-dependent output or mutates state. |
| `JobStatusView.get` | Fetches and returns data. | `self, request, job_id` | Returns context-dependent output or mutates state. |
| `HealthCheckView.get` | Check connectivity to ai-service, query-service and visualization-service. | `self, request` | Returns context-dependent output or mutates state. |

## voice_reports/voice_urls.py
- **Responsibility:** Support file inside the service.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## workspace/__init__.py
- **Responsibility:** Package initialization file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## workspace/admin.py
- **Responsibility:** Django Admin configuration.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `WorkspaceAdmin` (admin.ModelAdmin): Admin configuration for Workspace model.
  - `WorkspaceMemberAdmin` (admin.ModelAdmin): Admin configuration for WorkspaceMember model.
  - `InvitationAdmin` (admin.ModelAdmin): Admin configuration for Invitation model.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `WorkspaceAdmin.get_queryset` | Fetches and returns data. | `self, request` | Returns context-dependent output or mutates state. |
| `WorkspaceMemberAdmin.get_queryset` | Fetches and returns data. | `self, request` | Returns context-dependent output or mutates state. |
| `InvitationAdmin.get_queryset` | Fetches and returns data. | `self, request` | Returns context-dependent output or mutates state. |

## workspace/apps.py
- **Responsibility:** Django AppConfig declaration.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `WorkspaceConfig` (AppConfig): No explicit class docstring.
- **Functions/Methods:** none

## workspace/management/commands/expire_invitations.py
- **Responsibility:** Operational Django management command.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `Command` (BaseCommand): No explicit class docstring.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `Command.add_arguments` | Helper function within this module. | `self, parser` | Returns context-dependent output or mutates state. |
| `Command.handle` | Helper function within this module. | `self, *args, **options` | Returns context-dependent output or mutates state. |

## workspace/migrations/0001_initial.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.CreateModel, migrations.CreateModel, migrations.CreateModel
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## workspace/migrations/0002_alter_workspacemember_unique_together_and_more.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AlterUniqueTogether, migrations.AddField, migrations.AddField, migrations.AddField, migrations.AddField, migrations.AlterField, migrations.AlterField, migrations.AddIndex, migrations.AddIndex
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## workspace/migrations/0003_remove_invitation_unique_together_and_add_constraint.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AlterUniqueTogether, migrations.AddConstraint
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## workspace/migrations/0004_remove_old_invitation_constraint.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.RunSQL
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## workspace/migrations/0005_add_workspace_company_fields.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** migrations.AddField, migrations.AddField
- **Classes:**
  - `Migration` (migrations.Migration): No explicit class docstring.
- **Functions/Methods:** none

## workspace/migrations/__init__.py
- **Responsibility:** Database schema migration file.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Migration Operations:** none
- **Classes:** none
- **Functions/Methods:** none

## workspace/models.py
- **Responsibility:** Database models and relations.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** data model layer.
- **Classes:**
  - `Workspace` (models.Model): Workspace model representing a manager's workspace.
  - `WorkspaceMember` (models.Model): Model representing workspace membership for Analysts and Executives.
  - `Invitation` (models.Model): Model representing workspace invitations sent to new members.
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `Workspace.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `WorkspaceMember.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `Invitation.__str__` | Helper function within this module. | `self` | Returns context-dependent output or mutates state. |
| `Invitation.is_expired` | Check if invitation has expired. | `self` | Returns context-dependent output or mutates state. |
| `Invitation.save` | Set expiration date to 48 hours from creation if not set. | `self, *args, **kwargs` | State/DB side effects (return value not primary). |

## workspace/serializers.py
- **Responsibility:** Validation and data serialization/deserialization.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:**
  - `WorkspaceUpdateSerializer` (serializers.Serializer): Serializer for updating workspace information (Manager only).
  - `WorkspaceMemberSerializer` (serializers.Serializer): Serializer for workspace member information.
  - `WorkspaceSerializer` (serializers.ModelSerializer): Serializer for workspace basic information.
  - `InvitationSerializer` (serializers.Serializer): Serializer for workspace invitation (R9).
  - `RoleAssignmentSerializer` (serializers.Serializer): Serializer for assigning/updating member roles (R10).
  - `MemberDetailSerializer` (serializers.Serializer): Serializer for member detail view (R11).
  - `MemberUpdateSerializer` (serializers.Serializer): Serializer for updating member status (R11).
  - `MemberSuspendSerializer` (serializers.Serializer): Serializer for suspending a member (R12).
  - `AcceptInvitationSerializer` (serializers.Serializer): Serializer for accepting workspace invitation (R13).
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `WorkspaceUpdateSerializer.validate` | Validate that user is the workspace owner. | `self, attrs` | Returns context-dependent output or mutates state. |
| `WorkspaceUpdateSerializer.update` | Update workspace name and/or description. | `self, instance, validated_data` | Returns context-dependent output or mutates state. |
| `WorkspaceMemberSerializer.get_status` | Determine member status based on user state. | `self, obj` | Returns context-dependent output or mutates state. |
| `InvitationSerializer.validate` | Validate invitation request. | `self, attrs` | Returns context-dependent output or mutates state. |
| `RoleAssignmentSerializer.validate` | Validate role assignment request. | `self, attrs` | Returns context-dependent output or mutates state. |
| `MemberDetailSerializer.get_status` | Determine member status. | `self, obj` | Returns context-dependent output or mutates state. |
| `MemberUpdateSerializer.validate` | Validate member update request. | `self, attrs` | Returns context-dependent output or mutates state. |
| `MemberSuspendSerializer.validate` | Validate member suspension request. | `self, attrs` | Returns context-dependent output or mutates state. |
| `AcceptInvitationSerializer.validate` | Validate invitation token by looking up directly in Invitation model. | `self, attrs` | Returns context-dependent output or mutates state. |

## workspace/urls.py
- **Responsibility:** Defines API routes and binds them to views.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Classes:** none
- **Functions/Methods:** none

## workspace/utils.py
- **Responsibility:** Support file inside the service.
- **Role in System:** Workspace utility functions
- **Classes:** none
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `validate_invitation_token` | Validate invitation token by looking up in Invitation model. | `token` | Returns context-dependent output or mutates state. |

## workspace/views.py
- **Responsibility:** API layer: handles HTTP requests/responses and permissions.
- **Role in System:** Supports the folder-level concern and runtime flow.
- **Architectural Goal:** API views.
- **Classes:**
  - `WorkspaceUpdateView` (APIView): API endpoint for updating workspace information.
  - `WorkspaceMembersView` (APIView): API endpoint for viewing workspace members list.
  - `InvitationView` (APIView): API endpoint for inviting members to workspace (R9).
  - `RoleAssignmentView` (APIView): API endpoint for assigning/updating member roles (R10).
  - `MemberManageView` (APIView): API endpoint for managing workspace members (R11).
  - `MemberSuspendView` (APIView): API endpoint for suspending a member (R12).
  - `MemberUnsuspendView` (APIView): API endpoint for unsuspending a member.
  - `RemovePendingInvitationView` (APIView): API endpoint for removing pending invitations.
  - `AcceptInvitationView` (APIView): API endpoint for accepting workspace invitation (R13).
| Function/Method | What It Does | Typical Inputs | Return/Effect |
|---|---|---|---|
| `WorkspaceUpdateView.put` | Update workspace information (name and/or description). | `self, request` | State/DB side effects (return value not primary). |
| `WorkspaceMembersView.get` | Get list of all members in the user's workspace. | `self, request` | Returns context-dependent output or mutates state. |
| `InvitationView.post` | Send workspace invitation to a new member. | `self, request` | State/DB side effects (return value not primary). |
| `RoleAssignmentView.put` | Update the role of a workspace member. | `self, request, id` | State/DB side effects (return value not primary). |
| `MemberManageView.get` | Get detailed information about a workspace member. | `self, request, id` | Returns context-dependent output or mutates state. |
| `MemberManageView.put` | Update member status (active/pending). | `self, request, id` | State/DB side effects (return value not primary). |
| `MemberManageView.delete` | Remove member from workspace. | `self, request, id` | State/DB side effects (return value not primary). |
| `MemberSuspendView.put` | Suspend a workspace member. | `self, request, id` | State/DB side effects (return value not primary). |
| `MemberUnsuspendView.put` | Unsuspend a workspace member. | `self, request, id` | State/DB side effects (return value not primary). |
| `RemovePendingInvitationView.delete` | Remove a pending invitation by email. | `self, request, email` | State/DB side effects (return value not primary). |
| `AcceptInvitationView.get` | Accept workspace invitation using token. | `self, request` | Returns context-dependent output or mutates state. |

# Architecture Notes
- `voice_reports.application.orchestration_service` is the main coordinator for end-to-end job stages: AI classification/SQL, SQL validation, query execution, forecasting, visualization, and status/error tracing.
- `ai-service` integration is handled through `AIServiceClient` (via `infrastructure.ai_client` facade), and normalized into canonical response fields used by orchestrator and views.
- `query-service` is the single authority for SQL validation and execution (`/query/validate/`, `/query/execute/`), replacing local SQL safety ownership in voice-service.
- `visualization-service` owns chart rendering + Metabase-facing creation/embed URL logic; voice-service forwards chart contract + result data and persists final metadata.
- `workspace-service` (plus local workspace models) provides tenant/workspace context needed for consistent multi-tenant execution and permissions.

# Important Flows
1. Client submits audio/text to `VoiceUploadView` or `TextQueryView`.
2. Request is authenticated, workspace resolved, and subscription/audio checks are applied.
3. `VoiceReport` + `VoicePipelineJob` are created and API immediately returns `202 Accepted` with `job_id`.
4. Celery task (`run_pipeline_async`) picks the job and calls `process_pipeline_job(job_id)`.
5. Orchestrator calls ai-service, stores transcription/intent/sql/trace, then validates SQL via query-service.
6. If SQL passes, query-service executes query; results are persisted. Predictive requests optionally call forecasting bridge.
7. Visualization client sends chart contract + SQL + data to visualization-service, which creates chart/question + embed URL.
8. Report/job statuses are finalized; client polls `JobStatusView` and later reads list/detail endpoints.

# Refactor / Cleanup Notes
- `voice_reports/views.py` and `workspace/views.py` are very large and contain multiple concerns; split into smaller view/use-case modules for maintainability.
- Repeated verification/permission checks and repeated response-shape patterns can be centralized via custom permissions/mixins/helpers.
- `voice_reports/services/clickhouse_executor.py` looks legacy relative to the current query-service-first path; validate whether it is still required in production flow.
- Some overlap exists between metabase/visualization concerns across `services.metabase_service` and `infrastructure.visualization_client`; boundary tightening would reduce duplication risk.
- Multiple TODO placeholders exist (e.g., report history in voice report views) and can be tracked as explicit backlog tasks.

> Note: `tree.py` was listed in the provided tree output but was not present in the current `voice-service` directory at analysis time, so it could not be documented from source.