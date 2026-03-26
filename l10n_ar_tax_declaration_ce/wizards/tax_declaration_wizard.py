from odoo import _, fields, models


class L10nArTaxDeclarationWizard(models.TransientModel):
    _name = "l10n_ar.tax.declaration.wizard"
    _description = "Declaración Fiscal (AR)"

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)

    def action_open_tax_report(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tax Report (AR)"),
            "res_model": "l10n_ar.tax.report.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_company_id": self.company_id.id,
                "default_date_from": self.date_from,
                "default_date_to": self.date_to,
            },
        }

    def action_open_vat_book(self):
        """Abre el wizard existente de Libro IVA Digital (ZIP)."""
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_ar_account_reports.action_l10n_ar_vat_book_wizard"
        )
        ctx = action.get("context", {})
        if isinstance(ctx, str):
            # Odoo permite context como string-safe-eval en acciones.
            from odoo.tools.safe_eval import safe_eval

            ctx = safe_eval(ctx)
        ctx = dict(ctx or {})
        ctx.update(
            {
                "default_company_id": self.company_id.id,
                "default_date_from": self.date_from,
                "default_date_to": self.date_to,
            }
        )
        action["context"] = ctx
        return action

