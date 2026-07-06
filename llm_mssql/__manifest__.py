{
    "name": "MSSQL MCP",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Generic SQL Server (MSSQL) integration via MCP at /mcp/mssql",
    "license": "LGPL-3",
    "depends": ["llm_mcp_server"],
    "external_dependencies": {"python": ["pyodbc"]},
    "data": ["data/llm_mcp_server_config.xml", "data/ir_config_parameter.xml"],
    "installable": True,
    "auto_install": False,
}
