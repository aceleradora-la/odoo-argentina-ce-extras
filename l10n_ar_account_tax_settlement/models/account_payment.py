from odoo import _, api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    # Campo para recibir las líneas a pagar desde el contexto
    to_pay_move_line_ids = fields.Many2many(
        "account.move.line",
        string="Líneas a Pagar",
        compute="_compute_to_pay_move_line_ids",
        store=False,
        help="Líneas de asientos de liquidación a pagar",
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
        """Procesar to_pay_move_line_ids del contexto"""
        res = super().default_get(fields_list)
        
        # Si viene to_pay_move_line_ids en el contexto, procesarlo
        move_line_ids = self._context.get("default_to_pay_move_line_ids", [])
        if move_line_ids:
            move_lines = self.env["account.move.line"].browse(move_line_ids)
            # Filtrar solo líneas válidas (no reconciliadas, cuentas por pagar)
            valid_lines = move_lines.filtered(
                lambda l: not l.reconciled 
                and l.account_id.account_type in ("asset_receivable", "liability_payable")
            )
            
            if valid_lines:
                # Obtener el asiento de liquidación (debe ser el mismo para todas las líneas)
                settlement_moves = valid_lines.mapped("move_id")
                if len(settlement_moves) == 1:
                    res["settlement_move_id"] = settlement_moves.id
                
                # Si no hay partner_id, obtenerlo de las líneas
                if not res.get("partner_id") and valid_lines:
                    partners = valid_lines.mapped("partner_id")
                    if len(partners) == 1:
                        res["partner_id"] = partners.id
                
                # Calcular el monto total si no está establecido
                if not res.get("amount"):
                    total = abs(sum(valid_lines.mapped("balance")))
                    res["amount"] = total
                
                # Guardar las líneas para uso posterior
                res["to_pay_move_line_ids"] = [(6, 0, valid_lines.ids)]
        
        return res

    def _compute_to_pay_move_line_ids(self):
        """Compute field para mostrar las líneas a pagar"""
        for payment in self:
            if payment._context.get("default_to_pay_move_line_ids"):
                payment.to_pay_move_line_ids = payment._context["default_to_pay_move_line_ids"]
            elif payment.settlement_move_id:
                # Si hay un asiento de liquidación, obtener sus líneas por pagar
                payment.to_pay_move_line_ids = payment.settlement_move_id.line_ids.filtered(
                    lambda l: not l.reconciled 
                    and l.account_id.account_type in ("asset_receivable", "liability_payable")
                )
            else:
                payment.to_pay_move_line_ids = False

    def action_post(self):
        """Después de publicar el pago, reconciliar con las líneas del asiento de liquidación"""
        res = super().action_post()
        
        # Si hay líneas a pagar, reconciliarlas con el pago
        if self.to_pay_move_line_ids:
            # Obtener las líneas del pago que corresponden a cuentas por pagar
            payment_lines = self.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")
                and l.partner_id == self.partner_id
            )
            
            if payment_lines and self.to_pay_move_line_ids:
                # Reconciliar las líneas
                (payment_lines + self.to_pay_move_line_ids).reconcile()
        
        return res

