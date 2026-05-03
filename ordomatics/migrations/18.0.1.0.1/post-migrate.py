from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Re-run the full Ordomatics bootstrap after every upgrade.

    All functions in run_bootstrap() are idempotent — safe to call repeatedly.
    This ensures env-var-driven config (WhatsApp, Wave, S3, currency, pricing)
    converges on every ArgoCD sync that triggers --update-all.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.ordomatics_setup.hooks import run_bootstrap
    run_bootstrap(env)
