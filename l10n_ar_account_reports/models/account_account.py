from odoo import fields, models


class AccountAccount(models.Model):
    _inherit = "account.account"

    l10n_ar_afip_activity_id = fields.Many2one(
        "afip.activity",
        string="Actividad AFIP",
        help="Actividad económica (AFIP/ARCA) que se informa para los movimientos "
        "de esta cuenta en el Libro IVA Digital / IVA Simple. Si se deja vacía se "
        "usa la actividad por defecto de la compañía.",
    )


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ar_afip_activity_id = fields.Many2one(
        "afip.activity",
        string="Actividad AFIP por defecto",
        help="Actividad económica (AFIP/ARCA) que se informa por defecto en el "
        "Libro IVA Digital / IVA Simple cuando la cuenta no define la suya.",
    )
