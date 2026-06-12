import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AfipImportWizard(models.TransientModel):
    _name = "afip.import.wizard"
    _description = "Importador de Facturas de Proveedor desde Excel AFIP"

    line_ids = fields.One2many("afip.import.wizard.line", "wizard_id", string="LÃ­neas de Facturas de Facturas")
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

    @api.depends("line_ids.exists")
    def _compute_bills_to_create(self):
        for wizard in self:
            wizard.total_bills_to_create = len(wizard.line_ids.filtered(lambda l: not l.exists))

    @api.depends("line_ids.exists")
    def _compute_bills_exists(self):
        for wizard in self:
            wizard.total_bills_exists = len(wizard.line_ids.filtered(lambda l: l.exists))

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
        # Obtener todas las empresas relacionadas (padre e hijas)
        company_ids = [self.company_id.id]
        # Agregar empresa padre si existe
        if self.company_id.parent_id:
            company_ids.append(self.company_id.parent_id.id)
        # Agregar empresas hijas
        if self.company_id.child_ids:
            company_ids.extend(self.company_id.child_ids.ids)
        
        base_domain = [
            ("price_include", "=", False),
            ("type_tax_use", "=", tax_use_type),
            ("company_id", "in", company_ids),
        ]
        tax_iva_no_corresponde = self.env["account.tax"].search(
            base_domain + [("tax_group_id.l10n_ar_vat_afip_code", "=", "0")], limit=1
        )
        tax_iva_no_gravado = self.env["account.tax"].search(
            base_domain + [("tax_group_id.l10n_ar_vat_afip_code", "=", "1")], limit=1
        )
        
        # Buscar impuesto de Otros Tributos por código AFIP de tributo (campo de l10n_ar).
        tax_otros_tributos = self.env["account.tax"].search(
            base_domain + [("tax_group_id.l10n_ar_tribute_afip_code", "=", "99")], limit=1
        )

        # Si no se encontró, buscar por nombre del grupo de impuestos
        if not tax_otros_tributos:
            # Buscar grupo de impuestos con nombre que contenga "Otros Tributos" o "Otro Tributo"
            # Primero intentar sin filtro de país (más flexible)
            tribute_group = self.env["account.tax.group"].search([
                ("name", "ilike", "otro tributo"),
            ], limit=1)
            
            # Si no encuentra, intentar con filtro de país
            if not tribute_group:
                tribute_group = self.env["account.tax.group"].search([
                    ("name", "ilike", "otro tributo"),
                    ("country_id.code", "=", "AR"),
                ], limit=1)
            
            # Si encuentra el grupo, buscar el impuesto asociado
            if tribute_group:
                tax_otros_tributos = self.env["account.tax"].search(
                    base_domain + [("tax_group_id", "=", tribute_group.id)], limit=1
                )
            
            # Si aún no encuentra, buscar directamente por nombre del impuesto (último recurso)
            if not tax_otros_tributos:
                tax_otros_tributos = self.env["account.tax"].search(
                    base_domain + [("name", "ilike", "otro tributo")], limit=1
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
            if line.cae:
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

                if not tax_iva_no_corresponde:
                    raise UserError(
                        _(
                            "No se encontró un impuesto 'IVA No Corresponde' de tipo %s. "
                            "Cree un impuesto con el grupo de IVA código AFIP 0."
                        )
                        % tax_use_type
                    )
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
                    # Si no existe el wizard, Odoo recalculará automáticamente al guardar
                    # No necesitamos hacer nada adicional en Community Edition
                    pass

            # Si tiene otros tributos, agregamos una línea adicional con el impuesto
            if line.otros_tributos > 0:
                if not tax_otros_tributos:
                    # Buscar información de depuración
                    debug_info = []
                    # Buscar grupos de impuestos que puedan ser "Otros Tributos"
                    possible_groups = self.env["account.tax.group"].search([
                        ("name", "ilike", "tributo"),
                    ], limit=5)
                    if possible_groups:
                        debug_info.append("\nGrupos de impuestos encontrados con 'tributo' en el nombre:")
                        for group in possible_groups:
                            debug_info.append(f"  - {group.name} (ID: {group.id})")
                    
                    # Buscar impuestos que puedan ser "Otros Tributos"
                    possible_taxes = self.env["account.tax"].search([
                        ("name", "ilike", "tributo"),
                        ("company_id", "child_of", self.company_id.id),
                        ("type_tax_use", "=", tax_use_type),
                    ], limit=5)
                    if possible_taxes:
                        debug_info.append("\nImpuestos encontrados con 'tributo' en el nombre:")
                        for tax in possible_taxes:
                            debug_info.append(f"  - {tax.name} (ID: {tax.id}, Grupo: {tax.tax_group_id.name if tax.tax_group_id else 'Sin grupo'})")
                    
                    error_msg = _("No se encontró un impuesto de Otros Tributos.\n\n"
                                  "Para solucionar esto:\n"
                                  "1. Vaya a Contabilidad > Configuración > Impuestos > Grupos de Impuestos\n"
                                  "2. Busque o cree un grupo de impuestos llamado 'Otros Tributos' (o similar)\n"
                                  "3. Si el módulo l10n_ar está instalado, configure el código AFIP de tributo como '99'\n"
                                  "4. Cree un impuesto de compras/ventas asociado a ese grupo\n"
                                  "5. Asegúrese de que el impuesto esté activo y tenga el tipo correcto (%s)\n\n"
                                  "Valor de otros tributos en la factura: %s") % (tax_use_type, line.otros_tributos)
                    
                    if debug_info:
                        error_msg += "\n\n" + "\n".join(debug_info)
                    
                    raise UserError(error_msg)

                # Agregar línea de producto con el impuesto "Otros Tributos"
                # Si el impuesto es fijo (amount_type='fixed'), el precio debe ser 0
                # y el monto aparecerá en el resumen de impuestos
                # Si el impuesto es porcentual, necesitamos calcular la base correcta
                tax_amount_type = getattr(tax_otros_tributos, 'amount_type', 'percent')
                
                if tax_amount_type == 'fixed':
                    # Impuesto fijo: precio 0, el impuesto fijo se aplica automáticamente
                    price_unit = 0.0
                else:
                    # Impuesto porcentual: calcular la base para que el impuesto resulte en el monto deseado
                    # Si amount_type es 'percent' o 'division', calculamos la base
                    if tax_otros_tributos.amount == 0:
                        price_unit = line.otros_tributos
                    else:
                        # Base = Monto deseado / (1 + tasa/100) para impuestos incluidos
                        # O Base = Monto deseado / (tasa/100) para impuestos no incluidos
                        if tax_otros_tributos.price_include:
                            price_unit = line.otros_tributos / (1 + tax_otros_tributos.amount / 100)
                        else:
                            price_unit = line.otros_tributos / (tax_otros_tributos.amount / 100) if tax_otros_tributos.amount != 0 else line.otros_tributos
                
                move.write(
                    {
                        "line_ids": [
                            line._create_line(price_unit, [tax_otros_tributos.id])
                        ]
                    }
                )

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

