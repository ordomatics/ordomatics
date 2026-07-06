"""
MSSQL MCP Controller

Registers /mcp/mssql — a dedicated MCP endpoint for SQL Server tools.
Inherits the full MCP protocol from llm_mcp_server's MCPController and
overrides only tool discovery and execution to scope them to mssql_* tools.

Server identity (name, version, protocol) comes from the llm.mcp.server.config
record with endpoint_path='/mcp/mssql', selected automatically by the base
class via longest-prefix matching on the request path.
"""

import json
import logging
from http import HTTPStatus

from mcp.types import ListToolsResult, Tool

from odoo import http
from odoo.http import request

from odoo.addons.llm_mcp_server.controllers.mcp_controller import (
    MCPController,
    requires_bearer_auth,
)

_logger = logging.getLogger(__name__)

CONTENT_TYPE_JSON = "application/json"


class MssqlMCPController(MCPController):
    """
    MCP endpoint for SQL Server at /mcp/mssql.

    Reuses the full MCP protocol (session management, auth, protocol negotiation)
    from MCPController. Only tools/list and tools/call are overridden to filter
    by path: /mcp/mssql serves mssql_* tools only; /mcp excludes them.
    """

    @http.route(
        "/mcp/mssql",
        type="mcp_json",
        auth="public",
        methods=["POST"],
        csrf=False,
        cors="*",
    )
    def mcp_mssql_endpoint(self, **params):
        """MCP endpoint for MSSQL tools."""
        return self.mcp_endpoint(**params)

    @http.route(
        "/mcp/mssql",
        type="http",
        auth="bearer",
        methods=["DELETE"],
        csrf=False,
    )
    def mcp_mssql_delete_session(self):
        """Session termination for /mcp/mssql."""
        return self._handle_delete_session()

    @http.route(
        "/mcp/mssql/health",
        type="http",
        auth="public",
        methods=["GET", "POST"],
    )
    def mssql_health_check(self):
        """Health check — reads name/version from the /mcp/mssql config record."""
        config = request.env["llm.mcp.server.config"].sudo().get_active_config()
        data = config.get_health_status_data()
        return http.Response(
            json.dumps(data),
            headers={"Content-Type": CONTENT_TYPE_JSON},
            status=HTTPStatus.OK,
        )

    # ─── Scope tools by path ──────────────────────────────────────────────────

    def _is_mssql_path(self):
        return request.httprequest.path.startswith("/mcp/mssql")

    @requires_bearer_auth
    def _mcp_tools_list(self, params, request_id):
        if self._is_mssql_path():
            domain = [("active", "=", True), ("name", "like", "mssql_")]
        else:
            domain = [("active", "=", True), ("name", "not like", "mssql_")]
        active_tools = request.env["llm.tool"].sudo().search(domain)
        mcp_tools = [Tool(**tool.get_tool_definition()) for tool in active_tools]
        return ListToolsResult(tools=mcp_tools)

    @requires_bearer_auth
    def _mcp_tools_call(self, params, request_id):
        if not self._is_mssql_path():
            return super()._mcp_tools_call(params, request_id)
        tool_name = (params or {}).get("name", "")
        if not tool_name.startswith("mssql_"):
            from odoo.addons.llm_mcp_server.mcp_json_dispatcher import MCPInvalidParamsError  # noqa: PLC0415

            raise MCPInvalidParamsError(
                f"Tool '{tool_name}' is not available on /mcp/mssql. "
                "This endpoint only serves mssql_* tools."
            )

        session_id = request.httprequest.headers.get("mcp-session-id")
        if session_id and request.env.user and not request.env.user._is_public():
            session = request.env["llm.mcp.session"].get_session(session_id)
            if session and not session.user_id:
                session.user_id = request.env.user.id

        return request.env["llm.tool"].execute_mcp_tool(params=params)
