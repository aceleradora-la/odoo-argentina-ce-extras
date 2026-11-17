##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
import logging

from odoo import models
from odoo.addons.account.models.chart_template import template

_logger = logging.getLogger(__name__)

AR_CHART_TEMPLATES = ("ar_base", "ar_ri", "ar_ex")

# Campos de liquidación que se completan en diarios pre-existentes (solo si están
# vacíos, para no pisar la configuración manual del usuario).
SETTLEMENT_FIELDS = (
    "tax_settlement",
    "settlement_tax",
    "settlement_partner_id",
    "settlement_account_id",
    "settlement_account_tag_ids",
)


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _get_latam_withholding_journals_definition(self, template_code):
        """Definición de los diarios de liquidación según la condición fiscal.

        Estructura de cada fila:
            (nombre, code, tax_settlement, settlement_tax, partner, account_xmlid, tag)

        Donde:
            - tax_settlement: gate del diario ("yes" o "allow_per_line").
            - settlement_tax: tipo de TXT que genera (vat, profits, sicore_aplicado, ...).
            - account_xmlid: xmlid de plantilla de la cuenta (sin prefijo de compañía).
            - tag: account.account.tag que se carga en settlement_account_tag_ids
              para que el tablero sepa qué líneas liquida este diario.
        """
        journals_data = [
            (
                "Liquidación de IIBB",
                "IIBB",
                "allow_per_line",
                "iibb_sufrido",
                self.env.ref("l10n_ar.par_iibb_pagar", raise_if_not_found=False),
                "base_iibb_a_pagar",
                self.env.ref("l10n_ar_ux.tax_tag_a_cuenta_iibb", raise_if_not_found=False),
            ),
        ]
        if template_code == "ar_ri":
            journals_data.append(
                (
                    "Liquidación de IVA",
                    "IVA",
                    "yes",
                    "vat",
                    self.env.ref("l10n_ar.partner_afip", raise_if_not_found=False),
                    "ri_iva_saldo_a_pagar",
                    self.env.ref("l10n_ar_ux.tax_tag_a_cuenta_iva", raise_if_not_found=False),
                )
            )

        if template_code in ("ar_ri", "ar_ex"):
            journals_data += [
                (
                    "Liquidación de Ganancias",
                    "GAN",
                    "yes",
                    "profits",
                    self.env.ref("l10n_ar.partner_afip", raise_if_not_found=False),
                    "base_impuesto_ganancias_a_pagar",
                    self.env.ref("l10n_ar_ux.tax_tag_a_cuenta_ganancias", raise_if_not_found=False),
                ),
                (
                    "Liquidación SICORE Aplicado",
                    # account.journal.code tiene size=5: "SICORE" se guardaba como
                    # "SICOR" y la búsqueda por código nunca encontraba el diario.
                    "SICOR",
                    "allow_per_line",
                    "sicore_aplicado",
                    self.env.ref("l10n_ar.partner_afip", raise_if_not_found=False),
                    "ri_retencion_sicore_a_pagar",
                    self.env.ref("l10n_ar_ux.tag_ret_perc_sicore_aplicada", raise_if_not_found=False),
                ),
                (
                    "Liquidación IIBB Aplicado",
                    "IB_AP",
                    "allow_per_line",
                    False,  # iibb_aplicado (AGIP/ARBA/API/Mendoza/SIRCAR), debe elegirse según provincia
                    self.env.ref("l10n_ar.par_iibb_pagar", raise_if_not_found=False),
                    "ri_retencion_iibb_a_pagar",
                    self.env.ref("l10n_ar_ux.tag_ret_perc_iibb_aplicada", raise_if_not_found=False),
                ),
                (
                    "Liquidación IVA Ret/Perc Sufridas",
                    "IVA_S",  # máximo 5 caracteres (ver SICOR)
                    "allow_per_line",
                    "retenciones_iva",
                    False,  # no hay un agente de retención único: es crédito propio, no una deuda a un tercero
                    # Reutiliza la cuenta de IVA a favor/saldo técnico: retenciones y
                    # percepciones de IVA sufridas son crédito fiscal, igual que el
                    # saldo a favor del cierre de IVA. Cambiar si se prefiere una
                    # cuenta dedicada.
                    "ri_iva_saldo_a_pagar",
                    self.env.ref("l10n_ar_account_tax_settlement.tag_ret_perc_iva_sufrida", raise_if_not_found=False),
                ),
            ]
        return journals_data

    @template(model="account.journal")
    def _get_latam_withholding_account_journal(self, template_code=False, company=False):
        """Diarios de liquidación como datos de plantilla (carga del plan de cuentas
        en compañías raíz).

        La cuenta se devuelve como xmlid de plantilla (p. ej. "ri_retencion_sicore_a_pagar")
        y la resuelve `_load_data` DESPUÉS de crear las cuentas. Antes se buscaba con
        `env.ref("account.<id>_<xmlid>")` al armar los datos, cuando las cuentas de una
        compañía nueva todavía no existen, y el diario quedaba sin cuenta de liquidación.

        Ojo: en sucursales (company.parent_id) `_load` descarta todos los datos de
        plantilla salvo res.company, así que esta función no alcanza: los diarios de
        las sucursales los crea `_post_load_data` con
        `_l10n_ar_ensure_tax_settlement_journals`.
        """
        company = company or self.env.company
        if company.chart_template not in AR_CHART_TEMPLATES:
            return {}

        res = {}
        for name, code, tax_settlement, settlement_tax, partner, account_xmlid, tag in (
            self._get_latam_withholding_journals_definition(template_code or company.chart_template)
        ):
            if not account_xmlid:
                _logger.info("Skip creation of journal %s: missing default account", name)
                continue
            vals = {
                "type": "general",
                "name": name,
                "code": code,
                "tax_settlement": tax_settlement,
                "settlement_tax": settlement_tax or False,
                "settlement_partner_id": partner.id if partner else False,
                "settlement_account_id": account_xmlid,
                "show_on_dashboard": False,
            }
            if tag:
                vals["settlement_account_tag_ids"] = [(6, 0, [tag.id])]
            res[code] = vals
        return res

    def _l10n_ar_ensure_tax_settlement_journals(self, company):
        """Crea (o completa) los diarios de liquidación de una compañía AR.

        Funciona para compañías raíz y para sucursales. Si el diario ya existe en la
        compañía, solo completa los campos de liquidación vacíos. Usa `create()`
        directo porque el loader de plantillas corre con noupdate y, según la versión,
        no escribe bien los Selection custom (tax_settlement / settlement_tax).

        :return: True si creó o modificó algún diario.
        """
        if company.chart_template not in AR_CHART_TEMPLATES:
            return False

        # Contexto de la compañía: así `self.ref()` resuelve la cuenta en la compañía
        # o, si es sucursal, en la raíz (las sucursales comparten el plan de cuentas)
        # y las ir.rule no filtran los diarios.
        ChartTemplate = self.with_company(company).with_context(allowed_company_ids=[company.id])
        Journal = ChartTemplate.env["account.journal"]

        changed = False
        for name, code, tax_settlement, settlement_tax, partner, account_xmlid, tag in (
            ChartTemplate._get_latam_withholding_journals_definition(company.chart_template)
        ):
            account = account_xmlid and ChartTemplate.ref(account_xmlid, raise_if_not_found=False)
            if account_xmlid and not account:
                _logger.warning(
                    "Diario %s de %s: no se encontró la cuenta de plantilla %s; "
                    "queda sin cuenta de liquidación.", code, company.name, account_xmlid)
            vals = {
                "type": "general",
                "name": name,
                "code": code,
                "tax_settlement": tax_settlement,
                "settlement_tax": settlement_tax or False,
                "settlement_partner_id": partner.id if partner else False,
                "settlement_account_id": account.id if account else False,
                "company_id": company.id,
                "show_on_dashboard": False,
            }
            if tag:
                vals["settlement_account_tag_ids"] = [(6, 0, [tag.id])]

            # Solo diarios de ESTA compañía: un diario de la raíz con el mismo código
            # no le sirve a la sucursal (cada una liquida su propio CUIT).
            existing = Journal.with_context(active_test=False).search(
                [("company_id", "=", company.id), ("code", "=", code)], limit=1)
            if existing:
                update_vals = {
                    f: vals[f] for f in SETTLEMENT_FIELDS if vals.get(f) and not existing[f]
                }
                if update_vals:
                    existing.write(update_vals)
                    changed = True
            else:
                Journal.create(vals)
                changed = True
        return changed

    def _post_load_data(self, template_code, company, template_data):
        res = super()._post_load_data(template_code, company, template_data)
        company = company or self.env.company
        # Cubre compañías nuevas (raíz o sucursal) y recargas del plan de cuentas.
        self._l10n_ar_ensure_tax_settlement_journals(company)
        return res
