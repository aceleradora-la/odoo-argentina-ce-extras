from odoo import fields, models


class L10nArPadronActivity(models.Model):
    _name = "l10n_ar.padron.activity"
    _description = "Actividad económica AFIP/ARCA (Padrón)"
    _rec_name = "display_name"
    _order = "code"

    code = fields.Char("Código", required=True, index=True)
    name = fields.Char("Descripción")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Ya existe una actividad con ese código."),
    ]

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " - ".join(filter(None, [rec.code, rec.name]))
