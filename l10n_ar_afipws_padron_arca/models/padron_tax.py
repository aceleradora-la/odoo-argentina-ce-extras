from odoo import fields, models


class L10nArPadronTax(models.Model):
    _name = "l10n_ar.padron.tax"
    _description = "Impuesto AFIP/ARCA (Padrón)"
    _rec_name = "display_name"
    _order = "code"

    code = fields.Char("Código", required=True, index=True)
    name = fields.Char("Descripción")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Ya existe un impuesto con ese código."),
    ]

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " - ".join(filter(None, [rec.code, rec.name]))
