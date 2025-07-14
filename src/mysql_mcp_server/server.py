import asyncio
import logging
import os
import sys
import re
import socket
import time
from contextlib import contextmanager
from mysql.connector import connect, Error
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent
from pydantic import AnyUrl, parse_obj_as
from dotenv import load_dotenv
from typing import List, Optional, Tuple, Any, Dict, Union
from mysql.connector.pooling import MySQLConnectionPool
import mysql.connector
import subprocess

# Load environment variables from .env if present
load_dotenv()

try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    SSHTunnelForwarder = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=os.path.join(os.path.dirname(__file__), 'mysql_mcp_server.log'),   # Log to this file in the same directory as server.py
    filemode='a'                      # Append to the log file (use 'w' to overwrite each run)
)
logger = logging.getLogger("mysql_mcp_server")

# Global variables
ssh_tunnel = None
db_config = None

def find_free_port(start_port: int = 3306, max_attempts: int = 100) -> int:
    """Find a free local port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"Could not find a free port after {max_attempts} attempts")

@contextmanager
def maybe_ssh_tunnel():
    global ssh_tunnel

    use_ssh = os.getenv("MYSQL_SSH_ENABLE", "false").lower() == "true"
    logger.info(f"maybe_ssh_tunnel: use_ssh={use_ssh}")
    if not use_ssh:
        logger.info("maybe_ssh_tunnel: Not using SSH tunnel, connecting directly.")
        logger.info(f"maybe_ssh_tunnel: host={os.getenv('MYSQL_HOST', 'localhost')}, port={os.getenv('MYSQL_PORT', '3306')}")
        yield os.getenv("MYSQL_HOST", "localhost"), int(os.getenv("MYSQL_PORT", "3306"))
        return

    ssh_host = os.getenv("MYSQL_SSH_HOST")
    ssh_port = int(os.getenv("MYSQL_SSH_PORT", "22"))
    ssh_user = os.getenv("MYSQL_SSH_USER")
    ssh_key = os.getenv("MYSQL_SSH_KEY_PATH")
    remote_host = os.getenv("MYSQL_SSH_REMOTE_HOST")
    remote_port = int(os.getenv("MYSQL_SSH_REMOTE_PORT", "3306"))
    local_port = int(os.getenv("MYSQL_LOCAL_PORT", "3330"))

    # Mask SSH key path in logs
    safe_ssh_key = os.path.basename(ssh_key) if ssh_key else None
    logger.info(f"maybe_ssh_tunnel: SSH config: host={ssh_host}, port={ssh_port}, user={ssh_user}, key={safe_ssh_key}, remote_host={remote_host}, remote_port={remote_port}, local_port={local_port}")

    # Build the SSH command
    ssh_cmd = [
        'ssh',
        '-i', ssh_key,
        '-N',
        '-L', f'{local_port}:{remote_host}:{remote_port}',
        f'{ssh_user}@{ssh_host}',
        '-p', str(ssh_port)
    ]
    logger.info(f"maybe_ssh_tunnel: Starting SSH tunnel with command: {' '.join(ssh_cmd)}")
    try:
        ssh_proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        import time
        time.sleep(1)  # Wait for tunnel to be ready
        logger.info(f"maybe_ssh_tunnel: SSH tunnel established: 127.0.0.1:{local_port} -> {remote_host}:{remote_port} via {ssh_host}")
        # Log subprocess output (non-blocking)
        try:
            out, err = ssh_proc.communicate(timeout=0.1)
            if out:
                logger.info(f"maybe_ssh_tunnel: SSH tunnel stdout: {out.decode(errors='ignore')}")
            if err:
                logger.info(f"maybe_ssh_tunnel: SSH tunnel stderr: {err.decode(errors='ignore')}")
        except Exception:
            pass
        yield "127.0.0.1", local_port
    except Exception as e:
        logger.error(f"maybe_ssh_tunnel: Error starting SSH tunnel: {e}", exc_info=True)
        raise
    finally:
        logger.info("maybe_ssh_tunnel: Terminating SSH tunnel process.")
        try:
            ssh_proc.terminate()
            ssh_proc.wait(timeout=5)
            logger.info("maybe_ssh_tunnel: SSH tunnel process terminated.")
        except Exception as e:
            logger.error(f"maybe_ssh_tunnel: Error terminating SSH tunnel: {e}")

def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
        "collation": os.getenv("MYSQL_COLLATION", "utf8mb4_unicode_ci"),
        "autocommit": True,
        "sql_mode": os.getenv("MYSQL_SQL_MODE", "TRADITIONAL"),
        "connect_timeout": 10,
        "pool_size": 5,
        "pool_reset_session": True,
    }
    # Remove None values
    config = {k: v for k, v in config.items() if v is not None}
    # Mask password for logging
    safe_config = config.copy()
    if 'password' in safe_config:
        safe_config['password'] = '***'
    logger.info(f"get_db_config: config={safe_config}")
    
    if not all([config.get("user"), config.get("password"), config.get("database")]):
        logger.error("Missing required database configuration. Please check environment variables:")
        logger.error("MYSQL_USER, MYSQL_PASSWORD, and MYSQL_DATABASE are required")
        raise ValueError("Missing required database configuration")
    
    return config

def get_database_connection(host: str, port: int) -> Any:
    logger.info(f"get_database_connection: Connecting to {host}:{port}")
    config = get_db_config()
    config["host"] = host
    config["port"] = port
    config["auth_plugin"] = "mysql_native_password"
    logger.info(f"get_database_connection: config={config}")
    # Remove pool-specific settings for single connection
    pool_config = {k: v for k, v in config.items() if k not in ['pool_size', 'pool_reset_session']}
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info(f"get_database_connection: Attempt {attempt+1} to connect to MySQL")
            connection = mysql.connector.connect(**pool_config)
            logger.info("get_database_connection: Database connection established successfully")
            return connection
        except mysql.connector.Error as e:
            logger.warning(f"get_database_connection: Database connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                logger.error(f"get_database_connection: All connection attempts failed.")
                raise
    raise RuntimeError("Failed to establish database connection after all retries")

def validate_sql_query(query: str) -> tuple[bool, str]:
    """
    Validate SQL query for security restrictions.
    Returns (is_allowed, reason) tuple.
    """
    # Normalize query for easier parsing
    query_upper = query.strip().upper()
    
    # Define restricted commands (case-insensitive)
    restricted_commands = [
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'CREATE', 'ALTER', 'TRUNCATE',
        'GRANT', 'REVOKE', 'FLUSH', 'RESET', 'KILL', 'SHUTDOWN', 'RESTART'
    ]
    
    # Check for restricted commands
    for command in restricted_commands:
        # Use word boundaries to avoid false positives
        pattern = r'\b' + re.escape(command) + r'\b'
        if re.search(pattern, query_upper):
            return False, f"Command '{command}' is not allowed for security reasons"
    
    # Additional security checks
    if ';' in query and query.count(';') > 1:
        return False, "Multiple SQL statements are not allowed"
    
    if '--' in query or '/*' in query:
        return False, "SQL comments are not allowed"
    
    return True, "Query is allowed"

# Initialize server
app = Server("mysql_mcp_server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    logger.info("Listing tools...")
    return [
        Tool(
            name="execute_sql",
            description="Execute an SQL query on the MySQL server",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The SQL query to execute"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_schema_info",
            description="Get comprehensive schema information including table descriptions and relationships",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Optional: Specific table name to get info for. If not provided, returns overview of all tables."
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_table_sample",
            description="Get a sample of data from a specific table with column descriptions",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": "Name of the table to sample"},
                    "limit": {"type": "integer", "description": "Number of rows to return (default: 5, max: 20)"}
                },
                "required": ["table_name"]
            }
        ),
        Tool(
            name="get_reference_doc",
            description="Get the MCP use case and query reference documentation.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"call_tool: name={name}, arguments={arguments}")
    try:
        with maybe_ssh_tunnel() as (host, port):
            logger.info(f"call_tool: Tunnel established, host={host}, port={port}")
            if name == "execute_sql":
                logger.info("call_tool: Executing execute_sql_tool")
                return await execute_sql_tool(host, port, arguments)
            elif name == "get_schema_info":
                logger.info("call_tool: Executing get_schema_info_tool")
                return await get_schema_info_tool(host, port, arguments)
            elif name == "get_table_sample":
                logger.info("call_tool: Executing get_table_sample_tool")
                return await get_table_sample_tool(host, port, arguments)
            elif name == "get_reference_doc":
                logger.info("call_tool: Reading MCP_USECASES.md")
                try:
                    with open("MCP_USECASES.md", "r") as f:
                        doc = f.read()
                    return [TextContent(type="text", text=doc)]
                except Exception as e:
                    logger.error(f"Failed to read MCP_USECASES.md: {e}")
                    return [TextContent(type="text", text="Reference documentation not available.")]
            else:
                logger.error(f"call_tool: Unknown tool: {name}")
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.error(f"Tool execution failed: {e}", exc_info=True)
        return [TextContent(type="text", text="An error occurred while opening tunnels.")]

async def execute_sql_tool(host: str, port: int, arguments: dict) -> list[TextContent]:
    logger.info(f"execute_sql_tool: host={host}, port={port}, arguments={arguments}")
    query = arguments.get("query", "").strip()
    if not query:
        return [TextContent(type="text", text="No SQL query provided")]
    
    # Validate query
    is_allowed, reason = validate_sql_query(query)
    if not is_allowed:
        return [TextContent(type="text", text=f"Query not allowed: {reason}")]
    
    try:
        connection = get_database_connection(host, port)
        cursor = connection.cursor(dictionary=True)
        logger.info(f"execute_sql_tool: About to execute query: {query}")
        cursor.execute(query)
        logger.info("execute_sql_tool: Query executed successfully, about to fetch results.")
        
        if cursor.description:
            results = cursor.fetchall()
            logger.info(f"execute_sql_tool: Results fetched, {len(results)} rows.")
            if results:
                # Format results nicely
                formatted_results = []
                for row in results:
                    if isinstance(row, dict):
                        formatted_results.append(row)
                    else:
                        # Convert tuple to dict using column names
                        columns = [desc[0] for desc in cursor.description]
                        formatted_results.append(dict(zip(columns, row)))
                logger.info("execute_sql_tool: Returning formatted results.")
                return [TextContent(type="text", text=f"Query executed successfully. Results:\n{formatted_results}")]
            else:
                logger.info("execute_sql_tool: Query executed, no results returned.")
                return [TextContent(type="text", text="Query executed successfully. No results returned.")]
        else:
            logger.info(f"execute_sql_tool: Query executed, no result set. Rows affected: {cursor.rowcount}")
            return [TextContent(type="text", text=f"Query executed successfully. Rows affected: {cursor.rowcount}")]
    
    except mysql.connector.Error as e:
        logger.error(f"execute_sql_tool: SQL execution error: {e}")
        return [TextContent(type="text", text=f"SQL error: {e}")]
    except Exception as e:
        logger.error(f"execute_sql_tool: Unexpected error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Unexpected error: {e}")]
    finally:
        try:
            cursor.close()
            connection.close()
        except Exception as e:
            logger.error(f"execute_sql_tool: Error closing cursor/connection: {e}")

async def get_schema_info_tool(host: str, port: int, arguments: dict) -> list[TextContent]:
    """Get database schema information."""
    logger.info(f"get_schema_info_tool: host={host}, port={port}, arguments={arguments}")
    table_name = arguments.get("table_name")
    
    try:
        connection = get_database_connection(host, port)
        cursor = connection.cursor(dictionary=True)
        
        if table_name:
            # Get schema for a specific table
            cursor.execute(
                """
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (table_name,)
            )
            columns = cursor.fetchall()
            result = f"Table: {table_name}\nColumns:\n"
            for col in columns:
                field = col['COLUMN_NAME']
                type_name = col['DATA_TYPE']
                null_val = col['IS_NULLABLE']
                default_val = col['COLUMN_DEFAULT']
                comment = col['COLUMN_COMMENT']
                result += f"  - {field}: {type_name} {'NOT NULL' if null_val == 'NO' else 'NULL'}"
                if default_val is not None:
                    result += f" DEFAULT {default_val}"
                if comment:
                    result += f"  # {comment}"
                result += "\n"
            return [TextContent(type="text", text=result)]
        else:
            # Get schema for all tables
            cursor.execute(
                """
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """
            )
            columns = cursor.fetchall()
            result = "Database Schema (all tables):\n"
            last_table = None
            for col in columns:
                tname = col['TABLE_NAME']
                field = col['COLUMN_NAME']
                type_name = col['DATA_TYPE']
                null_val = col['IS_NULLABLE']
                default_val = col['COLUMN_DEFAULT']
                comment = col['COLUMN_COMMENT']
                if tname != last_table:
                    result += f"\nTable: {tname}\nColumns:\n"
                    last_table = tname
                result += f"  - {field}: {type_name} {'NOT NULL' if null_val == 'NO' else 'NULL'}"
                if default_val is not None:
                    result += f" DEFAULT {default_val}"
                if comment:
                    result += f"  # {comment}"
                result += "\n"
            return [TextContent(type="text", text=result)]
    
    except mysql.connector.Error as e:
        logger.error(f"Schema info error: {e}")
        return [TextContent(type="text", text=f"Schema error: {e}")]
    finally:
        try:
            cursor.close()
            connection.close()
        except:
            pass

async def get_table_sample_tool(host: str, port: int, arguments: dict) -> list[TextContent]:
    """Get sample data from a table."""
    logger.info(f"get_table_sample_tool: host={host}, port={port}, arguments={arguments}")
    table_name = arguments.get("table_name")
    limit = min(arguments.get("limit", 5), 20)  # Max 20 rows
    
    if not table_name:
        return [TextContent(type="text", text="Table name is required")]
    
    try:
        connection = get_database_connection(host, port)
        cursor = connection.cursor(dictionary=True)
        
        # Get table structure
        cursor.execute(f"DESCRIBE `{table_name}`")
        columns = cursor.fetchall()
        
        # Get sample data
        cursor.execute(f"SELECT * FROM `{table_name}` LIMIT {limit}")
        rows = cursor.fetchall()
        
        result = f"Table: {table_name}\n\n"
        result += "Columns:\n"
        for col in columns:
            if isinstance(col, dict):
                field = col.get('Field', col.get('field', ''))
                type_name = col.get('Type', col.get('type', ''))
            else:
                field = col[0] if len(col) > 0 else ''
                type_name = col[1] if len(col) > 1 else ''
            result += f"  - {field}: {type_name}\n"
        
        result += f"\nSample Data ({len(rows)} rows):\n"
        for i, row in enumerate(rows, 1):
            result += f"\nRow {i}:\n"
            if isinstance(row, dict):
                for key, value in row.items():
                    result += f"  {key}: {value}\n"
            else:
                # Handle tuple result
                column_names = [desc[0] for desc in cursor.description] if cursor.description else []
                for j, value in enumerate(row):
                    col_name = column_names[j] if j < len(column_names) else f"col_{j}"
                    result += f"  {col_name}: {value}\n"
        
        return [TextContent(type="text", text=result)]
    
    except mysql.connector.Error as e:
        logger.error(f"Table sample error: {e}")
        return [TextContent(type="text", text=f"Table sample error: {e}")]
    finally:
        try:
            cursor.close()
            connection.close()
        except:
            pass

async def main():
    """Main entry point."""
    logger.info("Starting MySQL MCP server...")
    
    try:
        # Test configuration early
        config = get_db_config()
        logger.info(f"Database config: {config['host'] if 'host' in config else 'SSH tunnel'}/{config['database']} as {config['user']}")
        
        from mcp.server.stdio import stdio_server
        
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server startup failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
