from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ar_account_tax_settlement.hooks import (
    ensure_tax_settlement_journals_all_companies,
)


def migrate(cr, version):
    """Crea los diarios de liquidación que faltan en compañías creadas después de
    instalar el módulo (sobre todo sucursales) y completa la cuenta de liquidación
    en los diarios que quedaron sin ella."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_tax_settlement_journals_all_companies(env)
