from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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

    @api.model
    def action_open_dynamic_tax_report(self):
        """Abre el reporte dinámico de impuestos (UI estilo Enterprise)."""
        candidate_actions = [
            # Odoo Enterprise (account_reports)
            "account_reports.action_account_report_tax",
            # Fallbacks defensivos por variantes de versiones/custom
            "account.action_account_report_tax",
            "account_reports.action_account_report_taxes",
        ]
        for xmlid in candidate_actions:
            try:
                action = self.env["ir.actions.actions"]._for_xml_id(xmlid)
            except ValueError:
                action = False
            if action:
                return action

        raise ValidationError(
            _(
                "No se encontró la acción del reporte dinámico de impuestos. "
                "Verifique que esté instalado el módulo de reportes contables correspondiente "
                "(por ejemplo, l10n_ar_reports/account_reports)."
            )
        )

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

