from odoo import _, models
from odoo.exceptions import ValidationError


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _get_settlement_tax(self, date=None):
        """Método puente para poder usar l10n_ar_tax_settlement_backward_comp
        Deprecar este método cuando se deprecie con l10n_ar_tax_settlement_backward_comp.
        El parámetro date es porque si la base no tiene instalado l10n_ar_tax_settlement_backward_comp
        entonces va a arrojar error si en alguna llamada al método se le pasa date.
        Ejemplo: método iibb_aplicado_agip_files_values de account_tax en módulo
        l10n_ar_account_tax_settlement hace la llamada tax = line._get_settlement_tax(date=date)"""
        self.ensure_one()
        return self.tax_line_id

    def get_tax_settlement_journal(self):
        """
        Metodo para obtener el diario de liquidacion arrojando mensajes
        de error (si corresponde)
        """
        settlement_journal = self.env["account.journal"]
        for rec in self:
            settlement_journal |= rec._get_tax_settlement_journal()
        if not settlement_journal:
            raise ValidationError(_("No encontramos diario de liquidación para los apuntes contables: %s") % self.ids)
        elif len(settlement_journal) != 1:
            raise ValidationError(
                _(
                    "Solo debe seleccionar líneas que se liquiden con un mismo "
                    "diario, las líneas seleccionadas (ids %s) se liquidan con "
                    "diarios %s"
                )
                % (self.ids, settlement_journal.ids)
            )
        return settlement_journal

    def _get_tax_settlement_journal(self):
        """
        This method return the journal that can settle this move line.
        This can be overwrited by other modules
        """
        self.ensure_one()
        # Para SICORE, buscar por tag
        tag_sicore = self.env.ref('l10n_ar_ux.tag_ret_perc_sicore_aplicada', raise_if_not_found=False)
        if tag_sicore and tag_sicore in (self.tax_repartition_line_id.tag_ids or []):
            # Buscar primero en la empresa exacta de la línea
            journal = self.env["account.journal"].search(
                [
                    ("company_id", "=", self.company_id.id),  # Empresa exacta
                    ("settlement_tax", "=", "sicore_aplicado"),
                ],
                limit=1,
            )
            # Si no encuentra, buscar en la empresa padre (solo si la línea es de una empresa hija)
            if not journal and self.company_id.parent_id:
                journal = self.env["account.journal"].search(
                    [
                        ("company_id", "=", self.company_id.parent_id.id),  # Empresa padre
                        ("settlement_tax", "=", "sicore_aplicado"),
                    ],
                    limit=1,
                )
            return journal
        # Para otros tipos, buscar por otros tags si es necesario
        # Por ahora retornamos vacío si no es SICORE
        return self.env["account.journal"]

    def get_tax_settlement_file(self, journal=None):
        """
        Metodo que encuentra el diario para liquidar los apuntes y devuelve
        los vals requeridos en el wizard
        """
        if not journal:
            journal = self.get_tax_settlement_journal()
        res = self.env["res.download_files_wizard"].action_get_files(
            journal.get_tax_settlement_files_values(self), journal.settlement_tax
        )
        return res

    def button_create_tax_settlement_entry(self):
        """
        Botón para liquidar una línea de impuesto individual
        Crea y publica el asiento de liquidación
        """
        self.ensure_one()
        journal = self.get_tax_settlement_journal()
        if not journal:
            raise ValidationError(_("No se encontró un diario de liquidación para esta línea."))
        
        # Crear el asiento de liquidación
        move = journal.create_tax_settlement_entry(self)
        move.action_post()
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asiento de Liquidación'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
