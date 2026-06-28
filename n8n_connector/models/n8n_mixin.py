import logging

from odoo import models

_logger = logging.getLogger(__name__)


class N8nMixin(models.AbstractModel):
    _name = "n8n.mixin"
    _description = "n8n Integration Mixin"

    def _n8n_trigger(self, webhook_name: str, payload: dict) -> dict:
        """Trigger an n8n webhook by name. Logs a warning and returns {} if not found."""
        webhook = self.env["n8n.webhook"].search(
            [("name", "=", webhook_name)], limit=1
        )
        if not webhook:
            _logger.warning("n8n webhook %r not found — skipping", webhook_name)
            return {}
        return webhook.trigger(payload)
