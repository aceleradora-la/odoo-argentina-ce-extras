##############################################################################
#
#    Copyright (C) 2015  ADHOC SA  (http://www.adhoc.com.ar)
#    All Rights Reserved.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
{
    "name": "Tax Settlements For Argentina (Community)",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "author": "ADHOC SA, Aceleradora-Latam",
    "website": "www.adhoc.com.ar",
    "license": "LGPL-3",
    "images": [],
    "depends": [
        "account",
        "l10n_ar",
        "l10n_ar_ux",
        "account_payment_pro_receiptbook",
        # Removed Enterprise deps: account_tax_settlement, l10n_ar_account_reports
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/inflation_adjustment_index.xml",
        "views/inflation_adjustmen_index_view.xml",
        "views/account_journal_view.xml",
        "views/l10n_ar_tax_settlement_wizard_view.xml",  # New Wizard view
        "security/ir.model.access.csv",
    ],
    "demo": [],
    "installable": True,
    "auto_install": False,
    "application": False,
}
