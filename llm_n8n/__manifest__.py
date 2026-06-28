{
    "name": "n8n LLM Integration",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Gives Odoo LLM agents the ability to trigger n8n workflows as a tool",
    "license": "LGPL-3",
    "depends": ["llm_tool", "llm_assistant", "n8n_connector"],
    "data": ["data/llm_n8n_data.xml"],
    "installable": True,
    "auto_install": False,
}
