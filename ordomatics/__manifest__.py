{
    "name": "Ordomatics Setup",
    "version": "18.0.1.0.10",
    "category": "Technical",
    "summary": "Default configuration for Ordomatics deployments",
    "license": "LGPL-3",
    "depends": ["fs_attachment_s3", "whatsapp_llm", "whatsapp_llm_payment", "billing_products"],
    "data": [
        "data/storage/fs_storage.xml",
    ],
    "installable": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
