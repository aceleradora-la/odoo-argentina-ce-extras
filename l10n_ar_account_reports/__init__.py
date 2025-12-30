from . import models
from . import wizards
from odoo import api, SUPERUSER_ID


def _post_init_hook_configure_ar_account_tags(env):
    """Configure Argentine account tags for existing companies."""
    # This hook is intended to run after module installation
    # to apply tags to existing chart of accounts
    companies = env["res.company"].search([("chart_template", "in", ["ar_base", "ar_ri", "ar_ex"])])
    if companies:
        env["account.chart.template"]._l10n_ar_account_reports_setup_account_tags(companies)
