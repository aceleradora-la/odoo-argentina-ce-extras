from odoo import _, fields, models


class AccountVatLedger(models.Model):
    """Extensión del Libro IVA de ingadhoc (l10n_ar_reports) con:

    * Export "IVA Simple (ZIP)" reutilizando la lógica ya probada del wizard
      de l10n_ar_account_reports (mismos CSVs que se suben al portal).
    * Asiento de Cierre de Impuestos del período, vía wizard precargado con
      el período/compañía del ledger, con trazabilidad del asiento generado.
    """

    _inherit = "account.vat.ledger"

    iva_simple_file = fields.Binary(
        string="Archivo IVA Simple (ZIP)",
        readonly=True,
        copy=False,
    )
    iva_simple_filename = fields.Char(
        string="Nombre archivo IVA Simple",
        readonly=True,
        copy=False,
    )
    tax_closing_move_id = fields.Many2one(
        "account.move",
        string="Asiento de cierre",
        readonly=True,
        copy=False,
        check_company=True,
        help="Asiento de cierre de impuestos generado desde este libro.",
    )

    def compute_iva_simple_data(self):
        """Genera el ZIP de IVA Simple delegando en el wizard existente."""
        self.ensure_one()
        wizard = self.env["l10n_ar.vat.book.wizard"].create(
            {
                "company_id": self.company_id.id,
                "date_from": self.date_from,
                "date_to": self.date_to,
                # El ledger es de ventas o compras: exportamos solo ese tipo.
                "tax_types": self.type,
            }
        )
        wizard.action_generate()
        type_label = {"sale": "VENTAS", "purchase": "COMPRAS"}.get(self.type, self.type)
        self.write(
            {
                "iva_simple_file": wizard.file_content,
                "iva_simple_filename": "IVA_Simple_%s_%s.zip" % (type_label, self.date_to),
            }
        )
        return True

    def action_open_tax_closing(self):
        """Abre el wizard de Cierre de Impuestos precargado con el período."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Cierre de impuestos"),
            "res_model": "l10n_ar.tax.closing.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_company_id": self.company_id.id,
                "default_date_from": fields.Date.to_string(self.date_from),
                "default_date_to": fields.Date.to_string(self.date_to),
                "default_vat_ledger_id": self.id,
            },
        }

    def action_view_tax_closing_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Asiento de cierre"),
            "res_model": "account.move",
            "res_id": self.tax_closing_move_id.id,
            "view_mode": "form",
            "target": "current",
        }
