import base64

from odoo import api, fields, models


class DownloadFilesWizard(models.TransientModel):
    _name = "res.download_files_wizard"
    _description = "Wizard genérico para descargar archivos"

    line_ids = fields.One2many(
        "res.download_files_wizard_line",
        "wizard_id",
        "Files",
        readonly=True,
    )

    @api.model
    def action_get_files(self, files_values, settlement_tax=None):
        # transformamos a binary y agregamos formato para campos o2m
        wizard = self.env["res.download_files_wizard"].create(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "txt_filename": x["txt_filename"],
                            "txt_binary": base64.b64encode(x["txt_content"].encode("latin-1", errors='replace')),
                        },
                    )
                    for x in files_values
                    if x.get("txt_content")
                ],
            }
        )

        return {
            "type": "ir.actions.act_window",
            "res_id": wizard.id,
            "res_model": wizard._name,
            "view_mode": "form",
            "target": "new",
        }


class DownloadFileWizardLine(models.TransientModel):
    _name = "res.download_files_wizard_line"
    _description = "Línea de wizard para descargar archivos"

    wizard_id = fields.Many2one(
        "res.download_files_wizard",
    )
    txt_filename = fields.Char(string="Nombre de Archivo")
    txt_binary = fields.Binary(string="Archivo", filename="txt_filename")

