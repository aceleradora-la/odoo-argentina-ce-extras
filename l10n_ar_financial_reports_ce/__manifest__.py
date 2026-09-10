# -*- coding: utf-8 -*-
{
    "name": "Reportes Financieros Interactivos (Community)",
    "summary": "Libro Mayor, Libro Mayor de la Empresa y Cuentas Vencidas "
               "estilo Enterprise, en pantalla (OWL) con export PDF y Excel.",
    "version": "17.0.2.0.0",
    "category": "Accounting",
    "author": "Aceleradora-Latam",
    "website": "https://github.com/aceleradora-la/odoo-argentina-ce-extras",
    "license": "AGPL-3",
    "depends": [
        "account",
        "web",
    ],
    "external_dependencies": {
        "python": ["xlsxwriter"],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/pl_structure_data.xml",
        "reports/financial_report_templates.xml",
        "reports/financial_report_views.xml",
        "reports/pl_structure_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ar_financial_reports_ce/static/src/css/financial_report.css",
            "l10n_ar_financial_reports_ce/static/src/js/financial_report/financial_report.js",
            "l10n_ar_financial_reports_ce/static/src/js/financial_report/financial_report.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
