from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    # Marca del período cerrado: permite detectar duplicados de cierre por
    # fechas reales (no por el string del ref, que es editable y traducible).
    l10n_ar_tax_closing_date_from = fields.Date(
        string="Cierre impuestos: desde",
        copy=False,
        index=True,
    )
    l10n_ar_tax_closing_date_to = fields.Date(
        string="Cierre impuestos: hasta",
        copy=False,
    )
