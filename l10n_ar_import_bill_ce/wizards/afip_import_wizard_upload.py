from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AfipImportWizardUpload(models.TransientModel):
    _name = "afip.import.wizard.upload"
    _description = "Wizard para subir archivo Excel de importación de facturas"

    company_id = fields.Many2one(
        "res.company", 
        required=True, 
        string="Compañía",
        default=lambda self: self.env.company
    )
    journal_id = fields.Many2one(
        "account.journal", 
        required=True, 
        string="Diario",
        domain="[('type', 'in', ['purchase', 'sale']), ('company_id', '=', company_id)]",
        help="Seleccione el diario de compras o ventas donde se importarán las facturas"
    )
    attachment_id = fields.Binary(
        string="Archivo Excel",
        required=True,
        help="Seleccione el archivo Excel exportado desde ARCA/AFIP",
    )
    attachment_name = fields.Char(string="Nombre del archivo")
    
    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Limpiar el diario cuando cambia la compañía"""
        if self.company_id:
            self.journal_id = False

    def action_upload(self):
        """Procesa el archivo subido y abre el wizard de importación"""
        self.ensure_one()

        if not self.attachment_id:
            raise UserError(_("Debe seleccionar un archivo para importar"))
        
        if not self.journal_id:
            raise UserError(_("Debe seleccionar un diario para importar las facturas"))

        # Validar que el diario sea válido para importación
        is_pos = getattr(self.journal_id, 'l10n_ar_is_pos', False) if hasattr(self.journal_id, 'l10n_ar_is_pos') else False
        
        if not (
            (self.journal_id.type == "purchase" or (self.journal_id.type == "sale" and not is_pos))
            and self.journal_id.company_id.country_code == "AR"
            and self.journal_id.company_id.l10n_ar_afip_responsibility_type_id.code == "1"
        ):
            raise UserError(
                _("Este diario no es válido para importar facturas. "
                  "Debe ser un diario de compras o ventas (no POS) para una empresa argentina con responsabilidad tipo 1.")
            )

        # Crear un attachment temporal
        attachment = self.env["ir.attachment"].create(
            {
                "name": self.attachment_name or "import_bills.xlsx",
                "datas": self.attachment_id,
                "res_model": "afip.import.wizard.upload",
                "res_id": self.id,
            }
        )

        # Llamar al método de importación del journal
        return self.journal_id.import_bills_from_xls(attachment)

