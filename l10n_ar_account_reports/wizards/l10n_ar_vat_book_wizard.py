from odoo import models, fields, _, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools import SQL
import base64
import io
import zipfile
from csv import DictWriter


class L10nArVatBookWizard(models.TransientModel):
    _name = "l10n_ar.vat.book.wizard"
    _description = "Generación Libro IVA Digital (TXT/CSV)"

    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    
    # Options equivalent
    tax_types = fields.Selection([
        ('purchase', 'Compras'),
        ('sale', 'Ventas'),
        ('both', 'Ambos'),
    ], string="Tipo de Reporte", default='both', required=True)

    # Result fields
    file_content = fields.Binary(string="Archivo ZIP", readonly=True)
    file_name = fields.Char(string="Nombre del Archivo", readonly=True)

    def action_generate(self):
        self.ensure_one()
        
        # Determine tax types to process
        tax_types_list = []
        if self.tax_types in ['sale', 'both']:
            tax_types_list.append('sale')
        if self.tax_types in ['purchase', 'both']:
             tax_types_list.append('purchase')

        # Logic from l10n_ar_vat_book.py adapted
        file_types = [f"{tax}_{suffix}" for tax in tax_types_list for suffix in ["invoice", "refund"]]
        file_names = {
            "sale_invoice": "DEBITO",
            "sale_refund": "REST_DEBITO",
            "purchase_invoice": "CREDITO",
            "purchase_refund": "REST_CREDITO",
        }

        stream = io.BytesIO()
        has_files = False
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_type in file_types:
                move_ids = self._vat_simple_get_csv_move_ids(file_type)
                if not move_ids:
                    continue
                
                file_data = self._vat_simple_get_data(file_type, move_ids)
                if file_data:
                    file_name = f"{file_names[file_type]}_{self.date_to}.csv"
                    zf.writestr(file_name, file_data)
                    has_files = True
        
        if not has_files:
             raise ValidationError(_("No se encontraron registros para los criterios seleccionados."))

        file_content = stream.getvalue()
        
        self.write({
            'file_content': base64.b64encode(file_content),
            'file_name': f"IVA_Digital_{self.date_to}.zip",
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ar.vat.book.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    # Helpers ported from l10n_ar_vat_book.py
    # NOTE: Adapted 'options' dict to use self fields

    def _vat_simple_get_lines_domain(self):
        domain = [
            ("state", "=", "posted"),
            ("journal_id.l10n_latam_use_documents", "=", True),
            ("company_id", "=", self.company_id.id),
        ]
        if self.date_to:
            domain += [("date", "<=", self.date_to)]
        if self.date_from:
            domain += [("date", ">=", self.date_from)]
        return domain

    def _vat_simple_get_csv_move_ids(self, file_type):
        domain = [("l10n_latam_document_type_id.code", "!=", False)] + self._vat_simple_get_lines_domain()
        if file_type == "sale_invoice":
            domain += [("journal_id.type", "=", "sale"), ("move_type", "=", "out_invoice")]
        elif file_type == "sale_refund":
            domain += [("journal_id.type", "=", "sale"), ("move_type", "=", "out_refund")]
        elif file_type == "purchase_invoice":
            domain += [("journal_id.type", "=", "purchase"), ("move_type", "=", "in_invoice")]
        else:
            domain += [("journal_id.type", "=", "purchase"), ("move_type", "=", "in_refund")]
        return tuple(self.env["account.move"].search(domain, order="invoice_date asc, name asc, id asc").ids)

    def _vat_simple_transform_column(self, value):
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            if value < 0:
                value = -value
            value = str(value)
        if "." in value:
            value = value.replace(".", ",")
        return value

    def _vat_simple_get_data(self, file_type, move_ids):
        if "sale_" in file_type:
            results = self._vat_simple_build_sale_query(file_type, move_ids)
        else:
            results = self._vat_simple_build_purchase_query(file_type, move_ids)

        if not results:
             return None

        fp = io.StringIO()
        headers = results[0].keys() if results else []
        writer = DictWriter(fp, fieldnames=headers, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)
        return fp.getvalue()

    def _vat_simple_get_taxes_from_row(self, row):
        aml_ids = row.get("aml_ids")
        total = row.get("balance")
        line_ids = self.env["account.move.line"].browse(aml_ids)

        currency_id = line_ids[:1].move_id.currency_id
        tax_data = line_ids.tax_ids.filtered("tax_group_id.l10n_ar_vat_afip_code").compute_all(
            total, currency=currency_id
        )
        return currency_id.round(tax_data["total_included"] - tax_data["total_excluded"])

    def _vat_simple_build_purchase_query(self, file_type, move_ids):
        columns_map = {
            "Concepto": "concept",
            "Codigo de Alicuota": "rate_code",
            "Monto Neto Gravado": "balance",
            "Credito Fiscal Facturado": "vat_amount",
        }
        if file_type == "purchase_invoice":
            columns_map["Credito Fiscal Computable"] = "vat_amount"

        query = SQL(
            """
                WITH move_lines_with_concept AS (
                    SELECT DISTINCT ON (aml.id)
                        aml.*,
                        CASE
                            WHEN tag_rel.account_account_tag_id = %(lease_tag_id)s THEN 2
                            WHEN tag_rel.account_account_tag_id = %(fixed_tag_id)s THEN 4
                            WHEN pt.type = 'consu' THEN 1
                            WHEN pt.type = 'service' THEN 3
                            ELSE 1
                        END as concept,
                        btg.l10n_ar_vat_afip_code AS rate_code
                    FROM account_move_line aml
                    LEFT JOIN product_product pp ON aml.product_id = pp.id
                    LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                    LEFT JOIN account_account_account_tag tag_rel
                        ON aml.account_id = tag_rel.account_account_id
                        AND tag_rel.account_account_tag_id IN (%(lease_tag_id)s, %(fixed_tag_id)s)
                    LEFT JOIN account_move_line_account_tax_rel amltr ON aml.id = amltr.account_move_line_id
                    LEFT JOIN account_tax bt ON amltr.account_tax_id = bt.id
                    LEFT JOIN account_tax_group btg ON bt.tax_group_id = btg.id
                    WHERE
                        aml.move_id IN %(move_ids)s AND
                        btg.l10n_ar_vat_afip_code IN ('3', '4', '5', '6', '8', '9') AND
                        aml.partner_id IS NOT NULL
                    ORDER BY
                        aml.id,
                        (CASE
                                WHEN tag_rel.account_account_tag_id = %(lease_tag_id)s THEN 1
                                WHEN tag_rel.account_account_tag_id = %(fixed_tag_id)s THEN 2
                                ELSE 3
                        END)
                )
                SELECT
                    concept,
                    rate_code,
                    SUM(balance) AS balance,
                    ARRAY_AGG(DISTINCT id) as aml_ids,
                    ARRAY_AGG(DISTINCT move_id) as move_ids
                FROM move_lines_with_concept
                GROUP BY concept, rate_code
                ORDER BY concept, rate_code;
            """,
            lease_tag_id=self.env.ref("l10n_ar_account_reports.tag_leases_rentals_account").id,
            fixed_tag_id=self.env.ref("l10n_ar_account_reports.tag_fixed_asset_account").id,
            move_ids=move_ids,
        )

        self.env.cr.execute(query)
        data = self.env.cr.dictfetchall()

        results = []
        for row in data:
            row_data = {}
            for header_name, column in columns_map.items():
                if column == "vat_amount":
                    value = self._vat_simple_get_taxes_from_row(row)
                else:
                    value = row.get(column, "")
                value = self._vat_simple_transform_column(value)
                row_data[header_name] = value
            results.append(row_data)
        return results

    def _vat_simple_activity_sql(self):
        """Devuelve (activity_select, activity_joins) para el query de ventas.

        La actividad AFIP proviene del Many2one `l10n_ar_afip_activity_id` a
        `afip.activity` (de l10n_ar_ux), tanto en la cuenta como en la compañía.
        Se detecta su presencia y, si falta, se usa la actividad por defecto '0'
        para que el export no falle.
        """

        def field_sql(model, table_alias, join_alias):
            """Devuelve (coalesce_expr, join_sql_or_None) para un modelo dado."""
            if "l10n_ar_afip_activity_id" in self.env[model]._fields:
                return (
                    SQL("%s.code" % join_alias),
                    SQL(
                        "LEFT JOIN afip_activity %s ON %s.l10n_ar_afip_activity_id = %s.id"
                        % (join_alias, table_alias, join_alias)
                    ),
                )
            return None, None

        coalesce_parts = []
        joins = []
        for model, table_alias, join_alias in (
            ("account.account", "acc", "amlact"),
            ("res.company", "cmp", "cmpact"),
        ):
            expr, join = field_sql(model, table_alias, join_alias)
            if expr is not None:
                coalesce_parts.append(expr)
            if join is not None:
                joins.append(join)

        if not coalesce_parts:
            return SQL("'0'"), SQL("")

        coalesce_parts.append(SQL("'0'"))
        activity_select = SQL("COALESCE(%s)", SQL(", ").join(coalesce_parts))
        activity_joins = SQL(" ").join(joins) if joins else SQL("")
        return activity_select, activity_joins

    def _vat_simple_build_sale_query(self, file_type, move_ids):
        columns_map = {
            "Actividad": "activity",
            "Tipo de Operacion": "operation_type",
            "Tipo de sujeto comprador": "responsibility_type_code",
            "Codigo de Alicuota": "rate_code",
            "Monto Neto Gravado": "balance",
        }
        if file_type == "sale_invoice":
            tag_id = self.env.ref("l10n_ar_account_reports.tag_fixed_asset_account")
            operation_type_query = SQL(
                """
                (CASE
                    WHEN btg.l10n_ar_vat_afip_code IN ('0', '1', '2') THEN 3
                    WHEN aaat.account_account_tag_id = %(tag_id)s THEN 2
                    ELSE 1
                END)
                """,
                tag_id=tag_id.id,
            )
            columns_map["Debito Fiscal Facturado"] = "vat_amount"
            columns_map["Debito Fiscal O.D.P."] = "vat_amount"
            exempt_operation_type = 3
            cte_order_query = SQL(
                "ORDER BY aml.id, (CASE when aaat.account_account_tag_id = %(tag_id)s THEN 1 ELSE 2 END)",
                tag_id=tag_id.id,
            )
        else:
            operation_type_query = SQL(
                """
                (CASE
                    WHEN btg.l10n_ar_vat_afip_code IN %(code_values)s THEN 2
                    ELSE 1
                END)
                """,
                code_values=("0", "1", "2"),
            )
            columns_map["Debito Fiscal a Restituir"] = "vat_amount"
            exempt_operation_type = 2
            cte_order_query = SQL("ORDER BY aml.id")
        columns_map["Monto Neto Exento o No Gravado"] = "exempt_balance"

        # El campo de actividad AFIP en cuenta/compañía es de módulos de la
        # localización (Enterprise: l10n_ar_afip_activity_id). En instalaciones
        # Community puede no existir o llamarse distinto: detectamos su presencia
        # y, si falta, usamos la actividad por defecto '0' sin romper el query.
        activity_select, activity_joins = self._vat_simple_activity_sql()

        query = SQL(
            """
                WITH move_lines_with_operation_type AS (
                    SELECT DISTINCT ON (aml.id)
                        aml.balance,
                        aml.id,
                        aml.move_id,
                        %(activity_select)s AS activity,
                        %(operation_query)s AS operation_type,
                        rprt.code as partner_responsibility_code,
                        btg.l10n_ar_vat_afip_code
                    FROM account_move_line aml
                    LEFT JOIN account_account acc ON aml.account_id = acc.id
                    LEFT JOIN res_company cmp ON aml.company_id = cmp.id
                    %(activity_joins)s
                    LEFT JOIN account_account_account_tag aaat ON acc.id = aaat.account_account_id
                    LEFT JOIN res_partner rp ON aml.partner_id = rp.id
                    LEFT JOIN l10n_ar_afip_responsibility_type rprt ON rp.l10n_ar_afip_responsibility_type_id = rprt.id
                    LEFT JOIN account_move_line_account_tax_rel amltr ON aml.id = amltr.account_move_line_id
                    LEFT JOIN account_tax bt ON amltr.account_tax_id = bt.id
                    LEFT JOIN account_tax_group btg ON bt.tax_group_id = btg.id
                    WHERE
                        btg.l10n_ar_vat_afip_code IS NOT NULL AND aml.move_id IN %(move_ids)s
                        %(cte_order_query)s
                )
                SELECT
                    activity,
                    operation_type,
                    operation_type = %(exempt_op_type)s AS is_exempt,
                    CASE
                        WHEN operation_type = %(exempt_op_type)s THEN ''
                        WHEN partner_responsibility_code = '1' THEN '1'
                        WHEN partner_responsibility_code IN ('6', '13') THEN '2'
                        WHEN partner_responsibility_code IN ('4', '5', '7', '8', '9', '10', '16') THEN '3'
                        ELSE ''
                    END AS responsibility_type_code,
                    CASE
                        WHEN operation_type = %(exempt_op_type)s THEN ''
                        ELSE l10n_ar_vat_afip_code
                    END AS rate_code,
                    SUM(balance) AS balance,
                    ARRAY_AGG(DISTINCT id) as aml_ids,
                    ARRAY_AGG(DISTINCT move_id) as move_ids
                FROM move_lines_with_operation_type
                GROUP BY activity, operation_type, responsibility_type_code, rate_code
                ORDER BY activity, operation_type, responsibility_type_code, rate_code;
            """,
            activity_select=activity_select,
            activity_joins=activity_joins,
            operation_query=operation_type_query,
            cte_order_query=cte_order_query,
            exempt_op_type=exempt_operation_type,
            move_ids=move_ids,
        )

        self.env.cr.execute(query)
        data = self.env.cr.dictfetchall()
        exempt_columns = ["Actividad", "Tipo de Operacion", "Monto Neto Exento o No Gravado"]

        results = []
        for row in data:
            row_data = {}
            for header_name, column in columns_map.items():
                if row["is_exempt"] and header_name not in exempt_columns:
                    value = ""
                elif column == "vat_amount":
                    value = self._vat_simple_get_taxes_from_row(row)
                elif column == "exempt_balance":
                    value = row.get("balance", "") if row["is_exempt"] else ""
                elif column == "balance":
                    value = "" if row["is_exempt"] else row.get("balance", "")
                else:
                    value = row.get(column, "")
                value = self._vat_simple_transform_column(value)
                row_data[header_name] = value
            results.append(row_data)
        return results
