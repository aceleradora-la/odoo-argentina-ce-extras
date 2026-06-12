# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
from io import BytesIO

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def create_document_from_attachment(self, attachment_ids=None):
        """
        Intercepta la importación desde el dashboard para archivos Excel de ARCA/AFIP.
        Si el archivo es un Excel y el diario es válido, redirige al proceso de importación del módulo.
        """
        # Si no hay attachments, usar el método original
        if not attachment_ids:
            return super().create_document_from_attachment(attachment_ids=attachment_ids)
        
        # Obtener los attachments
        attachments = self.env["ir.attachment"].browse(attachment_ids)
        
        # Verificar si alguno de los archivos es un Excel
        excel_extensions = ['.xlsx', '.xls']
        has_excel = any(
            attachment.name and any(attachment.name.lower().endswith(ext) for ext in excel_extensions)
            for attachment in attachments
        )
        
        # Si no es un Excel, dejar que el método original lo maneje
        if not has_excel:
            return super().create_document_from_attachment(attachment_ids=attachment_ids)
        
        # Intentar obtener el journal - puede venir en self o en el contexto
        journal = self
        if not journal:
            # Intentar obtener el journal del contexto
            journal_id = self._context.get('default_journal_id') or self._context.get('journal_id')
            if journal_id:
                journal = self.env['account.journal'].browse(journal_id)
        
        # Si aún no hay journal, buscar uno válido para importación
        if not journal:
            company = self.env.company
            if company.country_code == "AR" and company.l10n_ar_afip_responsibility_type_id.code == "1":
                # Buscar un journal de compras válido
                journal = self.env['account.journal'].search([
                    ('type', '=', 'purchase'),
                    ('company_id', '=', company.id)
                ], limit=1)
                if not journal:
                    # Si no hay journal de compras, buscar uno de ventas (no POS)
                    journal = self.env['account.journal'].search([
                        ('type', '=', 'sale'),
                        ('company_id', '=', company.id)
                    ], limit=1)
        
        # Si hay múltiples journals, usar el primero
        if journal and len(journal) > 1:
            journal = journal[0]
        
        # Si no hay journal válido, dejar que el método original lo maneje
        if not journal:
            return super().create_document_from_attachment(attachment_ids=attachment_ids)
        
        # Validar que el diario sea válido para importación
        is_pos = getattr(journal, 'l10n_ar_is_pos', False) if hasattr(journal, 'l10n_ar_is_pos') else False
        
        is_valid_journal = (
            (journal.type == "purchase" or (journal.type == "sale" and not is_pos))
            and journal.company_id.country_code == "AR"
            and journal.company_id.l10n_ar_afip_responsibility_type_id.code == "1"
        )
        
        # Si el diario no es válido, dejar que el método original lo maneje
        if not is_valid_journal:
            return super().create_document_from_attachment(attachment_ids=attachment_ids)
        
        # Si tenemos un journal válido y archivos Excel, intentar usar nuestro proceso de importación
        # El método import_bills_from_xls validará el formato y manejará errores
        try:
            # Savepoint: si la importación falla a mitad de camino (formato
            # inesperado, error SQL) revertimos sus escrituras parciales antes
            # de delegar en el flujo estándar.
            with self.env.cr.savepoint():
                return journal.import_bills_from_xls(attachments)
        except Exception:
            _logger.info("Fallo la importación AFIP del Excel, se delega al flujo estándar", exc_info=True)
            return super().create_document_from_attachment(attachment_ids=attachment_ids)

    def action_import_bills_from_xls(self):
        """Action to open file upload dialog for importing bills from Excel"""
        self.ensure_one()
        
        # Validar que el diario sea válido para importación
        # l10n_ar_is_pos puede no estar disponible en Community, verificar si existe
        is_pos = getattr(self, 'l10n_ar_is_pos', False) if hasattr(self, 'l10n_ar_is_pos') else False
        
        if not (
            (self.type == "purchase" or (self.type == "sale" and not is_pos))
            and self.company_id.country_code == "AR"
            and self.company_id.l10n_ar_afip_responsibility_type_id.code == "1"
        ):
            raise UserError(
                _("Este diario no es válido para importar facturas. "
                  "Debe ser un diario de compras o ventas (no POS) para una empresa argentina con responsabilidad tipo 1.")
            )
        
        return {
            "name": _("Importar Facturas desde Excel"),
            "type": "ir.actions.act_window",
            "res_model": "afip.import.wizard.upload",
            "target": "new",
            "views": [[False, "form"]],
            "context": {
                "default_journal_id": self.id,
                "default_company_id": self.company_id.id,
            },
        }

    def import_bills_from_xls(self, attachments):
        """Import bills from Excel attachments"""
        if not PANDAS_AVAILABLE:
            raise UserError(
                _("El módulo 'pandas' no está instalado. "
                  "Por favor, instálelo ejecutando: pip install pandas openpyxl")
            )
        
        # Asegurarse de que attachments sea un recordset
        if not isinstance(attachments, models.Model):
            attachments = self.env["ir.attachment"].browse(attachments if isinstance(attachments, (list, tuple)) else [attachments])
        
        # Crear el wizard una sola vez para todos los archivos
        wizard = self.env["afip.import.wizard"].create(
            {
                "journal_id": self.id,
                "company_id": self.company_id.id,
            }
        )
        
        all_line_vals = []
        
        for attachment in attachments:
            file_content = base64.b64decode(attachment.datas)
            df = pd.read_excel(BytesIO(file_content), engine="openpyxl")  # use openpyxl for .xlsx

            # El archivo tiene un header en la primera fila, lo eliminamos
            df.columns = df.iloc[0]
            df = df[1:].reset_index(drop=True)

            # Optimización: Convertir todas las fechas de una vez usando vectorización de pandas
            df["Fecha"] = pd.to_datetime(df["Fecha"], dayfirst=True).dt.date

            # Determinar las columnas según el tipo de diario
            # En ventas: "Nro. Doc. Receptor", en compras: "Nro. Doc. Emisor"
            if self.type == "sale":
                vat_column = "Nro. Doc. Receptor"
                type_column = "Tipo Doc. Receptor"
                name_column = "Denominación Receptor"
            else:
                vat_column = "Nro. Doc. Emisor"
                type_column = "Tipo Doc. Emisor"
                name_column = "Denominación Emisor"

            # Optimización: Convertir VAT a string de una vez
            df[vat_column] = df[vat_column].astype(int).astype(str)

            # Optimización: Generar número de factura usando vectorización
            df["Punto de Venta"] = df["Punto de Venta"].astype(int)
            df["Número Desde"] = df["Número Desde"].astype(int)
            df["invoice_number"] = (
                df["Punto de Venta"].astype(str).str.zfill(5) + "-" + df["Número Desde"].astype(str).str.zfill(8)
            )

            # Optimización: Convertir columnas numéricas de una vez
            numeric_columns = [
                "Imp. Total",
                "Tipo Cambio",
                "Neto No Gravado",
                "Op. Exentas",
                "Otros Tributos",
                "Neto Grav. IVA 0%",
                "IVA 2,5%",
                "Neto Grav. IVA 2,5%",
                "IVA 5%",
                "Neto Grav. IVA 5%",
                "IVA 10,5%",
                "Neto Grav. IVA 10,5%",
                "IVA 21%",
                "Neto Grav. IVA 21%",
                "IVA 27%",
                "Neto Grav. IVA 27%",
            ]

            existing_numeric_cols = [col for col in numeric_columns if col in df.columns]
            for col in existing_numeric_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            # Optimización: Renombrar columnas directamente en el DataFrame
            rename_dict = {
                "Fecha": "date_invoice",
                vat_column: "partner_vat",
                type_column: "partner_identification_type",
                name_column: "partner_name",
                "Moneda": "currency",
                "Tipo Cambio": "currency_rate",
                "Imp. Total": "amount_total",
                "Tipo": "document_type",
                "Neto No Gravado": "no_gravado",
                "Op. Exentas": "exento",
                "Otros Tributos": "otros_tributos",
                "Cód. Autorización": "cae",
                "Neto Grav. IVA 0%": "neto_grav_iva_0",
                "IVA 2,5%": "iva_2_5",
                "Neto Grav. IVA 2,5%": "neto_grav_iva_2_5",
                "IVA 5%": "iva_5",
                "Neto Grav. IVA 5%": "neto_grav_iva_5",
                "IVA 10,5%": "iva_10_5",
                "Neto Grav. IVA 10,5%": "neto_grav_iva_10_5",
                "IVA 21%": "iva_21",
                "Neto Grav. IVA 21%": "neto_grav_iva_21",
                "IVA 27%": "iva_27",
                "Neto Grav. IVA 27%": "neto_grav_iva_27",
            }
            df = df.rename(columns=rename_dict)

            # Optimización: Convertir directamente a lista de tuplas solo con campos válidos
            valid_fields = [
                "invoice_number",
                "date_invoice",
                "partner_vat",
                "partner_identification_type",
                "partner_name",
                "currency",
                "currency_rate",
                "amount_total",
                "document_type",
                "no_gravado",
                "exento",
                "otros_tributos",
                "cae",
                "neto_grav_iva_0",
                "iva_2_5",
                "neto_grav_iva_2_5",
                "iva_5",
                "neto_grav_iva_5",
                "iva_10_5",
                "neto_grav_iva_10_5",
                "iva_21",
                "neto_grav_iva_21",
                "iva_27",
                "neto_grav_iva_27",
            ]

            # Filtrar solo las columnas que existen en el modelo
            filtered_df = df[valid_fields]
            line_vals = [(0, 0, row) for row in filtered_df.to_dict(orient="records")]
            all_line_vals.extend(line_vals)
        
        # Escribir todas las líneas en el wizard una sola vez
        if all_line_vals:
            wizard.write({"line_ids": all_line_vals})

            # Determine wizard name based on journal type
            wizard_name = (
                "Importación de Facturas de Cliente" if self.type == "sale" else "Importación de Facturas de Proveedor"
            )

            return {
                "name": wizard_name,
                "type": "ir.actions.act_window",
                "res_model": "afip.import.wizard",
                "target": "new",
                "views": [[self.env.ref("l10n_ar_import_bill_ce.view_afip_import_wizard_form").id, "form"]],
                "res_id": wizard.id,
            }

