import html
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

try:  # zeep viene incluido en Odoo (odoo.tools.zeep)
    from odoo.tools.zeep import Client
    from odoo.tools.zeep.helpers import serialize_object
except ImportError:  # fallback al zeep del sistema
    from zeep import Client
    from zeep.helpers import serialize_object

_logger = logging.getLogger(__name__)

# idProvincia (ARCA) -> nombre de provincia
MAP_PROVINCIAS = {
    0: "CIUDAD AUTONOMA BUENOS AIRES",
    1: "BUENOS AIRES",
    2: "CATAMARCA",
    3: "CORDOBA",
    4: "CORRIENTES",
    5: "ENTRE RIOS",
    6: "JUJUY",
    7: "MENDOZA",
    8: "LA RIOJA",
    9: "SALTA",
    10: "SAN JUAN",
    11: "SAN LUIS",
    12: "SANTA FE",
    13: "SANTIAGO DEL ESTERO",
    14: "TUCUMAN",
    16: "CHACO",
    17: "CHUBUT",
    18: "FORMOSA",
    19: "MISIONES",
    20: "NEUQUEN",
    21: "LA PAMPA",
    22: "RIO NEGRO",
    23: "SANTA CRUZ",
    24: "TIERRA DEL FUEGO",
}


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Los campos actividades_padron / impuestos_padron y los modelos
    # afip.activity / afip.tax los provee l10n_ar_ux; acá solo los poblamos.

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _padron_clean_str(self, value):
        """ARCA devuelve algunos textos con entidades HTML (ej. ``&#209;`` por
        la Ñ). Las decodificamos y normalizamos espacios."""
        if not value or not isinstance(value, str):
            return value
        # ARCA a veces devuelve entidades doble-escapadas (ej. "&amp;#209;");
        # desescapamos hasta que el texto se estabilice.
        for _i in range(3):
            new = html.unescape(value)
            if new == value:
                break
            value = new
        return value.strip()

    @api.model
    def _padron_as_list(self, value):
        """ARCA devuelve un dict cuando hay un solo elemento y una lista cuando
        hay varios. Normalizamos siempre a lista."""
        if not value:
            return []
        return value if isinstance(value, list) else [value]

    # ------------------------------------------------------------------
    # Override: consulta a Padrón usando getPersona_v2 (ex A5 / ARCA)
    # ------------------------------------------------------------------
    def get_data_from_padron_afip(self):
        self.ensure_one()
        vat = self.ensure_vat()

        company = self.env.user.company_id
        # getPersona_v2 corre sobre el servicio de Constancia de Inscripción:
        # el token WSAA debe pedirse para ese servicio (no para ws_sr_padron_a5),
        # de lo contrario AFIP responde "Computador no autorizado".
        connection = company.get_connection("ws_sr_constancia_inscripcion")
        cuit_repr = company.partner_id.ensure_vat()

        error_msg = _(
            "No pudimos actualizar desde el Padrón de ARCA al contacto %s (%s).\n"
            "Recomendamos verificar manualmente en la página de ARCA.\n"
            "Obtuvimos este error:\n%s"
        )

        try:
            client = Client(connection.afip_ws_url)
            res = client.service.getPersona_v2(
                token=connection.token,
                sign=connection.sign,
                cuitRepresentada=cuit_repr,
                idPersona=vat,
            )
        except Exception as e:
            raise UserError(error_msg % (self.name, vat, e))

        res = serialize_object(res, dict) or {}
        # getPersona_v2 puede envolver la data; desempaquetamos si hace falta
        if not res.get("datosGenerales"):
            for wrapper in ("persona", "personaReturn"):
                if isinstance(res.get(wrapper), dict):
                    res = res[wrapper]
                    break

        data = res.get("datosGenerales") or {}
        if not data:
            raise UserError(error_msg % (self.name, vat, res))

        denominacion = data.get("razonSocial") or ", ".join(
            [p for p in [data.get("apellido", ""), data.get("nombre", "")] if p]
        )
        if not denominacion or denominacion == ", ":
            raise UserError(error_msg % (self.name, vat, "La AFIP no devolvió nombre"))

        domicilio = data.get("domicilioFiscal") or {}
        data_mt = res.get("datosMonotributo") or {}
        data_rg = res.get("datosRegimenGeneral") or {}
        estado_clave = data.get("estadoClave")

        # --- Impuestos activos ---
        impuestos_raw = self._padron_as_list(data_mt.get("impuesto")) + self._padron_as_list(
            data_rg.get("impuesto")
        )
        impuestos_raw = [i for i in impuestos_raw if i and i.get("estadoImpuesto") == "AC"]
        imp_codes = [str(i.get("idImpuesto")) for i in impuestos_raw if i.get("idImpuesto") is not None]

        # --- Actividades ---
        actividades_raw = self._padron_as_list(data_rg.get("actividad")) + self._padron_as_list(
            data_mt.get("actividadMonotributista")
        )
        actividades_raw = [a for a in actividades_raw if a and a.get("idActividad") is not None]

        tax_recs = self._padron_get_or_create(
            "afip.tax",
            [(str(i.get("idImpuesto")), self._padron_clean_str(i.get("descripcionImpuesto"))) for i in impuestos_raw],
        )
        act_recs = self._padron_get_or_create(
            "afip.activity",
            [
                (str(a.get("idActividad")), self._padron_clean_str(a.get("descripcionActividad")))
                for a in actividades_raw
            ],
        )

        # --- IVA por código de impuesto (no por el flag imp_iva, que viene roto) ---
        if "32" in imp_codes:
            imp_iva = "EX"
        elif "33" in imp_codes:
            imp_iva = "NI"
        elif "34" in imp_codes:
            imp_iva = "NA"
        else:
            imp_iva = "AC" if "30" in imp_codes else "NI"

        cat_mt = data_mt.get("categoriaMonotributo") or {}
        monotributo = "S" if cat_mt else "N"

        # --- Impuesto a las ganancias ---
        if {"10", "11"} & set(imp_codes):
            imp_ganancias = "AC"
        elif "12" in imp_codes:
            imp_ganancias = "EX"
        elif monotributo == "S":
            imp_ganancias = "NC"
        else:
            imp_ganancias = False

        id_provincia = domicilio.get("idProvincia")
        try:
            provincia = MAP_PROVINCIAS.get(int(id_provincia), "") if id_provincia not in (None, "") else ""
        except (TypeError, ValueError):
            provincia = ""

        vals = {
            "name": self._padron_clean_str(denominacion),
            "street": self._padron_clean_str(
                domicilio.get("direccion") or domicilio.get("localidad") or provincia
            ),
            "city": self._padron_clean_str(domicilio.get("localidad") or ""),
            "zip": domicilio.get("codPostal") or "",
            "actividades_padron": act_recs.ids,
            "impuestos_padron": tax_recs.ids,
            "estado_padron": estado_clave or "",
            "monotributo_padron": monotributo,
            "imp_iva_padron": imp_iva,
            "actividad_monotributo_padron": self._padron_clean_str(cat_mt.get("descripcionCategoria") or ""),
            "empleador_padron": "301" in imp_codes,
            "last_update_census": fields.Date.today(),
        }
        if imp_ganancias:
            vals["imp_ganancias_padron"] = imp_ganancias

        # --- Provincia ---
        if provincia:
            caba_codes = ["C", "CABA", "ABA"]
            if not domicilio.get("localidad"):
                state = self.env["res.country.state"].search(
                    [("code", "in", caba_codes), ("country_id.code", "=", "AR")], limit=1
                )
            else:
                state = self.env["res.country.state"].search(
                    [
                        ("name", "ilike", provincia),
                        ("code", "not in", caba_codes),
                        ("country_id.code", "=", "AR"),
                    ],
                    limit=1,
                )
            if state:
                vals["state_id"] = state.id

        # --- Tipo de responsabilidad AFIP ---
        if imp_iva == "NI" and monotributo == "S":
            vals["l10n_ar_afip_responsibility_type_id"] = self.env.ref("l10n_ar.res_RM").id
        elif imp_iva == "AC":
            vals["l10n_ar_afip_responsibility_type_id"] = self.env.ref("l10n_ar.res_IVARI").id
        elif imp_iva == "EX":
            vals["l10n_ar_afip_responsibility_type_id"] = self.env.ref("l10n_ar.res_IVAE").id
        else:
            _logger.info(
                "No pudimos inferir la responsabilidad AFIP desde padrón para %s (estado %s), "
                "hay que cargarla manualmente.",
                vat,
                estado_clave,
            )

        return vals

    @api.model
    def _padron_get_or_create(self, model_name, items):
        """items: lista de tuplas (code, name). Devuelve un recordset, creando
        los que falten. Se hace con sudo() porque el wizard corre con perfil
        de administración del sistema."""
        Model = self.env[model_name].sudo()
        result = Model.browse()
        for code, name in items:
            if not code:
                continue
            rec = Model.search([("code", "=", code)], limit=1)
            if not rec:
                rec = Model.create({"code": code, "name": name or code})
            result |= rec
        return result
