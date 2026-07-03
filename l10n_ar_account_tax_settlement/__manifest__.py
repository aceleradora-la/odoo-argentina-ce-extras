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
    "version": "17.0.1.2.0",
    "category": "Accounting",
    "author": "ADHOC SA, Aceleradora-Latam",
    "website": "www.adhoc.com.ar",
    "license": "AGPL-3",
    "images": [],
    "depends": [
        "account",
        "l10n_ar",
        "l10n_ar_ux",
        "account_payment_pro_receiptbook",
        # Removed Enterprise deps: account_tax_settlement, l10n_ar_account_reports
    ],
    "data": [
        "data/inflation_adjustment_index.xml",
        "views/inflation_adjustmen_index_view.xml",
        "views/account_journal_view.xml",
        "views/account_move_line_view.xml",
        "wizards/download_files_wizard_view.xml",
        "security/ir.model.access.csv",  # Load after wizards so models are registered
    ],
    "demo": [],
    "installable": True,
    "auto_install": False,
    "application": False,
    "post_init_hook": "l10n_ar_account_tax_settlement_post_init_hook",
}
