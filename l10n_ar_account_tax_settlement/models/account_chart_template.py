##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
import logging

from odoo import models
from odoo.addons.account.models.chart_template import template

_logger = logging.getLogger(__name__)


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    @template(model="account.journal")
    def _get_latam_withholding_account_journal(self, template_code=False, company=False):
        """Crea diarios tipo 'varios' para liquidación de impuestos al instalar el plan
        de cuentas. Los diarios dependen de la condición fiscal de la compañía.

        Estructura de cada fila:
            (nombre, code, tax_settlement, settlement_tax, partner_ref, account_xmlid_suffix, tag_ref)

        Donde:
            - tax_settlement: gate del diario ("yes" o "allow_per_line").
            - settlement_tax: tipo de TXT que genera (vat, profits, sicore_aplicado, ...).
            - tag_ref: account.account.tag que se carga en settlement_account_tag_ids
              para que el dashboard sepa qué líneas liquida este diario.
        """
        company = company or self.env.company
        if company.chart_template not in ("ar_base", "ar_ri", "ar_ex"):
            return {}

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
                    "SICORE",
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
                    "IVA_SUF",
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

        res = {}
        for name, code, tax_settlement, settlement_tax, partner, account_suffix, tag in journals_data:
            if not account_suffix:
                _logger.info("Skip creation of journal %s: missing default account", name)
                continue
            existing_journal = (
                self.env["account.journal"]
                .with_context(active_test=False)
                .search([("company_id", "=", company.id), ("code", "=", code)], limit=1)
            )
            if existing_journal:
                continue
            account_ref = self.env.ref(
                "account.%s_%s" % (company.id, account_suffix), raise_if_not_found=False
            )
            vals = {
                "type": "general",
                "name": name,
                "code": code,
                "tax_settlement": tax_settlement,
                "settlement_tax": settlement_tax or False,
                "settlement_partner_id": partner.id if partner else False,
                "settlement_account_id": account_ref.id if account_ref else False,
                "company_id": company.id,
                "show_on_dashboard": False,
            }
            if tag:
                vals["settlement_account_tag_ids"] = [(6, 0, [tag.id])]
            res[code] = vals
        return res
