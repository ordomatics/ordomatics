import datetime
import decimal
import logging

_logger = logging.getLogger(__name__)


def _to_json_safe(value):
    """Convert pyodbc-returned types to JSON-serializable Python primitives."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


class MssqlClient:
    """
    pyodbc-based SQL Server client.

    Reads connection credentials fresh from ir.config_parameter on each
    instantiation so credential changes take effect without Odoo restart.

    Required system parameters (Settings > Technical > System Parameters):
        mssql.host      — SQL Server hostname or IP
        mssql.port      — Port (default: 1433)
        mssql.database  — Database name
        mssql.user      — SQL Server login
        mssql.password  — SQL Server password
    """

    def __init__(self, env):
        try:
            import pyodbc  # noqa: F401 — validate at instantiation time

            self._pyodbc = pyodbc
        except ImportError as e:
            raise ImportError(
                "pyodbc is required for MSSQL integration. "
                "Install it with: pip install pyodbc"
            ) from e

        param = env["ir.config_parameter"].sudo().get_param
        host = param("mssql.host", "")
        port = param("mssql.port", "1433")
        database = param("mssql.database", "")
        user = param("mssql.user", "")
        password = param("mssql.password", "")

        if not all([host, database, user, password]):
            raise ValueError(
                "MSSQL connection not configured. Set system parameters: "
                "mssql.host, mssql.database, mssql.user, mssql.password"
            )

        self._conn_str = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={host},{port};"
            f"DATABASE={database};"
            f"UID={user};PWD={password};"
            "TrustServerCertificate=yes;"
            "Connection Timeout=10"
        )

    def query(self, sql: str, params: tuple = ()) -> list:
        """Execute a SELECT and return list of dicts. Always use ? placeholders."""
        with self._pyodbc.connect(self._conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            cols = [col[0] for col in cursor.description]
            return [
                {col: _to_json_safe(val) for col, val in zip(cols, row)}
                for row in cursor.fetchall()
            ]

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Execute INSERT/UPDATE/DELETE. Returns rowcount."""
        with self._pyodbc.connect(self._conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
