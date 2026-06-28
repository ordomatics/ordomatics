{
    "name": "n8n Connector",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Trigger n8n workflows from Odoo via webhooks",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/n8n_webhook_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
