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

    def _get_tax_row(self, invoice, base, code, tax_amount, impo=False):
        """Corrige un bug de l10n_ar_reports en el TXT del Libro IVA Digital
        (RG 3685) para comprobantes en moneda extranjera.

        `invoice._get_vat()` (l10n_ar, Community) devuelve BaseImp/Importe
        en la MONEDA DEL COMPROBANTE (amount_currency), pero el "Importe
        Total" del voucher (`_get_REGINFO_CV_CBTE`, archivo Vouchers_*.txt)
        usa `amount_total_signed`, que SIEMPRE está en moneda de compañía.
        Para facturas en USD/otra moneda esto desajusta el archivo
        Alicuots_*.txt exactamente por el tipo de cambio del comprobante, y
        el Portal IVA de AFIP lo rechaza con:
        "El Importe Total (X) no coincide con la suma de los demás montos (Y)".

        Convertimos a moneda de compañía antes de armar la fila; si el
        comprobante ya está en moneda de compañía, es un no-op.
        """
        if invoice.currency_id != invoice.company_currency_id:
            base = invoice.currency_id._convert(
                base, invoice.company_currency_id, invoice.company_id, invoice.date
            )
            tax_amount = invoice.currency_id._convert(
                tax_amount, invoice.company_currency_id, invoice.company_id, invoice.date
            )
        return super()._get_tax_row(invoice, base, code, tax_amount, impo=impo)

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
