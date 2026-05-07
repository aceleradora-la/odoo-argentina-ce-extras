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
    "version": "17.0.1.0.0",
    "category": "Accounting",
    "author": "Aceleradora-Latam",
    "website": "https://github.com/ingadhoc",
    "license": "AGPL-3",
    "depends": [
        "account",
        "l10n_ar",
        # Reusamos el export de Libro IVA Digital (ZIP) existente.
        "l10n_ar_account_reports",
    ],
    # Nota: este módulo es compatible conceptualmente con Odoo 17/18,
    # pero este repo corre sobre rama 18.0. El backport a 17 se realiza
    # aplicando el mismo módulo en la rama 17.0 con ajustes mínimos si hicieran falta.
    "data": [
        "security/ir.model.access.csv",
        "views/menu.xml",
        "views/tax_declaration_wizard_view.xml",
        "views/tax_report_views.xml",
    ],
    "installable": True,
    "application": False,
}

