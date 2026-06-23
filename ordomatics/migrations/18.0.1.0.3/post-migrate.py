from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.ordomatics.hooks import _setup_company_currency

    _setup_company_currency(env)
