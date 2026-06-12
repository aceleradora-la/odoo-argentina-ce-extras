##############################################################################
#
#    Copyright (C) 2026
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
##############################################################################
{
    "name": "Declaración Fiscal Argentina (Community)",
    "version": "17.0.2.0.0",
    "category": "Accounting",
    "author": "Aceleradora-Latam",
    "website": "https://github.com/aceleradora-la/odoo-argentina-ce-extras",
    "license": "AGPL-3",
    "summary": "Libro de IVA argentino, exports PDF/XLSX/ZIP y Cierre de Impuestos para Community",
    "depends": [
        "account",
        "l10n_ar",
        # Reusamos el export de Libro IVA Digital (ZIP) existente.
        "l10n_ar_account_reports",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/vat_book_line_views.xml",
        "views/menu.xml",
        "views/tax_declaration_wizard_view.xml",
        "views/tax_report_views.xml",
        "wizards/tax_closing_wizard_view.xml",
        "reports/vat_book_report.xml",
    ],
    "installable": True,
    "application": False,
}
