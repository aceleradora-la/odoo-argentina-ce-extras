from ast import literal_eval

from odoo import models


class ResPartnerUpdateFromPadronWizard(models.TransientModel):
    _inherit = "res.partner.update.from.padron.wizard"

    def _update(self):
        """Override del _update de l10n_ar_afipws.

        El wizard base guarda ``new_value`` como Char, por lo que al escribir
        los campos many2one (``l10n_ar_afip_responsibility_type_id`` y
        ``state_id``) pasa un string (ej. ``"5"``) en lugar de un int y Odoo
        no lo persiste. Acá casteamos esos campos con ``literal_eval`` igual que
        lo hace la versión enterprise (l10n_ar_edi_ux).
        """
        self.ensure_one()
        m2o_fields = ("state_id", "l10n_ar_afip_responsibility_type_id")
        vals = {}
        for field in self.field_ids:
            if field.field in ("impuestos_padron", "actividades_padron"):
                vals[field.field] = [(6, False, literal_eval(field.new_value))]
            elif field.field in m2o_fields:
                vals[field.field] = literal_eval(field.new_value)
            else:
                vals[field.field] = field.new_value
        self.partner_id.write(vals)
