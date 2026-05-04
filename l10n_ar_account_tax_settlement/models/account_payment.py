from odoo import _, api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    # IMPORTANTE: no redefinir campos genéricos usados por otros módulos (ej. Deudas).
    # Usamos un campo propio para el flujo de liquidación.
    tax_settlement_to_pay_move_line_ids = fields.Many2many(
        "account.move.line",
        string="Líneas a Pagar (Liquidación)",
        compute="_compute_tax_settlement_to_pay_move_line_ids",
        store=False,
        help="Líneas de asientos de liquidación a pagar (uso interno).",
    )
    # Campo para almacenar el ID del asiento de liquidación
    settlement_move_id = fields.Many2one(
        "account.move",
        string="Asiento de Liquidación",
        help="Asiento de liquidación que se está pagando",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        """Procesar to_pay_move_line_ids del contexto solo cuando las líneas pertenecen
        a un diario de liquidación. En otros flujos (Deudas, retenciones de cobranza,
        pagos genéricos) salimos sin tocar nada para no interferir con esos módulos."""
        res = super().default_get(fields_list)

        move_line_ids = self._context.get("default_to_pay_move_line_ids", [])
        if not move_line_ids:
            return res

        move_lines = self.env["account.move.line"].browse(move_line_ids)
        settlement_moves = move_lines.mapped("move_id").filtered(self._is_tax_settlement_move)
        if not settlement_moves:
            # Ninguna línea proviene de un diario de liquidación: no es nuestro flujo.
            return res

        valid_lines = move_lines.filtered(
            lambda l: not l.reconciled
            and l.move_id in settlement_moves
            and l.account_id.account_type in ("asset_receivable", "liability_payable")
        )
        if not valid_lines:
            return res

        if len(settlement_moves) == 1:
            res["settlement_move_id"] = settlement_moves.id

        if not res.get("partner_id"):
            partners = valid_lines.mapped("partner_id")
            if len(partners) == 1:
                res["partner_id"] = partners.id

        if not res.get("amount"):
            res["amount"] = sum(abs(line.balance) for line in valid_lines)

        # No tocamos `to_pay_move_line_ids` (puede pertenecer a otro módulo).
        res["tax_settlement_to_pay_move_line_ids"] = [(6, 0, valid_lines.ids)]
        return res

    def _is_tax_settlement_move(self, move):
        """True solo para asientos de diarios configurados como liquidación de impuestos."""
        move.ensure_one()
        journal = move.journal_id
        return bool(journal and (journal.tax_settlement or journal.settlement_tax))

    def _compute_tax_settlement_to_pay_move_line_ids(self):
        """Compute field para mostrar las líneas a pagar (liquidación)."""
        for payment in self:
            if payment.settlement_move_id:
                payment.tax_settlement_to_pay_move_line_ids = payment.settlement_move_id.line_ids.filtered(
                    lambda l: not l.reconciled
                    and l.account_id.account_type in ("asset_receivable", "liability_payable")
                )
            elif self._context.get("default_to_pay_move_line_ids"):
                payment.tax_settlement_to_pay_move_line_ids = self.env["account.move.line"].browse(
                    self._context["default_to_pay_move_line_ids"]
                )
            else:
                payment.tax_settlement_to_pay_move_line_ids = False

    def action_post(self):
        """Después de publicar el pago, reconciliar con las líneas del asiento de liquidación.
        Solo aplicamos esta lógica en el flujo de liquidación; en pagos/cobros estándar
        (ej. retenciones en cobranza de clientes) no debemos interferir."""
        res = super().action_post()

        if self.settlement_move_id and self._is_tax_settlement_move(self.settlement_move_id):
            settlement_lines = self.settlement_move_id.line_ids.filtered(
                lambda l: not l.reconciled
                and l.account_id.account_type in ("asset_receivable", "liability_payable")
                and l.partner_id == self.partner_id
            )

            payment_lines = self.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")
                and l.partner_id == self.partner_id
            )

            if payment_lines and settlement_lines:
                (payment_lines + settlement_lines).reconcile()

        return res
