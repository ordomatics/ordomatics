from odoo.api import Environment
from odoo import SUPERUSER_ID


def migrate(cr, version):
    env = Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.ordomatics.hooks import run_bootstrap
    run_bootstrap(env)
