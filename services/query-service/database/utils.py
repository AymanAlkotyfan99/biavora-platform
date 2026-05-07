"""
Utility functions for database operations including ClickHouse cleanup.
"""
import logging

import requests
from bi_platform_shared.http import HttpClientError, get_default_client
from django.conf import settings

logger = logging.getLogger(__name__)


class ClickHouseClient:
    """Client for interacting with ClickHouse database."""
    
    def __init__(self):
        self.host = getattr(settings, 'CLICKHOUSE_HOST', 'localhost')
        self.port = getattr(settings, 'CLICKHOUSE_PORT', '8123')
        self.user = getattr(settings, 'CLICKHOUSE_USER', 'etl_user')
        self.password = getattr(settings, 'CLICKHOUSE_PASSWORD', 'etl_pass123')
        self.base_url = f'http://{self.host}:{self.port}'
    
    def execute_query(self, query):
        """Execute a query on ClickHouse."""
        try:
            params = {'query': query}
            if self.user:
                params['user'] = self.user
            if self.password:
                params['password'] = self.password
            
            try:
                response = get_default_client().post(
                    self.base_url,
                    params=params,
                    timeout=(3.0, 10.0),
                    attach_internal_api_key=False,
                )
            except HttpClientError as exc:
                logger.error("ClickHouse query error: %s", exc)
                return {'success': False, 'error': str(exc)}
            response.raise_for_status()
            return {'success': True, 'data': response.text}
        except Exception as e:
            logger.error(f"ClickHouse query error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def drop_table(self, database, table_name):
        """Drop a table from ClickHouse."""
        query = f"DROP TABLE IF EXISTS {database}.{table_name}"
        logger.info(f"Dropping ClickHouse table: {database}.{table_name}")
        result = self.execute_query(query)
        if result['success']:
            logger.info(f"Successfully dropped table: {database}.{table_name}")
        else:
            logger.error(f"Failed to drop table: {result.get('error')}")
        return result
    
    def get_table_preview(self, database, table_name, limit=5):
        """Get preview data from a ClickHouse table."""
        query = f"SELECT * FROM {database}.{table_name} LIMIT {limit} FORMAT JSONEachRow"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                rows = [json.loads(line) for line in result['data'].strip().split('\n') if line]
                return {'success': True, 'rows': rows}
            except Exception as e:
                logger.error(f"Error parsing ClickHouse response: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def get_table_schema(self, database, table_name):
        """Get schema information for a table."""
        query = f"DESCRIBE TABLE {database}.{table_name} FORMAT JSONEachRow"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                schema = [json.loads(line) for line in result['data'].strip().split('\n') if line]
                return {'success': True, 'schema': schema}
            except Exception as e:
                logger.error(f"Error parsing schema: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def get_table_count(self, database, table_name):
        """Get row count for a table."""
        query = f"SELECT COUNT(*) as count FROM {database}.{table_name} FORMAT JSONEachRow"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                data = json.loads(result['data'].strip())
                return {'success': True, 'count': data.get('count', 0)}
            except Exception as e:
                logger.error(f"Error getting table count: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def table_exists(self, database, table_name):
        """Check if a table exists in ClickHouse."""
        query = f"SELECT count() FROM system.tables WHERE database = '{database}' AND name = '{table_name}'"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                count = int(result['data'].strip())
                return {'success': True, 'exists': count == 1}
            except Exception as e:
                logger.error(f"Error checking table existence: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def get_all_tables(self, database='default'):
        """Get list of all tables in a database."""
        query = f"SELECT name FROM system.tables WHERE database = '{database}' FORMAT JSONEachRow"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                tables = [json.loads(line)['name'] for line in result['data'].strip().split('\n') if line]
                return {'success': True, 'tables': tables}
            except Exception as e:
                logger.error(f"Error getting tables: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result


def format_file_size(size_bytes):
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def cleanup_database(database_instance):
    """
    Cleanup all resources associated with a database instance.
    This includes ClickHouse tables and any other related data.
    """
    cleanup_results = {
        'clickhouse_dropped': False,
        'errors': []
    }
    
    # Drop ClickHouse table if exists
    if database_instance.clickhouse_table_name:
        clickhouse = ClickHouseClient()
        result = clickhouse.drop_table(
            database_instance.clickhouse_database,
            database_instance.clickhouse_table_name
        )
        cleanup_results['clickhouse_dropped'] = result['success']
        if not result['success']:
            cleanup_results['errors'].append(f"ClickHouse: {result.get('error')}")
    
    return cleanup_results

