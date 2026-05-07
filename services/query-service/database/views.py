from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.conf import settings
import requests
import logging
import json

from bi_platform_shared.http import HttpClientError, get_default_client

from .models import Database
from .serializers import (
    DatabaseSerializer,
    DatabaseUploadResponseSerializer,
    DatabasePreviewSerializer
)
from .utils import ClickHouseClient, cleanup_database, format_file_size

logger = logging.getLogger(__name__)


class DatabaseHealthCheckView(APIView):
    """
    Health check endpoint to verify database module is loaded.
    GET: Returns system status
    """
    permission_classes = []  # Public endpoint
    
    def get(self, request):
        """Health check."""
        etl_url = getattr(settings, 'ETL_SERVICE_URL', 'http://127.0.0.1:8001')
        
        # Check ETL service
        etl_status = 'unknown'
        try:
            etl_response = get_default_client().get(
                f'{etl_url}/api/upload/',
                timeout=(1.0, 2.0),
                attach_internal_api_key=False,
            )
            etl_status = 'reachable'
        except (HttpClientError, requests.exceptions.RequestException):
            etl_status = 'unreachable'
        
        return Response({
            'success': True,
            'service': 'database',
            'status': 'healthy',
            'etl_service': etl_status,
            'etl_url': etl_url
        }, status=status.HTTP_200_OK)


class DatabaseUploadView(APIView):
    """
    Handle database file upload for managers.
    POST: Upload a new database file
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        """Upload database file with defensive error handling."""
        
        # ============================================================
        # 1. VALIDATION: Check user role
        # ============================================================
        if request.user.role != 'manager':
            logger.warning(f"Non-manager user {request.user.email} attempted database upload")
            return Response(
                {'success': False, 'message': 'Only managers can upload databases'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # ============================================================
        # 2. VALIDATION: Check file presence
        # ============================================================
        if 'file' not in request.FILES:
            logger.error("Upload attempt without file")
            return Response(
                {'success': False, 'message': 'No file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        uploaded_file = request.FILES['file']
        logger.info(f"Upload started: {uploaded_file.name} ({uploaded_file.size} bytes) by {request.user.email}")
        
        # ============================================================
        # 3. CHECK: Existing database (replace mode)
        # ============================================================
        existing_db = Database.objects.filter(manager=request.user).first()
        replace_mode = existing_db is not None
        
        if replace_mode:
            logger.info(f"Replace mode: Existing database {existing_db.id} will be replaced")
        
        # ============================================================
        # 4. ETL INTEGRATION: Forward file with defensive handling
        # ============================================================
        etl_url = getattr(settings, 'ETL_SERVICE_URL', 'http://127.0.0.1:8001')
        etl_upload_endpoint = f'{etl_url}/api/upload/'
        
        try:
            # Prepare multipart form data
            files = {
                'file': (
                    uploaded_file.name,
                    uploaded_file.file,
                    uploaded_file.content_type or 'application/octet-stream'
                )
            }
            
            logger.info(f"Forwarding to ETL: {etl_upload_endpoint}")
            
            # Phase 13 / GAP-05: forward upload via shared HTTP client (retries, breaker, trace context).
            etl_response = get_default_client().post(
                etl_upload_endpoint,
                files=files,
                timeout=(5.0, 30.0),
                attach_internal_api_key=False,
            )
            
            logger.info(f"ETL Response: Status={etl_response.status_code}, Content-Type={etl_response.headers.get('Content-Type')}")
            
            # ========================================================
            # 5. ETL RESPONSE HANDLING: Defensive JSON parsing
            # ========================================================
            
            # Check if ETL request was successful
            if etl_response.status_code != 200:
                error_msg = f"ETL service returned {etl_response.status_code}"
                
                # Try to extract error message from response
                try:
                    content_type = etl_response.headers.get('Content-Type', '')
                    
                    if 'application/json' in content_type:
                        error_data = etl_response.json()
                        error_msg = error_data.get('message', error_msg)
                    else:
                        # Non-JSON response, log it
                        response_text = etl_response.text[:200]  # First 200 chars
                        logger.error(f"ETL non-JSON error response: {response_text}")
                        error_msg = f"ETL service error (Status: {etl_response.status_code})"
                
                except Exception as parse_error:
                    logger.error(f"Failed to parse ETL error response: {parse_error}")
                
                return Response(
                    {'success': False, 'message': error_msg},
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            # Parse successful ETL response
            etl_data = None
            file_path = ''
            
            try:
                content_type = etl_response.headers.get('Content-Type', '')
                
                if not content_type:
                    logger.warning("ETL response has no Content-Type header")
                
                if 'application/json' in content_type:
                    etl_data = etl_response.json()
                    logger.info(f"ETL JSON response: {etl_data}")
                    
                    # Extract file path from various possible response structures
                    if isinstance(etl_data, dict):
                        # Try different keys
                        file_path = (
                            etl_data.get('data', {}).get('saved_path', '') or
                            etl_data.get('saved_path', '') or
                            etl_data.get('path', '') or
                            etl_data.get('file_path', '')
                        )
                    
                    if not file_path:
                        logger.warning(f"No file path in ETL response: {etl_data}")
                        file_path = f"uploaded_{uploaded_file.name}"
                
                else:
                    # Non-JSON response - this is acceptable
                    logger.warning(f"ETL returned non-JSON response (Content-Type: {content_type})")
                    file_path = f"uploaded_{uploaded_file.name}"
            
            except json.JSONDecodeError as e:
                logger.error(f"ETL response is not valid JSON: {e}")
                logger.error(f"Response text: {etl_response.text[:500]}")
                # Don't fail - use default path
                file_path = f"uploaded_{uploaded_file.name}"
            
            except Exception as e:
                logger.error(f"Unexpected error parsing ETL response: {e}")
                file_path = f"uploaded_{uploaded_file.name}"
            
            # ========================================================
            # 6. DATABASE OPERATIONS: Replace or create
            # ========================================================
            
            # If replacing, cleanup old database
            if replace_mode:
                logger.info(f"Cleaning up existing database {existing_db.id}")
                try:
                    cleanup_database(existing_db)
                    existing_db.delete()
                    logger.info("Cleanup successful")
                except Exception as cleanup_error:
                    logger.error(f"Cleanup error: {cleanup_error}")
                    # Continue anyway - create new record
            
            # Create new database record
            try:
                configured_clickhouse_database = getattr(settings, 'CLICKHOUSE_DATABASE', 'etl')
                database = Database.objects.create(
                    manager=request.user,
                    filename=uploaded_file.name,
                    file_size=uploaded_file.size,
                    file_path=file_path,
                    clickhouse_database=configured_clickhouse_database,
                    etl_status='processing'
                )
                
                logger.info(f"Database record created: ID={database.id}, Status={database.etl_status}")
                
            except Exception as db_error:
                logger.error(f"Failed to create database record: {db_error}")
                return Response(
                    {'success': False, 'message': f'Database creation failed: {str(db_error)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # ========================================================
            # 7. SUCCESS RESPONSE
            # ========================================================
            
            response_data = {
                'success': True,
                'message': 'Database replaced successfully and ETL processing started' if replace_mode else 'Database uploaded successfully and ETL processing started',
                'data': {
                    'id': database.id,
                    'filename': database.filename,
                    'file_size': database.file_size,
                    'file_size_formatted': format_file_size(database.file_size),
                    'upload_date': database.upload_date.isoformat(),
                    'etl_status': database.etl_status,
                    'replaced': replace_mode
                }
            }
            
            logger.info(f"Upload successful: Database ID={database.id}")
            return Response(response_data, status=status.HTTP_201_CREATED)
        
        # ============================================================
        # 8. ERROR HANDLING: Network and unexpected errors
        # ============================================================
        
        except requests.exceptions.Timeout:
            logger.error(f"ETL service timeout after 30s: {etl_upload_endpoint}")
            return Response(
                {
                    'success': False,
                    'message': 'ETL service timeout. The file upload took too long. Please try again or use a smaller file.'
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"ETL service connection error: {e}")
            return Response(
                {
                    'success': False,
                    'message': 'ETL service is unavailable. Please ensure the ETL system is running and try again.'
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        except requests.exceptions.RequestException as e:
            logger.error(f"ETL service request error: {e}")
            return Response(
                {
                    'success': False,
                    'message': f'ETL service error: {str(e)}'
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        except Exception as e:
            logger.error(f"Unexpected error during upload: {e}", exc_info=True)
            return Response(
                {
                    'success': False,
                    'message': f'Upload failed: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DatabaseDetailView(APIView):
    """
    Handle database operations for the authenticated manager.
    GET: Retrieve manager's database information (with smart status checking)
    DELETE: Delete manager's database
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get manager's database information.
        Automatically checks ClickHouse and updates status if processing.
        """
        if request.user.role != 'manager':
            return Response(
                {'success': False, 'message': 'Only managers can access databases'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            database = Database.objects.get(manager=request.user)
            
            # ============================================================
            # SMART STATUS CHECK: Auto-update if processing
            # ============================================================
            if database.etl_status == 'processing':
                logger.info(f"Database {database.id} is processing - checking ClickHouse")
                
                # Check if ClickHouse table exists and has data
                updated = self._check_and_update_etl_status(database)
                
                if updated:
                    logger.info(f"Database {database.id} status updated to {database.etl_status}")
                    # Reload to get updated data
                    database.refresh_from_db()
            
            # ============================================================
            # Return current database information
            # ============================================================
            serializer = DatabaseSerializer(database)
            
            return Response({
                'success': True,
                'data': {
                    **serializer.data,
                    'file_size_formatted': format_file_size(database.file_size)
                }
            }, status=status.HTTP_200_OK)
            
        except Database.DoesNotExist:
            return Response(
                {'success': False, 'message': 'No database found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error retrieving database: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _check_and_update_etl_status(self, database):
        """
        Check ClickHouse for table existence and data.
        Update database status, row count, and column count if ready.
        
        Returns:
            bool: True if status was updated, False otherwise
        """
        try:
            clickhouse = ClickHouseClient()
            configured_ch_database = getattr(settings, 'CLICKHOUSE_DATABASE', 'etl')
            ch_database = (database.clickhouse_database or configured_ch_database).strip()
            if ch_database == 'default' and configured_ch_database and configured_ch_database != 'default':
                logger.info(
                    "Database %s had ClickHouse database='default'. Switching to configured database '%s'.",
                    database.id,
                    configured_ch_database,
                )
                ch_database = configured_ch_database
                database.clickhouse_database = configured_ch_database
                database.save(update_fields=['clickhouse_database'])
            
            # ========================================================
            # Step 1: Find the table name
            # ========================================================
            table_name = database.clickhouse_table_name
            
            if not table_name:
                # Try to find table by searching for tables containing filename
                logger.info("No table name set - searching ClickHouse for matching table")
                
                # Get all tables
                tables_result = clickhouse.get_all_tables(ch_database)
                
                if tables_result['success']:
                    if not tables_result['tables']:
                        logger.info(
                            "No tables found in ClickHouse database '%s' yet for database %s.",
                            ch_database,
                            database.id,
                        )
                        database.etl_message = (
                            f"Waiting for ETL output in ClickHouse database '{ch_database}'."
                        )
                        database.save(update_fields=['etl_message'])
                        return False

                    # Try to match by filename
                    import re
                    base_name = database.filename.rsplit('.', 1)[0].lower()
                    clean_base = re.sub(r'[^a-z0-9]', '', base_name)
                    
                    logger.info(f"Searching for tables matching: {clean_base}")
                    
                    # Look for tables that might match
                    for table in tables_result['tables']:
                        clean_table = re.sub(r'[^a-z0-9]', '', table.lower())
                        if clean_base in clean_table or clean_table in clean_base:
                            logger.info(f"Found matching table: {table}")
                            table_name = table
                            database.clickhouse_table_name = table
                            database.save()
                            break
                    
                    if not table_name:
                        logger.warning(f"No matching table found for {database.filename}")
                        logger.info(f"Available tables: {tables_result['tables']}")
                        database.etl_message = (
                            f"No matching ClickHouse table found yet in '{ch_database}'."
                        )
                        database.save(update_fields=['etl_message'])
                        return False
                else:
                    error_detail = tables_result.get('error', 'unknown_error')
                    logger.warning(
                        "Could not retrieve table list from ClickHouse database='%s' error=%s",
                        ch_database,
                        error_detail,
                    )
                    database.etl_message = (
                        f"Failed to retrieve ClickHouse table list: {error_detail}"
                    )
                    database.save(update_fields=['etl_message'])
                    return False
            
            # ========================================================
            # Step 2: Verify table exists
            # ========================================================
            logger.info(f"Checking if table exists: {ch_database}.{table_name}")
            
            exists_result = clickhouse.table_exists(ch_database, table_name)
            
            if not exists_result['success']:
                logger.warning(f"Failed to check table existence: {exists_result.get('error')}")
                return False
            
            if not exists_result['exists']:
                logger.info(f"Table {table_name} does not exist yet - still processing")
                return False
            
            logger.info(f"Table {table_name} exists - fetching metadata")
            
            # ========================================================
            # Step 3: Get row count
            # ========================================================
            count_result = clickhouse.get_table_count(ch_database, table_name)
            
            if not count_result['success']:
                logger.error(f"Failed to get row count: {count_result.get('error')}")
                database.etl_status = 'failed'
                database.etl_message = f"Failed to query table: {count_result.get('error')}"
                database.save()
                return True
            
            row_count = count_result['count']
            logger.info(f"Row count: {row_count}")
            
            # ========================================================
            # Step 4: Get column count and schema
            # ========================================================
            schema_result = clickhouse.get_table_schema(ch_database, table_name)
            
            if not schema_result['success']:
                logger.error(f"Failed to get schema: {schema_result.get('error')}")
                database.etl_status = 'failed'
                database.etl_message = f"Failed to get schema: {schema_result.get('error')}"
                database.save()
                return True
            
            schema = schema_result['schema']
            column_count = len(schema)
            logger.info(f"Column count: {column_count}")
            
            # Build column schema dictionary
            columns_schema = {col['name']: col['type'] for col in schema}
            
            # ========================================================
            # Step 5: Update database record with actual data
            # ========================================================
            database.row_count = row_count
            database.column_count = column_count
            database.columns_schema = columns_schema
            database.etl_status = 'completed'
            database.etl_message = f"Successfully loaded {row_count} rows, {column_count} columns"
            database.save()
            
            logger.info(f"Database {database.id} marked as completed: {row_count} rows, {column_count} columns")
            return True
            
        except Exception as e:
            logger.error(f"Error checking ETL status: {str(e)}", exc_info=True)
            # Don't update status on unexpected errors - might be temporary
            return False
    
    def delete(self, request):
        """Delete manager's database."""
        if request.user.role != 'manager':
            return Response(
                {'success': False, 'message': 'Only managers can delete databases'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            database = Database.objects.get(manager=request.user)
            
            # Cleanup ClickHouse and other resources
            cleanup_results = cleanup_database(database)
            
            # Delete database record
            database.delete()
            
            logger.info(f"Database deleted for manager {request.user.email}")
            
            return Response({
                'success': True,
                'message': 'Database deleted successfully',
                'cleanup_results': cleanup_results
            }, status=status.HTTP_200_OK)
            
        except Database.DoesNotExist:
            return Response(
                {'success': False, 'message': 'No database found to delete'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error deleting database: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DatabasePreviewView(APIView):
    """
    Get preview data from the manager's database.
    GET: Returns first 5 rows and schema information
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get database preview."""
        if request.user.role != 'manager':
            return Response(
                {'success': False, 'message': 'Only managers can preview databases'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            database = Database.objects.get(manager=request.user)
            
            # Check if ETL processing is complete
            if database.etl_status != 'completed':
                return Response({
                    'success': False,
                    'message': f'Database is still processing. Status: {database.etl_status}',
                    'etl_status': database.etl_status
                }, status=status.HTTP_202_ACCEPTED)
            
            # Get data from ClickHouse
            clickhouse = ClickHouseClient()
            
            # Get schema
            schema_result = clickhouse.get_table_schema(
                database.clickhouse_database,
                database.clickhouse_table_name
            )
            
            if not schema_result['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to retrieve schema from ClickHouse',
                    'error': schema_result.get('error')
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Get preview rows
            preview_result = clickhouse.get_table_preview(
                database.clickhouse_database,
                database.clickhouse_table_name,
                limit=5
            )
            
            if not preview_result['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to retrieve preview data from ClickHouse',
                    'error': preview_result.get('error')
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Format response
            columns = [col['name'] for col in schema_result['schema']]
            column_types = {col['name']: col['type'] for col in schema_result['schema']}
            
            response_data = {
                'success': True,
                'data': {
                    'columns': columns,
                    'column_types': column_types,
                    'rows': preview_result['rows'],
                    'total_rows': database.row_count,
                    'total_columns': database.column_count
                }
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Database.DoesNotExist:
            return Response(
                {'success': False, 'message': 'No database found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error getting database preview: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DatabaseStatusView(APIView):
    """
    Update database status (called by ETL service after processing).
    PUT: Update ETL status and metadata
    """
    permission_classes = [IsAuthenticated]
    
    def put(self, request, database_id):
        """Update database ETL status and metadata."""
        try:
            database = get_object_or_404(Database, id=database_id)
            
            # Update ETL status
            etl_status = request.data.get('etl_status')
            if etl_status:
                database.etl_status = etl_status
            
            # Update metadata if provided
            if 'row_count' in request.data:
                database.row_count = request.data['row_count']
            
            if 'column_count' in request.data:
                database.column_count = request.data['column_count']
            
            if 'columns_schema' in request.data:
                database.columns_schema = request.data['columns_schema']
            
            if 'clickhouse_table_name' in request.data:
                database.clickhouse_table_name = request.data['clickhouse_table_name']
            
            if 'clickhouse_database' in request.data:
                database.clickhouse_database = request.data['clickhouse_database']
            
            if 'etl_message' in request.data:
                database.etl_message = request.data['etl_message']
            
            database.save()
            
            logger.info(f"Database {database_id} status updated to {etl_status}")
            
            return Response({
                'success': True,
                'message': 'Database status updated successfully'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error updating database status: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
