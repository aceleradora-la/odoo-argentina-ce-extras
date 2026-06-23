from odoo import _, api, fields, models

# WSDL del padrón (mismo endpoint A5; getPersona_v2 corre sobre el servicio
# de Constancia de Inscripción, que requiere su propio token WSAA).
CONSTANCIA_WSDL = {
    "production": "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5?wsdl",
    "homologation": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5?wsdl",
}


class AfipwsConnection(models.Model):
    _inherit = "afipws.connection"

    afip_ws = fields.Selection(
        selection_add=[
            (
                "ws_sr_constancia_inscripcion",
                "ARCA - Constancia de Inscripción (Padrón, getPersona_v2)",
            )
        ],
        ondelete={"ws_sr_constancia_inscripcion": "cascade"},
    )

    @api.model
    def get_afip_ws_url(self, afip_ws, environment_type):
        if afip_ws == "ws_sr_constancia_inscripcion":
            url = CONSTANCIA_WSDL.get(environment_type)
            if not url:
                raise ValueError(_("Entorno AFIP desconocido: %s") % environment_type)
            return url
        return super().get_afip_ws_url(afip_ws, environment_type)
