from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountVatLedger(models.Model):
    """Extensión del Libro IVA de ingadhoc (l10n_ar_reports) con:

    * Export "IVA Simple (ZIP)" reutilizando la lógica ya probada del wizard
      de l10n_ar_account_reports (mismos CSVs que se suben al portal).
    * Asiento de Cierre de Impuestos del período, vía wizard precargado con
      el período/compañía del ledger, con trazabilidad del asiento generado.
    """

    _inherit = "account.vat.ledger"

    # Títulos en inglés que ingadhoc sella en el campo `name` al crear el Libro.
    _TITLE_TRANSLATIONS = {
        "Purchases VAT Ledger": "Libro IVA Compras",
        "Purchase VAT Ledger": "Libro IVA Compras",
        "Sales VAT Ledger": "Libro IVA Ventas",
        "Sale VAT Ledger": "Libro IVA Ventas",
    }

    def _l10n_ar_translate_title(self, name):
        """Pasa a español el título en inglés que sella el módulo base."""
        if not name:
            return name
        for en, es in self._TITLE_TRANSLATIONS.items():
            name = name.replace(en, es)
        return name

    @api.model
    def default_get(self, fields_list):
        # También traducimos el nombre propuesto en el formulario (antes de guardar).
        res = super().default_get(fields_list)
        if res.get("name"):
            res["name"] = self._l10n_ar_translate_title(res["name"])
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            # Título en español (el campo se arma en código, no es traducible vía .po).
            new_name = rec._l10n_ar_translate_title(rec.name)
            if new_name != rec.name:
                rec.name = new_name
            # Vinculación con un asiento de cierre del MISMO período ya generado
            # (ej. el cierre se hizo desde Compras y ahora se crea el Libro de Ventas).
            if not rec.tax_closing_move_id and rec.date_from and rec.date_to:
                move = self.env["account.move"].search(
                    [
                        ("company_id", "=", rec.company_id.id),
                        ("l10n_ar_tax_closing_date_from", "=", rec.date_from),
                        ("l10n_ar_tax_closing_date_to", "=", rec.date_to),
                        ("state", "!=", "cancel"),
                    ],
                    limit=1,
                )
                if move:
                    rec.tax_closing_move_id = move
        return records

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

    tax_closing_payment_state = fields.Selection(
        [
            ("draft", "Asiento borrador"),
            ("to_pay", "A pagar"),
            ("paid", "Pagado"),
            ("nothing", "Sin deuda"),
        ],
        string="Estado de pago del cierre",
        compute="_compute_tax_closing_payment_state",
        help="Estado del circuito de pago del asiento de cierre: a pagar cuando "
        "hay líneas por pagar/cobrar sin conciliar, pagado cuando todas están "
        "conciliadas, sin deuda si la contrapartida no es una cuenta por pagar/cobrar.",
    )

    @api.depends(
        "tax_closing_move_id.state",
        "tax_closing_move_id.line_ids.reconciled",
    )
    def _compute_tax_closing_payment_state(self):
        for rec in self:
            move = rec.tax_closing_move_id
            if not move:
                rec.tax_closing_payment_state = False
            elif move.state != "posted":
                rec.tax_closing_payment_state = "draft"
            else:
                open_lines = rec._get_tax_closing_open_lines()
                if open_lines:
                    rec.tax_closing_payment_state = "to_pay"
                elif move.line_ids.filtered(
                    lambda x: x.account_id.account_type in ("liability_payable", "asset_receivable")
                ):
                    rec.tax_closing_payment_state = "paid"
                else:
                    rec.tax_closing_payment_state = "nothing"

    def _get_tax_closing_open_lines(self):
        self.ensure_one()
        return self.tax_closing_move_id.line_ids.filtered(
            lambda r: not r.reconciled
            and r.account_id.account_type in ("liability_payable", "asset_receivable")
        )

    def action_pay_tax_closing(self):
        """Abre el wizard de pago imputado contra la deuda del asiento de cierre.
        Mismo patrón que action_pay_tax_settlement de l10n_ar_account_tax_settlement."""
        self.ensure_one()
        move = self.tax_closing_move_id
        if not move or move.state != "posted":
            raise ValidationError(_("El asiento de cierre debe estar publicado para poder pagarlo."))

        open_lines = self._get_tax_closing_open_lines()
        if not open_lines:
            raise ValidationError(
                _(
                    "El asiento de cierre no tiene líneas por pagar sin conciliar. "
                    "Verifique que la contrapartida use una cuenta de tipo "
                    "'A pagar' / 'A cobrar' con un partner asignado."
                )
            )

        partner = open_lines.mapped("partner_id")
        if len(partner) != 1:
            raise ValidationError(
                _("Las líneas a pagar del cierre deben tener un único partner (organismo recaudador).")
            )

        account_types = set(open_lines.mapped("account_id.account_type"))
        if account_types == {"liability_payable"}:
            partner_type, payment_type = "supplier", "outbound"
        elif account_types == {"asset_receivable"}:
            partner_type, payment_type = "customer", "inbound"
        else:
            raise ValidationError(
                _("Las líneas a pagar mezclan cuentas por cobrar y por pagar; no es posible un único pago.")
            )

        # account_payment_pro popula `to_pay_move_line_ids` con un compute que corre
        # con `pay_now` en contexto; active_model/active_ids lo restringen a estas líneas.
        return {
            "name": _("Registrar Pago"),
            "view_mode": "form",
            "res_model": "account.payment",
            "target": "current",
            "type": "ir.actions.act_window",
            "context": {
                "default_partner_id": partner.id,
                "default_partner_type": partner_type,
                "default_payment_type": payment_type,
                "default_company_id": self.company_id.id,
                "pay_now": True,
                "active_model": "account.move.line",
                "active_ids": open_lines.ids,
                "create": True,
                "pop_up": True,
                "force_simple": True,
            },
        }

    libro_iva_currency_mode = fields.Selection(
        [
            ("invoice_currency", "Moneda del comprobante"),
            ("company_currency", "Pesos (moneda de la compañía)"),
        ],
        string="Moneda del TXT",
        default="invoice_currency",
        help="Moneda en la que se informan los importes del TXT del Libro "
        "IVA Digital (RG 3685). Debe coincidir con la opción elegida al "
        "importar en el Portal IVA de ARCA ('Moneda y tipo de cambio'). "
        "'Moneda del comprobante' es el criterio original de la RG 3685 y "
        "no requiere conversión; 'Pesos' convierte todos los importes a la "
        "moneda de la compañía usando el tipo de cambio de cada comprobante.",
    )

    def _l10n_ar_reginfo_rate(self, invoice):
        """Tipo de cambio guardado en el propio comprobante (Campo 18 del
        Vouchers_*.txt). Usamos ESTE valor -no `res.currency._convert()`,
        que busca la cotización de la tabla para la fecha del comprobante-
        porque en AR el tipo de cambio suele cargarse a mano por
        comprobante y puede no coincidir con la cotización oficial de esa
        fecha; usar una fuente distinta de la que usó Odoo para calcular
        `amount_total_signed`/`balance` deja un residuo de descuadre que
        el Portal IVA de ARCA rechaza."""
        return invoice.invoice_currency_rate

    def _l10n_ar_reginfo_to_company_currency(self, invoice, amount):
        return invoice.company_currency_id.round(amount * self._l10n_ar_reginfo_rate(invoice))

    def _get_tax_row(self, invoice, base, code, tax_amount, impo=False):
        """`invoice._get_vat()` (l10n_ar, Community) siempre devuelve
        BaseImp/Importe en la moneda del comprobante (amount_currency); no
        tiene opción de moneda. Si el modo elegido es 'Pesos', convertimos acá
        antes de armar la fila (ver `libro_iva_currency_mode` y
        `_get_REGINFO_CV_CBTE`, que resuelve el mismo problema para el
        'Importe Total' del archivo de comprobantes)."""
        if self.libro_iva_currency_mode == "company_currency" and invoice.currency_id != invoice.company_currency_id:
            base = self._l10n_ar_reginfo_to_company_currency(invoice, base)
            tax_amount = self._l10n_ar_reginfo_to_company_currency(invoice, tax_amount)
        return super()._get_tax_row(invoice, base, code, tax_amount, impo=impo)

    def _l10n_ar_reginfo_amounts(self, inv):
        """Monto total y desglose de impuestos del comprobante, en la moneda
        elegida por `libro_iva_currency_mode`.

        `l10n_ar_reports._get_REGINFO_CV_CBTE` (Vouchers_*.txt) hardcodea
        `inv._l10n_ar_get_amounts(company_currency=True)` y
        `inv.amount_total_signed`: SIEMPRE en pesos, sin dar opción, mientras
        que `_get_vat()` (Alicuots_*.txt) siempre está en moneda del
        comprobante. Para comprobantes en moneda extranjera, el TXT queda
        con el "Importe Total" en pesos y las alícuotas en la moneda
        original: el Portal IVA de ARCA lo rechaza con
        "El Importe Total (X) no coincide con la suma de los demás montos (Y)".

        Para no depender de si `_l10n_ar_get_amounts` acepta o no el kwarg
        `company_currency` (cambia según la versión de Odoo: existía en
        17.0, se quitó en 18.0/19.0, donde el método ya sólo devuelve
        moneda del comprobante), lo llamamos siempre sin kwargs y
        convertimos nosotros mismos si corresponde, usando el tipo de
        cambio propio del comprobante (ver _l10n_ar_reginfo_rate).
        """
        amounts = inv._l10n_ar_get_amounts()
        amount_total = (1 if inv.is_inbound() else -1) * inv.amount_total_in_currency_signed
        if self.libro_iva_currency_mode == "company_currency" and inv.currency_id != inv.company_currency_id:
            amounts = {
                key: self._l10n_ar_reginfo_to_company_currency(inv, value)
                for key, value in amounts.items()
            }
            amount_total = (1 if inv.is_inbound() else -1) * inv.amount_total_signed
        return amounts, amount_total

    def _get_REGINFO_CV_CBTE(self, alicuotas):
        """Override completo de l10n_ar_reports (19.0/18.0, ver
        _l10n_ar_reginfo_amounts): única diferencia con el original es que
        `amounts`/`amount_total` salen de `_l10n_ar_reginfo_amounts` (según
        `libro_iva_currency_mode`) en vez de estar hardcodeados a pesos.
        Resto del método sin cambios respecto a l10n_ar_reports."""
        self.ensure_one()
        res = []
        invoices = self._get_txt_invoices()
        for inv in invoices:
            # si no existe la factura en alicuotas es porque no tienen ninguna
            cant_alicuotas = len(alicuotas.get(inv))

            currency_rate = inv.invoice_currency_rate
            currency_code = inv.currency_id.l10n_ar_afip_code

            invoice_number, pos_number = self._get_pos_and_invoice_invoice_number(inv)
            doc_code, doc_number = self._get_partner_document_code_and_number(inv.partner_id)

            amounts, amount_total = self._l10n_ar_reginfo_amounts(inv)
            vat_amount = amounts["vat_amount"]
            vat_exempt_base_amount = amounts["vat_exempt_base_amount"]
            vat_untaxed_base_amount = amounts["vat_untaxed_base_amount"]
            other_taxes_amount = amounts["other_taxes_amount"]
            vat_perc_amount = amounts["vat_perc_amount"]
            iibb_perc_amount = amounts["iibb_perc_amount"]
            mun_perc_amount = amounts["mun_perc_amount"]
            intern_tax_amount = amounts["intern_tax_amount"]
            perc_imp_nacionales_amount = amounts["profits_perc_amount"] + amounts["other_perc_amount"]

            if vat_exempt_base_amount:
                # operacion con zona franca
                if inv.partner_id.l10n_ar_afip_responsibility_type_id.code == "10":
                    codigo_operacion = "Z"
                # expo al exterior
                elif inv.l10n_latam_document_type_id.l10n_ar_letter == "E":
                    codigo_operacion = "X"
                # operacion exenta
                else:
                    codigo_operacion = "E"
            # despacho de importacion
            elif inv.l10n_latam_document_type_id.code == "66":
                codigo_operacion = "E"
            # operacion no gravada
            elif vat_untaxed_base_amount:
                codigo_operacion = "N"
            else:
                codigo_operacion = " "

            row = [
                # Campo 1: Fecha de comprobante
                inv.invoice_date.strftime("%Y%m%d"),
                # Campo 2: Tipo de Comprobante.
                f"{int(inv.l10n_latam_document_type_id.code):0>3d}",
                # Campo 3: Punto de Venta
                pos_number,
                # Campo 4: Número de Comprobante
                invoice_number,
            ]

            if self.type == "sale":
                # Campo 5: Número de Comprobante Hasta.
                row.append(invoice_number)
            else:
                # Campo 5: Despacho de importación
                if inv.l10n_latam_document_type_id.code == "66":
                    row.append((inv.l10n_latam_document_number).rjust(16, "0"))
                else:
                    row.append("".rjust(16, " "))

            row += [
                # Campo 6: Código de documento del comprador.
                doc_code,
                # Campo 7: Número de Identificación del comprador
                doc_number,
                # Campo 8: Apellido y Nombre del comprador.
                inv.commercial_partner_id.name.ljust(30, " ")[:30],
                # Campo 9: Importe Total de la Operación.
                self.format_amount(amount_total),
                # Campo 10: Importe total de conceptos que no integran el precio neto gravado
                self.format_amount(vat_untaxed_base_amount),
            ]

            if self.type == "sale":
                row += [
                    # Campo 11: Percepción a no categorizados
                    self.format_amount(0.0),
                    # Campo 12: Importe de operaciones exentas
                    self.format_amount(vat_exempt_base_amount),
                    # Campo 13: Importe de percepciones o pagos a cuenta de impuestos Nacionales
                    self.format_amount(perc_imp_nacionales_amount + vat_perc_amount),
                ]
            else:
                row += [
                    # Campo 11: Importe de operaciones exentas
                    self.format_amount(vat_exempt_base_amount),
                    # Campo 12: Importe de percepciones o pagos a cuenta del Impuesto al Valor Agregado
                    self.format_amount(vat_perc_amount),
                    # Campo 13: Importe de percepciones o pagos a cuenta otros impuestos nacionales
                    self.format_amount(perc_imp_nacionales_amount),
                ]

            row += [
                # Campo 14: Importe de percepciones de ingresos brutos
                self.format_amount(iibb_perc_amount),
                # Campo 15: Importe de percepciones de impuestos municipales
                self.format_amount(mun_perc_amount),
                # Campo 16: Importe de impuestos internos
                self.format_amount(intern_tax_amount),
                # Campo 17: Código de Moneda
                str(currency_code),
                # Campo 18: Tipo de Cambio
                self.format_amount(currency_rate, padding=10, decimals=6),
                # Campo 19: Cantidad de alícuotas de IVA
                str(cant_alicuotas),
                # Campo 20: Código de operación.
                codigo_operacion,
            ]

            if self.type == "sale":
                row += [
                    # Campo 21: Otros Tributos
                    self.format_amount(other_taxes_amount),
                    # Campo 22: vencimiento comprobante
                    (
                        inv.l10n_latam_document_type_id.code
                        in [
                            "19", "20", "21", "16", "55", "81", "82", "83",
                            "110", "111", "112", "113", "114", "115", "116",
                            "117", "118", "119", "120", "201", "202", "203",
                            "206", "207", "208", "211", "212", "213",
                        ]
                        and "00000000"
                        or inv.invoice_date_due.strftime("%Y%m%d")
                    ),
                ]
            else:
                # Campo 21: Crédito Fiscal Computable
                if self.prorate_tax_credit:
                    if self.prorate_type == "global":
                        row.append(self.format_amount(0))
                    else:
                        raise ValidationError(
                            _(
                                "Para utilizar el prorrateo por comprobante:\n"
                                '1) Exporte los archivos sin la opción "Proratear '
                                'Crédito de Impuestos"\n2) Importe los mismos '
                                "en el aplicativo\n3) En el aplicativo de afip, "
                                "comprobante por comprobante, indique el valor "
                                'correspondiente en el campo "Crédito Fiscal '
                                'Computable"'
                            )
                        )
                else:
                    row.append(self.format_amount(vat_amount))

                liquido_type = inv.l10n_latam_document_type_id.code in [
                    "033", "058", "059", "060", "063",
                ]
                row += [
                    # Campo 22: Otros Tributos
                    self.format_amount(other_taxes_amount),
                    # Campo 23: CUIT Emisor / Corredor
                    self.format_amount(
                        liquido_type and inv.company_id.partner_id.ensure_vat() or 0,
                        padding=11,
                    ),
                    # Campo 24: Denominación Emisor / Corredor
                    (liquido_type and inv.company_id.name or "").ljust(30, " ")[:30],
                    # Campo 25: IVA Comisión
                    self.format_amount(0),
                ]
            res.append("".join(row))
        self.REGINFO_CV_CBTE = "\r\n".join(res)

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
