from odoo import models, fields, _
from odoo.exceptions import ValidationError
import base64
import io
import zipfile


class L10nArTaxSettlementWizard(models.TransientModel):
    _name = "l10n_ar.tax.settlement.wizard"
    _description = "Generación de Archivos de Liquidación de Impuestos"

    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario de Liquidación",
        domain=[("tax_settlement", "!=", False)],
        required=True,
    )
    
    # Result fields
    file_content = fields.Binary(string="Archivo Generado", readonly=True)
    file_name = fields.Char(string="Nombre del Archivo", readonly=True)

    def action_generate(self):
        self.ensure_one()
        
        # Search for lines
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('journal_id', '=', self.journal_id.id),
            ('parent_state', '=', 'posted'),
        ]
        
        # Depending on logic, we might need moves or move lines.
        # The original methods in account_journal.py (e.g., iibb_aplicado_files_values) take move_lines.
        lines = self.env['account.move.line'].search(domain)
        
        if not lines:
            raise ValidationError(_("No se encontraron movimientos para el período y diario seleccionados."))

        # Determine method to call based on settlement tax type
        # In the original, this was often determined by context or specialized reports.
        # Here we map the journal's settlement_tax (or similar) to the method.
        # Wait, the original account_journal.py had methods like `iibb_aplicado_files_values`.
        # How do we know which one to call?
        # In the original Enterprise code, this was likely done via the `account_tax_settlement` structure mapping.
        # In our ported `account_journal.py`, we have the methods directly.
        # We need a mapping or a convention.
        
        # Let's inspect the `settlement_tax` selection values we ported in `account_journal.py`:
        # "misiones", "sicore_aplicado", "iibb_sufrido", "iibb_aplicado", etc.
        # The methods are named like `iibb_aplicado_dgr_mendoza_files_values` in some cases,
        # or `iibb_aplicado_files_values`.
        
        method_name = f"{self.journal_id.settlement_tax}_files_values"
        
        if not hasattr(self.journal_id, method_name):
            # Fallback or specific mapping checks
            # In original code: 
            # "iibb_aplicado_dgr_mendoza" -> iibb_aplicado_dgr_mendoza_files_values
            # "iibb_aplicado" -> iibb_aplicado_files_values
            # "iibb_aplicado_act_7" -> iibb_aplicado_act_7_files_values (which calls iibb_aplicado_files_values(act_7=True))
            
            # Let's try to handle cases where simple string concatenation doesn't match
            if self.journal_id.settlement_tax == 'iibb_aplicado_act_7':
                method_name = 'iibb_aplicado_act_7_files_values'
            else:
                 raise ValidationError(_("No hay lógica de exportación definida para el tipo de liquidación: %s (Método esperado: %s)") % (self.journal_id.settlement_tax, method_name))

        if not hasattr(self.journal_id, method_name):
             raise ValidationError(_("El método %s no existe en el modelo de diario.") % method_name)

        # Call the method
        generator_method = getattr(self.journal_id, method_name)
        files_data = generator_method(lines)
        
        # files_data should be a list of dicts: [{'txt_filename': '...', 'txt_content': '...'}]
        
        if not files_data:
            raise ValidationError(_("El proceso no generó ningún contenido."))
            
        if len(files_data) == 1:
            data = files_data[0]
            content = data['txt_content']
            filename = data['txt_filename']
            encoded_content = base64.b64encode(content.encode('latin-1', errors='replace')) # Typical AFIP encoding or UTF-8? Usually Latin-1/Windows-1252 for legacy gov systems.
        else:
            # Zip multiple files
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for fver in files_data:
                    zip_file.writestr(fver['txt_filename'], fver['txt_content'].encode('latin-1', errors='replace'))
            
            filename = f"Liquidacion_{self.journal_id.name}_{self.date_from}_{self.date_to}.zip"
            encoded_content = base64.b64encode(buffer.getvalue())

        self.write({
            'file_content': encoded_content,
            'file_name': filename,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ar.tax.settlement.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
