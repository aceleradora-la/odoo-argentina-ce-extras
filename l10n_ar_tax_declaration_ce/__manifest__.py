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
    "version": "17.0.6.0.1",
    "category": "Accounting",
    "author": "Aceleradora-Latam",
    "website": "https://github.com/aceleradora-la/odoo-argentina-ce-extras",
    "license": "AGPL-3",
    "summary": "Extiende el Libro IVA (ingadhoc) con export IVA Simple (ZIP) y Cierre de Impuestos",
    "depends": [
        "account",
        "l10n_ar",
        # Libro IVA (account.vat.ledger) de ingadhoc, base de toda la pantalla.
        "l10n_ar_reports",
        # Reusamos el export IVA Simple (ZIP/CSV) existente.
        "l10n_ar_account_reports",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/account_vat_ledger_view.xml",
        "wizards/tax_closing_wizard_view.xml",
    ],
    "installable": True,
    "application": False,
}
