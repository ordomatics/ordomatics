from typing import Optional

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool


class LlmN8nTool(models.AbstractModel):
    _name = "llm.n8n.tool"
    _description = "n8n Workflow Tool"

    @llm_tool(open_world_hint=True, idempotent_hint=False)
    def odoo_n8n_trigger(
        self,
        workflow_name: str,
        payload: Optional[dict] = None,
    ) -> dict:
        """Trigger an n8n workflow by name and return its response.

        Use this to delegate tasks to automated workflows: create invoices in
        Sage, send emails, sync external systems, or run any other n8n
        automation. Workflows are identified by their registered name.

        If the named workflow does not exist, an error is returned along with
        the list of available workflow names so you can retry with the correct
        name.
        """
        webhook = self.env["n8n.webhook"].search(
            [("name", "=", workflow_name), ("active", "=", True)], limit=1
        )
        if not webhook:
            available = (
                self.env["n8n.webhook"]
                .search([("active", "=", True)])
                .mapped("name")
            )
            return {
                "error": f"Workflow '{workflow_name}' not found",
                "available_workflows": available,
            }
        return webhook.trigger(payload or {})
