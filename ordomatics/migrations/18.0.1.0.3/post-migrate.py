from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Re-run bootstrap to seed any newly added providers/models.

    All functions in run_bootstrap() are idempotent — existing records are
    skipped, only missing ones are created.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.ordomatics_setup.hooks import run_bootstrap
    run_bootstrap(env)
