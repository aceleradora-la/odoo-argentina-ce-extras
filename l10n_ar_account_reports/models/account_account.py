from odoo import fields, models


class AccountAccount(models.Model):
    _inherit = "account.account"

    l10n_ar_afip_activity_code = fields.Char(
        string="Código de actividad AFIP",
        help="Código de actividad económica (AFIP/ARCA) que se informa para los "
        "movimientos de esta cuenta en el Libro IVA Digital / IVA Simple. "
        "Si se deja vacío se usa la actividad por defecto de la compañía.",
    )


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ar_afip_activity_code = fields.Char(
        string="Código de actividad AFIP por defecto",
        help="Código de actividad económica (AFIP/ARCA) que se informa por defecto "
        "en el Libro IVA Digital / IVA Simple cuando la cuenta no define el suyo.",
    )
