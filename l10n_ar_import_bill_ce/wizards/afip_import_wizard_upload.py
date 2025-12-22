from odoo import _, fields, models
from odoo.exceptions import UserError


class AfipImportWizardUpload(models.TransientModel):
    _name = "afip.import.wizard.upload"
    _description = "Wizard para subir archivo Excel de importación de facturas"

    journal_id = fields.Many2one("account.journal", required=True, string="Diario")
    company_id = fields.Many2one("res.company", required=True, string="Compañía")
    attachment_id = fields.Binary(
        string="Archivo Excel",
        required=True,
        help="Seleccione el archivo Excel exportado desde ARCA/AFIP",
    )
    attachment_name = fields.Char(string="Nombre del archivo")

    def action_upload(self):
        """Procesa el archivo subido y abre el wizard de importación"""
        self.ensure_one()

        if not self.attachment_id:
            raise UserError(_("Debe seleccionar un archivo para importar"))

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

