import base64
import calendar
import io
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError


class L10nArVatBookLine(models.Model):
    """Vista SQL: una fila por comprobante con los importes abiertos por
    alícuota de IVA y percepciones, replicando el "Libro de IVA argentino (AR)"
    de Odoo Enterprise (l10n_ar_reports) pero usando solo vistas nativas CE.
    """

    _name = "l10n_ar.vat.book.line"
    _description = "Libro de IVA Argentino (línea)"
    _auto = False
    _order = "date asc, move_name asc, id asc"

    move_id = fields.Many2one("account.move", string="Comprobante", readonly=True)
    move_name = fields.Char(string="Nombre", readonly=True)
    date = fields.Date(string="Fecha", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Contacto", readonly=True)
    cuit = fields.Char(string="CUIT", readonly=True)
    afip_responsibility_type_id = fields.Many2one(
        "l10n_ar.afip.responsibility.type", string="Cond. IVA", readonly=True
    )
    move_type = fields.Selection(
        [
            ("out_invoice", "Factura de cliente"),
            ("out_refund", "NC de cliente"),
            ("in_invoice", "Factura de proveedor"),
            ("in_refund", "NC de proveedor"),
        ],
        string="Tipo",
        readonly=True,
    )
    journal_id = fields.Many2one("account.journal", string="Diario", readonly=True)
    journal_type = fields.Selection(
        [("sale", "Ventas"), ("purchase", "Compras")],
        string="Libro",
        readonly=True,
    )
    state = fields.Selection(
        [("draft", "Borrador"), ("posted", "Registrado")],
        string="Estado",
        readonly=True,
    )
    company_id = fields.Many2one("res.company", string="Compañía", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", readonly=True)
    l10n_latam_document_type_id = fields.Many2one(
        "l10n_latam.document.type", string="Tipo de Documento", readonly=True
    )

    taxed = fields.Monetary(string="Gravado", readonly=True, currency_field="currency_id")
    not_taxed = fields.Monetary(
        string="No gravado", readonly=True, currency_field="currency_id",
        help="Importe neto exento, no gravado o sin IVA",
    )
    vat_25 = fields.Monetary(string="IVA 2,5%", readonly=True, currency_field="currency_id")
    vat_5 = fields.Monetary(string="IVA 5%", readonly=True, currency_field="currency_id")
    vat_10_5 = fields.Monetary(string="IVA 10,5%", readonly=True, currency_field="currency_id")
    vat_21 = fields.Monetary(string="IVA 21%", readonly=True, currency_field="currency_id")
    vat_27 = fields.Monetary(string="IVA 27%", readonly=True, currency_field="currency_id")
    perc_vat = fields.Monetary(string="Perc. IVA", readonly=True, currency_field="currency_id")
    perc_iibb = fields.Monetary(string="Perc. IIBB", readonly=True, currency_field="currency_id")
    perc_profits = fields.Monetary(string="Gcia. perc.", readonly=True, currency_field="currency_id")
    municipal = fields.Monetary(string="Municipales", readonly=True, currency_field="currency_id")
    other_taxes = fields.Monetary(string="Otros impuestos", readonly=True, currency_field="currency_id")
    total = fields.Monetary(string="Total", readonly=True, currency_field="currency_id")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Categorización de líneas de impuesto por grupo (l10n_ar):
        # - l10n_ar_vat_afip_code: '4'=10,5%, '5'=21%, '6'=27%, '8'=5%, '9'=2,5%
        #   ('0','1','2','3' son no gravado/exento/0%, sin importe de IVA)
        # - l10n_ar_tribute_afip_code: '06'=Perc. IVA, '07'=Perc. IIBB,
        #   '03'/'08'=municipales. Ganancias se detecta por nombre del grupo
        #   (el cast jsonb->text cubre todas las traducciones).
        self.env.cr.execute(
            """
CREATE OR REPLACE VIEW %(table)s AS (
WITH base_lines AS (
    SELECT
        sub.move_id,
        SUM(CASE WHEN sub.has_vat THEN sub.balance ELSE 0 END) AS taxed,
        SUM(CASE WHEN sub.has_vat THEN 0 ELSE sub.balance END) AS not_taxed
    FROM (
        SELECT
            l.move_id,
            l.balance,
            EXISTS (
                SELECT 1
                FROM account_move_line_account_tax_rel r
                JOIN account_tax t ON t.id = r.account_tax_id
                JOIN account_tax_group g ON g.id = t.tax_group_id
                WHERE r.account_move_line_id = l.id
                  AND g.l10n_ar_vat_afip_code IN ('4', '5', '6', '8', '9')
            ) AS has_vat
        FROM account_move_line l
        WHERE l.display_type = 'product'
    ) sub
    GROUP BY sub.move_id
),
tax_lines AS (
    SELECT
        sub.move_id,
        SUM(CASE WHEN sub.cat = 'vat_25' THEN sub.balance ELSE 0 END) AS vat_25,
        SUM(CASE WHEN sub.cat = 'vat_5' THEN sub.balance ELSE 0 END) AS vat_5,
        SUM(CASE WHEN sub.cat = 'vat_10_5' THEN sub.balance ELSE 0 END) AS vat_10_5,
        SUM(CASE WHEN sub.cat = 'vat_21' THEN sub.balance ELSE 0 END) AS vat_21,
        SUM(CASE WHEN sub.cat = 'vat_27' THEN sub.balance ELSE 0 END) AS vat_27,
        SUM(CASE WHEN sub.cat = 'perc_vat' THEN sub.balance ELSE 0 END) AS perc_vat,
        SUM(CASE WHEN sub.cat = 'perc_iibb' THEN sub.balance ELSE 0 END) AS perc_iibb,
        SUM(CASE WHEN sub.cat = 'perc_profits' THEN sub.balance ELSE 0 END) AS perc_profits,
        SUM(CASE WHEN sub.cat = 'municipal' THEN sub.balance ELSE 0 END) AS municipal,
        SUM(CASE WHEN sub.cat = 'other' THEN sub.balance ELSE 0 END) AS other_taxes
    FROM (
        SELECT
            l.move_id,
            l.balance,
            CASE
                WHEN g.l10n_ar_vat_afip_code = '9' THEN 'vat_25'
                WHEN g.l10n_ar_vat_afip_code = '8' THEN 'vat_5'
                WHEN g.l10n_ar_vat_afip_code = '4' THEN 'vat_10_5'
                WHEN g.l10n_ar_vat_afip_code = '5' THEN 'vat_21'
                WHEN g.l10n_ar_vat_afip_code = '6' THEN 'vat_27'
                WHEN g.l10n_ar_tribute_afip_code = '06' THEN 'perc_vat'
                WHEN g.l10n_ar_tribute_afip_code = '07' THEN 'perc_iibb'
                WHEN g.l10n_ar_tribute_afip_code IN ('03', '08') THEN 'municipal'
                WHEN g.name::text ILIKE '%%ganan%%' THEN 'perc_profits'
                ELSE 'other'
            END AS cat
        FROM account_move_line l
        JOIN account_tax t ON t.id = l.tax_line_id
        JOIN account_tax_group g ON g.id = t.tax_group_id
    ) sub
    GROUP BY sub.move_id
),
totals AS (
    SELECT l.move_id, SUM(l.balance) AS total
    FROM account_move_line l
    WHERE l.display_type = 'payment_term'
    GROUP BY l.move_id
)
SELECT
    am.id AS id,
    am.id AS move_id,
    am.name AS move_name,
    COALESCE(am.invoice_date, am.date) AS date,
    am.commercial_partner_id AS partner_id,
    rp.vat AS cuit,
    rp.l10n_ar_afip_responsibility_type_id AS afip_responsibility_type_id,
    am.move_type,
    am.journal_id,
    aj.type AS journal_type,
    am.state,
    am.company_id,
    rc.currency_id AS currency_id,
    am.l10n_latam_document_type_id,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(bl.taxed, 0) AS taxed,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(bl.not_taxed, 0) AS not_taxed,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.vat_25, 0) AS vat_25,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.vat_5, 0) AS vat_5,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.vat_10_5, 0) AS vat_10_5,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.vat_21, 0) AS vat_21,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.vat_27, 0) AS vat_27,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.perc_vat, 0) AS perc_vat,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.perc_iibb, 0) AS perc_iibb,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.perc_profits, 0) AS perc_profits,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.municipal, 0) AS municipal,
    (CASE WHEN aj.type = 'sale' THEN -1 ELSE 1 END) * COALESCE(tl.other_taxes, 0) AS other_taxes,
    (CASE WHEN aj.type = 'sale' THEN 1 ELSE -1 END) * COALESCE(tt.total, 0) AS total
FROM account_move am
JOIN account_journal aj ON aj.id = am.journal_id
JOIN res_company rc ON rc.id = am.company_id
LEFT JOIN res_partner rp ON rp.id = am.commercial_partner_id
LEFT JOIN base_lines bl ON bl.move_id = am.id
LEFT JOIN tax_lines tl ON tl.move_id = am.id
LEFT JOIN totals tt ON tt.move_id = am.id
WHERE am.move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
  AND am.state != 'cancel'
)
            """
            % {"table": self._table}
        )

    # -------------------------------------------------------------------------
    # Helpers de período
    # -------------------------------------------------------------------------

    def _get_period_defaults(self):
        """Deriva (date_from, date_to) del recordset (registros filtrados o
        seleccionados en la vista). Si no hay registros, usa el mes anterior."""
        dates = [d for d in self.mapped("date") if d]
        if dates:
            dmin, dmax = min(dates), max(dates)
            date_from = dmin.replace(day=1)
            date_to = dmax.replace(day=calendar.monthrange(dmax.year, dmax.month)[1])
        else:
            first_of_this_month = fields.Date.context_today(self).replace(day=1)
            date_to = first_of_this_month - relativedelta(days=1)
            date_from = date_to.replace(day=1)
        return date_from, date_to

    def _get_company(self):
        companies = self.mapped("company_id")
        return companies[0] if len(companies) == 1 else self.env.company

    # -------------------------------------------------------------------------
    # Acciones (botones de cabecera de la lista)
    # -------------------------------------------------------------------------

    def action_open_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_tax_closing(self):
        """Abre el wizard de Cierre de Impuestos precargado con el período
        de los registros seleccionados/filtrados en la vista."""
        date_from, date_to = self._get_period_defaults()
        company = self._get_company()
        return {
            "type": "ir.actions.act_window",
            "name": _("Cierre de impuestos"),
            "res_model": "l10n_ar.tax.closing.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_company_id": company.id,
                "default_date_from": date_from,
                "default_date_to": date_to,
            },
        }

    def action_open_vat_book_zip(self):
        """Abre el wizard existente de Libro IVA Digital / IVA Simple (ZIP)."""
        date_from, date_to = self._get_period_defaults()
        company = self._get_company()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_ar_account_reports.action_l10n_ar_vat_book_wizard"
        )
        action["context"] = {
            "default_company_id": company.id,
            "default_date_from": fields.Date.to_string(date_from),
            "default_date_to": fields.Date.to_string(date_to),
        }
        return action

    def action_print_pdf(self):
        if not self:
            raise UserError(_("Seleccione los comprobantes a imprimir."))
        return self.env.ref(
            "l10n_ar_tax_declaration_ce.action_report_vat_book"
        ).report_action(self.sorted(key=lambda r: (r.date or date.min, r.id)))

    def action_export_xlsx(self):
        if not self:
            raise UserError(_("Seleccione los comprobantes a exportar."))
        try:
            import xlsxwriter  # noqa: F401 (incluido en las dependencias de Odoo)
        except ImportError as exc:
            raise UserError(_("La librería xlsxwriter no está disponible.")) from exc

        date_from, date_to = self._get_period_defaults()
        records = self.sorted(key=lambda r: (r.date or date.min, r.id))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Libro IVA")

        header_fmt = workbook.add_format({"bold": True, "bg_color": "#DDDDDD", "border": 1})
        money_fmt = workbook.add_format({"num_format": "#,##0.00"})
        money_bold_fmt = workbook.add_format({"num_format": "#,##0.00", "bold": True, "top": 1})
        date_fmt = workbook.add_format({"num_format": "dd/mm/yyyy"})
        bold_fmt = workbook.add_format({"bold": True, "top": 1})

        columns = self._xlsx_columns()
        for col, (label, _field, width, _is_money) in enumerate(columns):
            sheet.write(0, col, label, header_fmt)
            sheet.set_column(col, col, width)

        row = 1
        for rec in records:
            for col, (_label, field_name, _width, is_money) in enumerate(columns):
                value = rec[field_name] if field_name else ""
                if field_name == "date":
                    if value:
                        sheet.write_datetime(row, col, fields.Datetime.to_datetime(value), date_fmt)
                elif is_money:
                    sheet.write_number(row, col, value or 0.0, money_fmt)
                elif field_name in ("partner_id", "afip_responsibility_type_id"):
                    sheet.write(row, col, value.display_name if value else "")
                else:
                    sheet.write(row, col, value or "")
            row += 1

        # Totales
        sheet.write(row, 0, _("Totales"), bold_fmt)
        for col, (_label, field_name, _width, is_money) in enumerate(columns):
            if is_money:
                sheet.write_number(row, col, sum(records.mapped(field_name)), money_bold_fmt)

        workbook.close()

        filename = "Libro_IVA_AR_%s_%s.xlsx" % (date_from, date_to)
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "datas": base64.b64encode(output.getvalue()),
                "res_model": self._name,
                "type": "binary",
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    @api.model
    def _xlsx_columns(self):
        """(etiqueta, campo, ancho, es_moneda)"""
        return [
            (_("Fecha"), "date", 12, False),
            (_("Nombre"), "move_name", 22, False),
            (_("Contacto"), "partner_id", 35, False),
            (_("Cond. IVA"), "afip_responsibility_type_id", 22, False),
            (_("CUIT"), "cuit", 14, False),
            (_("Gravado"), "taxed", 14, True),
            (_("No gravado"), "not_taxed", 14, True),
            (_("IVA 2,5%"), "vat_25", 12, True),
            (_("IVA 5%"), "vat_5", 12, True),
            (_("IVA 10,5%"), "vat_10_5", 13, True),
            (_("IVA 21%"), "vat_21", 14, True),
            (_("IVA 27%"), "vat_27", 13, True),
            (_("Perc. IVA"), "perc_vat", 13, True),
            (_("Perc. IIBB"), "perc_iibb", 13, True),
            (_("Gcia. perc."), "perc_profits", 13, True),
            (_("Municipales"), "municipal", 13, True),
            (_("Otros impuestos"), "other_taxes", 14, True),
            (_("Total"), "total", 16, True),
        ]
