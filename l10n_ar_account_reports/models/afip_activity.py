from odoo import api, fields, models


class AfipActivity(models.Model):
    # Modelo provisto antes por l10n_ar_ux (community). En la serie 19 ingadhoc
    # lo removio (la actividad ARCA quedo como feature de Enterprise), por lo que
    # este modulo lo provee para sostener la actividad por cuenta/compania del
    # Libro IVA en instalaciones community.
    _name = "afip.activity"
    _description = "afip.activity"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_unique", "UNIQUE(code)", "Activity code must be unique"),
        ("code_length", "CHECK(LENGTH(code) <= 6)", "Activity codes must be at most 6 characters long"),
    ]

    @api.depends("code", "name")
    @api.depends_context("formatted_display_name")
    def _compute_display_name(self):
        for activity in self:
            if activity.env.context.get("formatted_display_name"):
                activity.display_name = f"--{activity.code}--\t{activity.name}"
            else:
                activity.display_name = f"{activity.code} - {activity.name}"
