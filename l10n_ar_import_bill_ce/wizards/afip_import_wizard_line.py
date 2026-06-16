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
        # Una sola búsqueda por wizard: con archivos de ARCA de cientos de líneas,
        # buscar facturas línea por línea era O(n) consultas con limit=100 cada una.
        for wizard in self.mapped("wizard_id"):
            lines = self.filtered(lambda l: l.wizard_id == wizard)
            valid_lines = lines.filtered(
                lambda l: l.invoice_number and str(l.invoice_number).strip()
                and l.partner_vat and str(l.partner_vat).strip()
            )
            (lines - valid_lines).exists = False
            if not valid_lines:
                continue

            if wizard.journal_id.type == "sale":
                move_types = ["out_refund", "out_invoice"]
            else:
                move_types = ["in_refund", "in_invoice"]

            numbers = list({str(l.invoice_number).strip() for l in valid_lines})
            vats = list({str(l.partner_vat).strip() for l in valid_lines})
            candidates = self.env["account.move"].search(
                [
                    ("move_type", "in", move_types),
                    ("partner_id.vat", "in", vats),
                    ("company_id", "=", wizard.company_id.id),
                    ("l10n_latam_document_number", "in", numbers),
                ]
            )
            # Normalizamos espacios igual que antes para evitar falsos negativos.
            existing_keys = {
                (str(m.partner_id.vat).strip(), str(m.l10n_latam_document_number).strip())
                for m in candidates
            }
            for line in valid_lines:
                key = (str(line.partner_vat).strip(), str(line.invoice_number).strip())
                line.exists = key in existing_keys

    def _get_partner_by_vat(self):
        """
        Busca el proveedor en la tabla de proveedores
        :param vat: CUIT del proveedor
        :return: id del proveedor
        """
        self.ensure_one()

        # Solo partners raíz (no contactos hijos) visibles para la compañía del wizard.
        partner = self.env["res.partner"].search(
            [
                ("vat", "=", self.partner_vat),
                ("parent_id", "=", False),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.wizard_id.company_id.id),
            ],
            limit=1,
        )

        if not partner:
            identification_type = self.env["l10n_latam.identification.type"].search(
                [("name", "ilike", self.partner_identification_type)], limit=1
            )

            vals = {
                "name": self.partner_name,
                "vat": self.partner_vat,
                "l10n_latam_identification_type_id": identification_type.id,
                "company_type": "company",
            }
            # Inferimos la responsabilidad AFIP a partir de la letra del comprobante
            # (lo que Enterprise resuelve vía padrón). Si luego se actualiza desde
            # AFIP, ese dato más fiable sobrescribe esta inferencia.
            responsibility = self._get_afip_responsibility_type()
            if responsibility:
                vals["l10n_ar_afip_responsibility_type_id"] = responsibility.id

            partner = self.env["res.partner"].create(vals)
            # Si el tipo de identificación es CUIT (código AFIP 80), intentamos actualizar los datos desde AFIP
            # Este método puede no estar disponible en Community, verificar si existe
            # l10n_ar_afip_code es Char: comparar como string.
            if str(partner.l10n_latam_identification_type_id.l10n_ar_afip_code) == "80":
                if hasattr(partner, 'button_update_partner_data_from_afip'):
                    try:
                        partner.button_update_partner_data_from_afip()
                    except Exception:
                        # Si el método no está disponible o falla, continuar sin actualizar
                        pass

        return partner

    def _get_afip_responsibility_type(self):
        """
        Infiere la responsabilidad AFIP del proveedor según la letra del
        comprobante que emitió:
          - A / B / M  -> IVA Responsable Inscripto (código 1)
          - C          -> Responsable Monotributo (código 6)
        Devuelve el registro l10n_ar.afip.responsibility.type o False si no se
        puede determinar.
        """
        self.ensure_one()
        letter = self._get_document_type().l10n_ar_letter
        code = {"A": "1", "B": "1", "M": "1", "C": "6"}.get(letter)
        if not code:
            return False
        return self.env["l10n_ar.afip.responsibility.type"].search(
            [("code", "=", code)], limit=1
        )

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

    def _get_analytic_distribution(self, partner):
        """
        Propone la distribución analítica copiándola del último apunte de
        compra posteado de este proveedor que tenga una distribución cargada.
        Replica para la analítica lo que Odoo ya hace con la cuenta contable
        (autocompletar a partir de los últimos registros del proveedor), algo
        que en Community no se hace solo.
        Devuelve el dict de analytic_distribution o False.
        """
        self.ensure_one()
        AccountMoveLine = self.env["account.move.line"]
        if "analytic_distribution" not in AccountMoveLine._fields:
            return False
        last_line = AccountMoveLine.search(
            [
                ("partner_id", "=", partner.id),
                ("company_id", "=", self.wizard_id.company_id.id),
                ("parent_state", "=", "posted"),
                ("move_id.move_type", "in", ["in_invoice", "in_refund"]),
                ("display_type", "=", "product"),
                ("analytic_distribution", "!=", False),
            ],
            order="date desc, id desc",
            limit=1,
        )
        return last_line.analytic_distribution or False

    def _create_line(self, price_unit, tax_ids):
        partner = self._get_partner_by_vat()
        line_vals = {
            "name": "Creado por importación de facturas",
            "quantity": 1.0,
            "price_unit": price_unit,
            "tax_ids": [(6, 0, tax_ids)],
            "partner_id": partner.id,
        }
        distribution = self._get_analytic_distribution(partner)
        if distribution:
            line_vals["analytic_distribution"] = distribution
        return (0, 0, line_vals)

