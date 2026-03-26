import base64
import io
from csv import DictWriter

from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class L10nArTaxReportWizard(models.TransientModel):
    _name = "l10n_ar.tax.report.wizard"
    _description = "Tax Report (AR) - Community"

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)
    only_posted = fields.Boolean(string="Solo publicados", default=True)

    line_ids = fields.One2many(
        "l10n_ar.tax.report.line",
        "wizard_id",
        string="Líneas",
        readonly=True,
    )

    file_content = fields.Binary(string="Export (CSV)", readonly=True)
    file_name = fields.Char(string="Nombre del archivo", readonly=True)

    def _get_domain(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_("La fecha desde no puede ser mayor a la fecha hasta."))
        domain = [
            ("company_id", "=", self.company_id.id),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("tax_line_id", "!=", False),
            ("display_type", "=", False),
        ]
        if self.only_posted:
            domain.append(("move_id.state", "=", "posted"))
        return domain

    def action_compute(self):
        self.ensure_one()
        self.line_ids.unlink()

        aml = self.env["account.move.line"]
        domain = self._get_domain()
        groups = aml.read_group(
            domain=domain,
            fields=[
                "tax_line_id",
                "tax_base_amount:sum",
                "balance:sum",
            ],
            groupby=["tax_line_id"],
            lazy=False,
        )

        currency = self.company_id.currency_id
        new_lines = []
        for g in groups:
            tax_line_id = g.get("tax_line_id") and g["tax_line_id"][0]
            if not tax_line_id:
                continue
            base_amount = g.get("tax_base_amount", 0.0) or 0.0
            balance_sum = g.get("balance", 0.0) or 0.0

            # En `account.move.line` el impuesto suele quedar con signo contable.
            # Para reportes suele mostrarse como importe positivo.
            tax_amount = currency.round(abs(balance_sum))
            base_amount = currency.round(abs(base_amount))

            tax = self.env["account.tax"].browse(tax_line_id)
            new_lines.append(
                {
                    "wizard_id": self.id,
                    "tax_id": tax.id,
                    "tax_group_id": tax.tax_group_id.id,
                    "tax_name": tax.display_name,
                    "base_amount": base_amount,
                    "tax_amount": tax_amount,
                    "line_domain": repr(domain + [("tax_line_id", "=", tax.id)]),
                }
            )

        if new_lines:
            self.env["l10n_ar.tax.report.line"].create(new_lines)

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_open_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Apuntes de impuestos (Tax Report AR)"),
            "res_model": "account.move.line",
            "view_mode": "tree,form",
            "target": "current",
            "domain": self._get_domain(),
            "context": {"search_default_groupby_move": 1},
        }

    def action_export_csv(self):
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        if not self.line_ids:
            raise ValidationError(_("No hay líneas para exportar."))

        fp = io.StringIO()
        writer = DictWriter(
            fp,
            fieldnames=["tax_group", "tax", "base_amount", "tax_amount"],
            delimiter=";",
            lineterminator="\n",
        )
        writer.writeheader()
        for line in self.line_ids:
            writer.writerow(
                {
                    "tax_group": line.tax_group_id.display_name or "",
                    "tax": line.tax_name or line.tax_id.display_name or "",
                    "base_amount": line.base_amount,
                    "tax_amount": line.tax_amount,
                }
            )

        content = fp.getvalue().encode("utf-8")
        fname = f"tax_report_ar_{self.date_from}_{self.date_to}.csv"
        self.write(
            {
                "file_content": base64.b64encode(content),
                "file_name": fname,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class L10nArTaxReportLine(models.TransientModel):
    _name = "l10n_ar.tax.report.line"
    _description = "Tax Report (AR) - Línea"
    _order = "tax_group_id, tax_name, id"

    wizard_id = fields.Many2one("l10n_ar.tax.report.wizard", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id", store=False, readonly=True)

    tax_group_id = fields.Many2one("account.tax.group", string="Grupo de impuesto", readonly=True)
    tax_id = fields.Many2one("account.tax", string="Impuesto", readonly=True)
    tax_name = fields.Char(string="Impuesto (texto)", readonly=True)

    base_amount = fields.Monetary(
        string="Base",
        currency_field="currency_id",
        readonly=True,
    )
    tax_amount = fields.Monetary(
        string="Impuesto",
        currency_field="currency_id",
        readonly=True,
    )
    currency_id = fields.Many2one(related="wizard_id.company_id.currency_id", readonly=True)

    line_domain = fields.Text(string="Dominio (debug)", readonly=True)

    def action_drilldown(self):
        self.ensure_one()
        domain = []
        if self.line_domain:
            try:
                domain = safe_eval(self.line_domain, {"__builtins__": {}})
            except Exception:
                domain = []
        if not domain:
            domain = [
                ("company_id", "=", self.wizard_id.company_id.id),
                ("date", ">=", self.wizard_id.date_from),
                ("date", "<=", self.wizard_id.date_to),
                ("tax_line_id", "=", self.tax_id.id),
            ]
        return {
            "type": "ir.actions.act_window",
            "name": _("Detalle %s") % (self.tax_name or self.tax_id.display_name),
            "res_model": "account.move.line",
            "view_mode": "tree,form",
            "target": "current",
            "domain": domain,
        }

