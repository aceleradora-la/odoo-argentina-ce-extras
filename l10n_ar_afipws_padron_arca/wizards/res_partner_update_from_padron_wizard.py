from ast import literal_eval

from odoo import api, models

# Campos adicionales que el wizard base no contempla en su dominio
EXTRA_FIELDS = [
    "state_id",
    "actividades_padron",
    "impuestos_padron",
    "estado_padron",
    "monotributo_padron",
    "imp_iva_padron",
    "imp_ganancias_padron",
    "actividad_monotributo_padron",
    "empleador_padron",
]

# Campos booleanos: el wizard guarda new_value como Char ("True"/"False"),
# por lo que hay que castearlos para que no se graben siempre como verdadero.
BOOL_FIELDS = ("empleador_padron",)


class ResPartnerUpdateFromPadronWizard(models.TransientModel):
    _inherit = "res.partner.update.from.padron.wizard"

    @api.model
    def _get_domain(self):
        """Amplía la lista de campos actualizables del wizard base para incluir
        provincia, actividades e impuestos del padrón."""
        domain = super()._get_domain()
        new_domain = []
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "name" and leaf[1] == "in":
                names = list(leaf[2]) + [f for f in EXTRA_FIELDS if f not in leaf[2]]
                new_domain.append(("name", "in", names))
            else:
                new_domain.append(leaf)
        return new_domain

    def _update(self):
        """Override del _update de l10n_ar_afipws.

        El wizard base guarda ``new_value`` como Char, por lo que al escribir
        los campos many2one (``l10n_ar_afip_responsibility_type_id`` y
        ``state_id``) pasa un string (ej. ``"5"``) en lugar de un int y Odoo
        no lo persiste. Acá casteamos esos campos con ``literal_eval`` igual que
        lo hace la versión enterprise (l10n_ar_edi_ux)."""
        self.ensure_one()
        m2o_fields = ("state_id", "l10n_ar_afip_responsibility_type_id")
        vals = {}
        for field in self.field_ids:
            if field.field in ("impuestos_padron", "actividades_padron"):
                vals[field.field] = [(6, False, literal_eval(field.new_value))]
            elif field.field in m2o_fields or field.field in BOOL_FIELDS:
                vals[field.field] = literal_eval(field.new_value)
            else:
                vals[field.field] = field.new_value
        self.partner_id.write(vals)
