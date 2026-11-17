import logging

from .models.account_chart_template import AR_CHART_TEMPLATES

_logger = logging.getLogger(__name__)


def ensure_tax_settlement_journals_all_companies(env):
    """Crea (o completa) los diarios de liquidación en todas las compañías AR,
    raíces y sucursales. Idempotente: se usa al instalar y en la migración."""
    ChartTemplate = env["account.chart.template"]
    companies = env["res.company"].search([("chart_template", "in", AR_CHART_TEMPLATES)])
    touched = [
        company.name
        for company in companies
        if ChartTemplate._l10n_ar_ensure_tax_settlement_journals(company)
    ]
    if touched:
        _logger.info(
            "Diarios de liquidación creados/actualizados para las compañías %s.", ", ".join(touched))
    return touched


def l10n_ar_account_tax_settlement_post_init_hook(env):
    ensure_tax_settlement_journals_all_companies(env)
