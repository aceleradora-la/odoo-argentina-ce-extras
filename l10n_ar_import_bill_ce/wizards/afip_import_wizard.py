import math

from odoo import fields, models
from odoo.exceptions import UserError


class AfipImportWizard(models.TransientModel):
    _name = "afip.import.wizard"
    _description = "Importador de Facturas de Proveedor desde Excel AFIP"

    line_ids = fields.One2many("afip.import.wizard.line", "wizard_id", string="Líneas de Facturas")
    company_id = fields.Many2one("res.company", required=True)
    journal_id = fields.Many2one("account.journal", required=True)
    auto_validate = fields.Boolean(string="Autovalidar Facturas Importadas", default=False)
    total_bills_to_create = fields.Integer(
        compute="_compute_bills_to_create",
        string="Total de Facturas a Crear",
    )
    total_bills_exists = fields.Integer(
        compute="_compute_bills_exists",
        string="Total de Facturas Existentes",
    )

    def _compute_bills_to_create(self):
        self.total_bills_to_create = len(self.line_ids.filtered(lambda l: not l.exists))

    def _compute_bills_exists(self):
        self.total_bills_exists = len(self.line_ids.filtered(lambda l: l.exists))

    def action_confirm(self):
        if all(line.exists for line in self.line_ids):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Importación completada",
                    "message": "No se crearon facturas: todas las facturas requeridas ya existen.",
                    "type": "warning",
                    "sticky": False,
                },
            }

        new_moves = self.env["account.move"]
        # Determine tax use type based on journal type
        tax_use_type = "sale" if self.journal_id.type == "sale" else "purchase"
        # Buscar impuestos en la empresa actual y en empresas relacionadas (padre e hijas)
        # Usar child_of para incluir la empresa y sus empresas padre
        base_domain = [
            ("price_include", "=", False),
            ("company_id", "child_of", self.company_id.id),
            ("type_tax_use", "=", tax_use_type),
        ]
        tax_iva_no_corresponde = self.env["account.tax"].search(
            base_domain + [("tax_group_id.l10n_ar_vat_afip_code", "=", "0")], limit=1
        )
        tax_iva_no_gravado = self.env["account.tax"].search(
            base_domain + [("tax_group_id.l10n_ar_vat_afip_code", "=", "1")], limit=1
        )
        tax_otros_tributos = self.env["account.tax"].search(
            base_domain + [("tax_group_id.l10n_ar_tribute_afip_code", "=", "99")], limit=1
        )
        tax_iva_exento = self.env["account.tax"].search(
            base_domain + [("tax_group_id.l10n_ar_vat_afip_code", "=", "2")], limit=1
        )

        for line in self.line_ids.filtered(lambda l: not l.exists):
            partner = line._get_partner_by_vat()

            document_type = line._get_document_type()

            currency = line._get_currency()
            move_type = line._get_move_type()

            move_vals = {
                "move_type": move_type,
                "l10n_latam_document_type_id": document_type.id,
                "partner_id": partner.id,
                "invoice_date": line.date_invoice,
                "l10n_latam_document_number": line.invoice_number,
                "currency_id": currency.id,
                "journal_id": self.journal_id.id,
                "company_id": self.company_id.id,
                "line_ids": [],
            }
            # Agregar l10n_ar_afip_auth_code solo si el campo existe (puede no estar en Community)
            if hasattr(self.env["account.move"], "_fields") and "l10n_ar_afip_auth_code" in self.env["account.move"]._fields:
                move_vals["l10n_ar_afip_auth_code"] = line.cae

            # Agregamos la linea con IVA y otros tributos (si existen).
            vat_rates = [
                (2.5, line.iva_2_5, line.neto_grav_iva_2_5),
                (5.0, line.iva_5, line.neto_grav_iva_5),
                (10.5, line.iva_10_5, line.neto_grav_iva_10_5),
                (21.0, line.iva_21, line.neto_grav_iva_21),
                (27.0, line.iva_27, line.neto_grav_iva_27),
            ]

            for vat_rate, vat_amount, neto_amount in vat_rates:
                if not math.isnan(vat_amount) and vat_amount > 0 and not math.isnan(neto_amount) and neto_amount > 0:
                    # Search for the specific VAT tax
                    # Buscar primero en la empresa actual, luego en empresas relacionadas
                    iva_tax = self.env["account.tax"].search(
                        base_domain
                        + [
                            ("amount", "=", vat_rate),
                            ("tax_group_id.l10n_ar_vat_afip_code", "!=", False),
                        ],
                        order="company_id",  # Priorizar impuestos de la empresa actual
                        limit=1,
                    )

                    if iva_tax:
                        move_vals["line_ids"].append(line._create_line(neto_amount, [iva_tax.id]))
                    else:
                        raise UserError(
                            f"No se encontró un impuesto de IVA para la alícuota {vat_rate}%. "
                            "Revise si este impuesto esta deshabilitado."
                        )

            # Add line for "exento" if it has a value
            if not math.isnan(line.exento) and line.exento > 0:
                if not tax_iva_exento:
                    raise UserError(
                        "No se encontró un impuesto de IVA Exento. "
                        "Debe crear un impuesto de compras con el grupo 'IVA Exento'."
                    )
                move_vals["line_ids"].append(line._create_line(line.exento, [tax_iva_exento.id]))

            # Add line for "no gravado" if it has a value
            if not math.isnan(line.no_gravado) and line.no_gravado > 0:
                if not tax_iva_no_gravado:
                    raise UserError(
                        "No se encontró un impuesto de IVA No Gravado. "
                        "Debe crear un impuesto de compras con el grupo 'IVA No Gravado'."
                    )
                move_vals["line_ids"].append(line._create_line(line.no_gravado, [tax_iva_no_gravado.id]))

            # Handle case when no VAT lines were created
            if not move_vals["line_ids"]:
                # Si no encuentra IVA ni importe "No Gravado" agrega la linea como "IVA No Corresponde" o "IVA No Gravado"
                base_amount = line.amount_total
                if line.otros_tributos > 0:
                    base_amount -= line.otros_tributos

                move_vals["line_ids"].append(line._create_line(base_amount, [tax_iva_no_corresponde.id]))

            move = self.env["account.move"].create(move_vals)

            # Agregamos el rate despues de crear la factura, para que Odoo no lo recalcule
            if line.currency_rate and line.currency_rate != 1:
                # Verificar si existe el wizard de cambio de tasa (puede ser de un módulo adicional)
                if "account.move.change.rate" in self.env:
                    wizard = self.env["account.move.change.rate"].create(
                        {
                            "move_id": move.id,
                            "currency_rate": line.currency_rate,
                        }
                    )
                    if hasattr(wizard, "confirm"):
                        wizard.confirm()
                else:
                    # Si no existe el wizard, actualizar directamente la tasa usando el contexto
                    move.with_context(override_currency_rate=line.currency_rate)._recompute_dynamic_lines()

            # Si tiene otros tributos, agregamos una línea adicional con el impuesto
            if line.otros_tributos > 0:
                if not tax_otros_tributos:
                    raise UserError(
                        "No se encontró un impuesto de Otros Tributos. "
                        "Debe crear un impuesto de compras con el grupo de tributo 'Otros Tributos'."
                    )

                # Agregar línea de impuesto directamente a la factura
                # Obtener la cuenta de impuestos
                tax_account = (
                    tax_otros_tributos.invoice_repartition_line_ids.filtered(
                        lambda l: l.repartition_type == "tax"
                    )[:1].account_id
                    or move.journal_id.default_account_id
                )
                
                # Determinar si es crédito o débito según el tipo de movimiento
                is_credit = move.move_type in ["in_invoice", "out_refund"]
                
                # Crear nueva línea de impuesto
                move.write(
                    {
                        "line_ids": [
                            (
                                0,
                                0,
                                {
                                    "name": tax_otros_tributos.name,
                                    "partner_id": partner.id,
                                    "account_id": tax_account.id,
                                    "tax_base_amount": 0.0,
                                    "tax_repartition_line_id": tax_otros_tributos.invoice_repartition_line_ids.filtered(
                                        lambda l: l.repartition_type == "tax"
                                    )[:1].id,
                                    "tax_line_id": tax_otros_tributos.id,
                                    "credit": line.otros_tributos if is_credit else 0.0,
                                    "debit": line.otros_tributos if not is_credit else 0.0,
                                },
                            )
                        ]
                    }
                )
                # Recalcular los totales
                move._recompute_dynamic_lines(recompute_all_taxes=True)

            # Confirm the invoice only if auto_validate is True and the total matches line.amount_total
            if self.auto_validate and abs(move.amount_total - line.amount_total) <= 0.10 and line.amount_total > 0:
                move.action_post()

            new_moves += move

        # Determine title based on journal type
        title = (
            "Facturas de Cliente Importadas" if self.journal_id.type == "sale" else "Facturas de Proveedor Importadas"
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "name": title,
            "domain": [("id", "in", new_moves.ids)],
            "target": "current",
            "views": [
                [self.env.ref("l10n_ar_import_bill_ce.view_account_move_list_bill_import").id, "list"],
                [False, "form"],
            ],
        }

