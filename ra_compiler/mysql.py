# ra_compiler/mysql.py
'''Set up and tear down for a SQL database connection.'''

import importlib
import os
from contextlib import suppress
from dotenv import load_dotenv
import mysql.connector
from .utils import print_error, clean_exit

CONN = None
DB_BACKEND = "MySQL"
DB_ERROR_TYPES = (mysql.connector.Error,)

SUPPORTED_BACKENDS = {
    "mysql": "MySQL",
    "mariadb": "MySQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "pgsql": "PostgreSQL",
    "psql": "PostgreSQL",
    "posgresql": "PostgreSQL",
}

def setup_mysql(config_file=".env"):
    """Initialize the configured SQL database connection."""
    global CONN

    try:
        print(f"Using configuration file: {config_file}")
        loaded = load_dotenv(dotenv_path=config_file)

        if not loaded:
            raise FileNotFoundError

        CONN = connect()

        print(f"{DB_BACKEND} Connection Successfully Complete")

    except FileNotFoundError as e:
        print_error(f"Error in loading config file {e.filename}", e)
        clean_exit(1)
    except DB_ERROR_TYPES as e:
        print_error(f"Error creating cursor: {e}", e)
        clean_exit(1)

def connect():
    """Establish a connection to the configured SQL database."""
    global DB_BACKEND

    # make sure that the required fields are in the config file
    required_vars = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
    for var in required_vars:
        if os.getenv(var) is None:
            print_error(f"Missing required database config variable: {var}", "DBConfigError")
            clean_exit(1)

    DB_BACKEND = get_configured_backend()

    if DB_BACKEND == "PostgreSQL":
        return connect_postgresql()

    return connect_mysql()

def get_configured_backend():
    """Return the configured database backend, defaulting to MySQL."""

    configured_db = os.getenv("DB", "MySQL").strip().lower().replace("-", "")
    backend = SUPPORTED_BACKENDS.get(configured_db)

    if backend is None:
        supported = ", ".join(sorted(set(SUPPORTED_BACKENDS.values())))
        print_error(
            f"Unsupported DB value '{os.getenv('DB')}'. Supported values: {supported}",
            "DBConfigError"
        )
        clean_exit(1)

    return backend

def connect_mysql():
    """Establish a connection to the MySQL database."""

    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            autocommit=True
        )

    except mysql.connector.Error as e:
        print_error(f"Database connection failed: {e}", e)
        clean_exit(1)

def connect_postgresql():
    """Establish a connection to the PostgreSQL database."""
    global DB_ERROR_TYPES

    try:
        psycopg2 = importlib.import_module("psycopg2")
    except ImportError as e:
        print_error(
            "PostgreSQL support requires psycopg2-binary. "
            "Install dependencies again or run: pip install psycopg2-binary",
            e
        )
        clean_exit(1)

    DB_ERROR_TYPES = (mysql.connector.Error, psycopg2.Error)

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            dbname=os.getenv("DB_NAME")
        )
        conn.autocommit = True
        return conn

    except psycopg2.Error as e:
        print_error(f"Database connection failed: {e}", e)
        clean_exit(1)

def close_mysql():
    """Closes the SQL database connection."""

    if CONN:
        with suppress(Exception):
            CONN.close()

def run_query(sql):
    """Run a SQL query and return the results."""

    # if there is no current connection, set one up
    if CONN is None:
        setup_mysql()

    try:
        with CONN.cursor() as cursor:
            cursor.execute(sql)
            if cursor.description is None:
                return [], []

            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

            return columns, rows

    except DB_ERROR_TYPES as e:
        handle_sql_error(e, sql)
        return None

def handle_sql_error(e, sql):
    """Handle SQL database error codes."""

    if getattr(e, "errno", None) == 1146 or getattr(e, "pgcode", None) == "42P01":
        print_error(f"SQL error: Table does not exist. {sql} ", e)
    else:
        print_error(f"SQL execution error: {e}", e)
        clean_exit(1)

def format_identifier(identifier):
    """Return an identifier formatted for the configured SQL backend."""

    if DB_BACKEND == "PostgreSQL":
        return identifier

    return f"`{identifier.replace('`', '``')}`"

def quote_sql_literal(value):
    """Return a SQL string literal."""

    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"

def list_relations_query():
    """Return the SQL query that lists visible database relations by category."""

    if DB_BACKEND == "PostgreSQL":
        return (
            "SELECT category, relation_name "
            "FROM ("
            "    SELECT CASE "
            "        WHEN c.relpersistence = 't' THEN 'temporary_tables' "
            "        WHEN c.relkind IN ('r', 'p') THEN 'tables' "
            "        WHEN c.relkind = 'v' THEN 'views' "
            "        WHEN c.relkind = 'm' THEN 'materialized_views' "
            "    END AS category, "
            "    c.relname AS relation_name, "
            "    CASE "
            "        WHEN c.relkind IN ('r', 'p') AND c.relpersistence != 't' THEN 1 "
            "        WHEN c.relpersistence = 't' THEN 2 "
            "        WHEN c.relkind = 'v' THEN 3 "
            "        WHEN c.relkind = 'm' THEN 4 "
            "    END AS category_order "
            "    FROM pg_catalog.pg_class c "
            "    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "    WHERE c.relkind IN ('r', 'p', 'v', 'm') "
            "    AND pg_catalog.pg_table_is_visible(c.oid) "
            "    AND ("
            "        c.relpersistence = 't' "
            "        OR ("
            "            n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "            AND n.nspname NOT LIKE 'pg_toast%'"
            "        )"
            "    )"
            ") relations "
            "WHERE category IS NOT NULL "
            "ORDER BY category_order, relation_name;"
        )

    return (
        "SELECT CASE "
        "    WHEN table_type = 'BASE TABLE' THEN 'tables' "
        "    WHEN table_type = 'VIEW' THEN 'views' "
        "END AS category, table_name AS relation_name "
        "FROM information_schema.tables "
        "WHERE table_schema = DATABASE() "
        "AND table_type IN ('BASE TABLE', 'VIEW') "
        "ORDER BY CASE WHEN table_type = 'BASE TABLE' THEN 1 ELSE 2 END, table_name;"
    )


def list_tables_query():
    """Return the SQL query that lists available database relations."""

    return list_relations_query()

def table_exists_query(table_name):
    """Return the SQL query that checks whether a table exists."""

    table = quote_sql_literal(table_name)
    if DB_BACKEND == "PostgreSQL":
        return (
            "SELECT c.relname "
            "FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p', 'v', 'm') "
            "AND pg_catalog.pg_table_is_visible(c.oid) "
            "AND ("
            "    c.relpersistence = 't' "
            "    OR ("
            "        n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "        AND n.nspname NOT LIKE 'pg_toast%'"
            "    )"
            ") "
            f"AND lower(c.relname) = lower({table}) "
            "LIMIT 1;"
        )

    return f"SHOW TABLES LIKE {table};"
