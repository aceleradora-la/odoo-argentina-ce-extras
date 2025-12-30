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
    "name": "Accounting Reports Customized for Argentina (Community)",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "author": "ADHOC SA, Aceleradora-Latam",
    "website": "www.adhoc.com.ar",
    "license": "AGPL-3",
    "images": [],
    "depends": [
        "account",
        "l10n_ar",
        # Removed Enterprise deps: account_reports, l10n_ar_reports
    ],
    "data": [
        "data/tags_data.xml",
        "data/account.account.tag.csv",
        "views/l10n_ar_vat_book_wizard_view.xml",
    ],
    "demo": [],
    "installable": True,
    "auto_install": False,
    "application": False,
    "post_init_hook": "_post_init_hook_configure_ar_account_tags",
}
