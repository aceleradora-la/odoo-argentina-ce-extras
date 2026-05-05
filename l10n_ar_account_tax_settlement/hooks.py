import logging

_logger = logging.getLogger(__name__)

# Campos de liquidación que el hook se asegura de mantener sincronizados con la
# definición declarativa del chart template, también en diarios pre-existentes.
SETTLEMENT_FIELDS = (
    "tax_settlement",
    "settlement_tax",
    "settlement_partner_id",
    "settlement_account_id",
    "settlement_account_tag_ids",
)


def l10n_ar_account_tax_settlement_post_init_hook(env):
    """Crea (o completa) los diarios de liquidación para cada compañía AR.

    Bypass intencional del `_load_data` del chart template: ese loader corre con
    `noupdate=True` y, según la versión de Odoo, ha mostrado problemas escribiendo
    campos Selection custom (tax_settlement / settlement_tax). Acá usamos
    `create()` directamente y, si el diario ya existe, le completamos los campos
    de liquidación que estén vacíos para no perder la configuración manual del
    usuario.

    Multi-compañía: para cada company AR conmutamos el contexto vía
    `with_company` y `allowed_company_ids` así los `search`/`create` no son
    filtrados por la `ir.rule` de account.journal y caen en la company correcta
    aunque la sesión de instalación esté parada en otra."""

    ChartTemplate = env["account.chart.template"]

    ar_companies = env["res.company"].search(
        [("chart_template", "in", ("ar_base", "ar_ri", "ar_ex"))]
    )

    touched = []
    for company in ar_companies:
        journals_data = ChartTemplate.with_company(company)._get_latam_withholding_account_journal(
            template_code=company.chart_template, company=company
        )
        if not journals_data:
            continue

        Journal = (
            env["account.journal"]
            .with_company(company)
            .with_context(allowed_company_ids=[company.id])
        )

        for code, vals in journals_data.items():
            existing = (
                Journal.with_context(active_test=False, allowed_company_ids=[company.id])
                .search([("company_id", "=", company.id), ("code", "=", code)], limit=1)
            )
            if existing:
                # Completamos sólo los campos de liquidación que estén vacíos.
                update_vals = {
                    f: vals[f]
                    for f in SETTLEMENT_FIELDS
                    if f in vals and not existing[f]
                }
                if update_vals:
                    existing.write(update_vals)
            else:
                Journal.create(vals)

        touched.append(company.name)

    if touched:
        _logger.info(
            "Diarios de liquidación creados/actualizados para las compañías %s."
            % ", ".join(touched)
        )
