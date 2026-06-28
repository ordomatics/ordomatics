import logging

import requests

from odoo import fields, models

_logger = logging.getLogger(__name__)


class N8nWebhook(models.Model):
    _name = "n8n.webhook"
    _description = "n8n Webhook"

    name = fields.Char(required=True)
    webhook_url = fields.Char(string="Webhook URL", required=True)
    test_url = fields.Char(string="Test URL")
    auth_header_name = fields.Char(string="Auth Header Name", help="e.g. X-Auth-Token")
    auth_header_value = fields.Char(string="Auth Header Value")
    active = fields.Boolean(default=True)

    def trigger(self, payload: dict, *, use_test_url: bool = False) -> dict:
        """POST payload to this webhook. Returns the n8n response body."""
        self.ensure_one()
        url = (use_test_url and self.test_url) or self.webhook_url
        headers = {"Content-Type": "application/json"}
        if self.auth_header_name and self.auth_header_value:
            headers[self.auth_header_name] = self.auth_header_value
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except Exception:
            _logger.exception("n8n webhook %r (%s) failed", self.name, url)
            raise
