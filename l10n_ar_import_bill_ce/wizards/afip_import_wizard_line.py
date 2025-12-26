import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AfipImportWizardLine(models.TransientModel):
    _name = "afip.import.wizard.line"
    _description = "Línea de Factura Importada desde Excel"

    wizard_id = fields.Many2one("afip.import.wizard", required=True, ondelete="cascade")
    invoice_number = fields.Char("Número de Factura")
    partner_name = fields.Char("Proveedor")
    partner_vat = fields.Char("VAT del Proveedor")
    partner_identification_type = fields.Char("Tipo de Identificación")
    date_invoice = fields.Date("Fecha de Factura")
    currency = fields.Char("Moneda")
    currency_rate = fields.Float("Valor de cambio")
    amount_total = fields.Float("Total")
    document_type = fields.Char(string="Tipo de Documento")
    move_type = fields.Char(string="Tipo de Factura")
    exists = fields.Boolean("Ya Existe", compute="_compute_exists", store=True)
    neto_grav_iva_0 = fields.Float("Neto Gravado IVA 0%")
    iva_2_5 = fields.Float("IVA 2.5%")
    neto_grav_iva_2_5 = fields.Float("Neto Gravado IVA 2.5%")
    iva_5 = fields.Float("IVA 5%")
    neto_grav_iva_5 = fields.Float("Neto Gravado IVA 5%")
    iva_10_5 = fields.Float("IVA 10.5%")
    neto_grav_iva_10_5 = fields.Float("Neto Gravado IVA 10.5%")
    iva_21 = fields.Float("IVA 21%")
    neto_grav_iva_21 = fields.Float("Neto Gravado IVA 21%")
    iva_27 = fields.Float("IVA 27%")
    neto_grav_iva_27 = fields.Float("Neto Gravado IVA 27%")
    no_gravado = fields.Float()
    otros_tributos = fields.Float()
    exento = fields.Float()
    cae = fields.Char("CAE")

    @api.depends("invoice_number", "partner_vat")
    def _compute_exists(self):
        for line in self:
            if not line.invoice_number or not line.partner_vat:
                line.exists = False
                continue
                
            # Normalizar el número de factura (eliminar espacios)
            invoice_number = str(line.invoice_number).strip() if line.invoice_number else ""
            partner_vat = str(line.partner_vat).strip() if line.partner_vat else ""
            
            if not invoice_number or not partner_vat:
                line.exists = False
                continue
                
            # Determine move types based on journal type
            if line.wizard_id.journal_id.type == "sale":
                move_types = ["out_refund", "out_invoice"]
            else:
                move_types = ["in_refund", "in_invoice"]

            # Search using l10n_latam_document_number for exact match
            # This is the field where the invoice number is actually stored
            move_model = line.env["account.move"]
            
            # Buscar usando l10n_latam_document_number (método preferido)
            # Si el campo no existe o está vacío, la búsqueda no encontrará nada (correcto)
            domain = [
                ("move_type", "in", move_types),
                ("l10n_latam_document_number", "=", invoice_number),
                ("partner_id.vat", "=", partner_vat),
                ("company_id", "=", line.wizard_id.company_id.id),
            ]
            existing_invoice = move_model.search(domain, limit=1)
            
            # Si no encontramos y el campo podría estar vacío, usar name/display_name como fallback
            # pero verificando que el número completo esté presente (no solo coincidencia parcial)
            if not existing_invoice:
                # Buscar facturas del mismo proveedor y tipo
                domain_fallback = [
                    ("move_type", "in", move_types),
                    ("partner_id.vat", "=", partner_vat),
                    ("company_id", "=", line.wizard_id.company_id.id),
                ]
                candidates = move_model.search(domain_fallback, limit=100)
                
                # Verificar manualmente que el número esté en name o display_name
                # El número debe estar completo, no parcial (ej: "00001-00000539" no debe coincidir con "00001-000005390")
                for candidate in candidates:
                    name = candidate.name or ""
                    display_name = candidate.display_name or ""
                    
                    # Verificar que el número completo esté presente en name o display_name
                    if invoice_number in name or invoice_number in display_name:
                        # Verificar que no sea una coincidencia parcial usando regex
                        pattern = re.escape(invoice_number)
                        # Verificar que el número esté completo (no seguido de más dígitos)
                        # Debe estar precedido por guión o espacio, y no seguido de dígitos
                        if (re.search(r'[-\s]' + pattern + r'(?![0-9])', name) or \
                            re.search(r'[-\s]' + pattern + r'(?![0-9])', display_name) or \
                            name.endswith(invoice_number) or \
                            display_name.endswith(invoice_number)):
                            existing_invoice = candidate
                            break

            line.exists = bool(existing_invoice)

    def _get_partner_by_vat(self):
        """
        Busca el proveedor en la tabla de proveedores
        :param vat: CUIT del proveedor
        :return: id del proveedor
        """
        self.ensure_one()

        partner = self.env["res.partner"].search([("vat", "=", self.partner_vat)], limit=1)

        if not partner:
            identification_type = self.env["l10n_latam.identification.type"].search(
                [("name", "ilike", self.partner_identification_type)], limit=1
            )

            partner = self.env["res.partner"].create(
                {
                    "name": self.partner_name,
                    "vat": self.partner_vat,
                    "l10n_latam_identification_type_id": identification_type.id,
                    "company_type": "company",
                }
            )
            # Si el tipo de identificación es CUIT (código AFIP 80), intentamos actualizar los datos desde AFIP
            # Este método puede no estar disponible en Community, verificar si existe
            if partner.l10n_latam_identification_type_id.l10n_ar_afip_code == 80:
                if hasattr(partner, 'button_update_partner_data_from_afip'):
                    try:
                        partner.button_update_partner_data_from_afip()
                    except Exception:
                        # Si el método no está disponible o falla, continuar sin actualizar
                        pass

        return partner

    def _get_document_type(self):
        """
        Busca el tipo de factura en la tabla de tipos de documento
        :param invoice_type: Tipo de factura (A, B, C, etc)
        :return: id del tipo de documento
        """
        self.ensure_one()
        # Extract the number before the hyphen
        invoice_type_code = self.document_type.split(" - ")[0].strip()

        # Search for the document type in the model l10n_latam.document.type
        document_type = self.env["l10n_latam.document.type"].search(
            [("code", "=", invoice_type_code), ("country_id.code", "=", "AR")], limit=1
        )

        if not document_type:
            raise UserError(_("No document type found for code: %s") % invoice_type_code)

        return document_type

    def _get_currency(self):
        """
        Busca la moneda en la tabla de monedas
        :param currency: Moneda (ARS, USD, etc)
        :return: id de la moneda
        """
        # Extract the number before the hyphen
        if self.currency == "$":
            currency_id = self.env["res.currency"].search([("name", "=", "ARS")], limit=1)
        else:
            currency_id = self.env["res.currency"].search([("name", "=", self.currency)], limit=1)

        if not currency_id:
            raise UserError(_("No currency found for code: %s") % self.currency)

        return currency_id

    def _get_move_type(self):
        """
        Compute the move_type based on the document type and journal type.
        :return: move_type string
        """
        move_type = False
        document_type = self._get_document_type()
        is_sale = self.wizard_id.journal_id.type == "sale"

        if document_type.internal_type in ["invoice", "debit_note"]:
            move_type = "out_invoice" if is_sale else "in_invoice"
        elif document_type.internal_type == "credit_note":
            move_type = "out_refund" if is_sale else "in_refund"
        return move_type

    # Definimos la funcion que crea las lineas de factura
    # con el precio unitario y los impuestos correspondientes

    def _create_line(self, price_unit, tax_ids):
        partner = self._get_partner_by_vat()
        return (
            0,
            0,
            {
                "name": "Creado por importación de facturas",
                "quantity": 1.0,
                "price_unit": price_unit,
                "tax_ids": [(6, 0, tax_ids)],
                "partner_id": partner.id,
            },
        )

