##############################################################################
#
#    Copyright (C) 2025  Aceleradora-Latam
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
    "name": "AFIP FCE Transmission Mode Extension",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localization",
    "summary": "Permite elegir modo de transmisión FCE (SCA/ADC) por factura individual",
    "description": """
        Extensión para l10n_ar_afipws_fe que permite elegir el modo de transmisión
        (SCA/ADC) para Facturas de Crédito Electrónica de forma individual por factura,
        en lugar de usar solo la configuración general.
        
        Características:
        - Campo en la factura para seleccionar SCA o ADC
        - Prioriza el valor de la factura sobre la configuración general
        - Visible solo para facturas de crédito electrónica (FCE)
    """,
    "author": "Aceleradora-Latam",
    "website": "https://github.com/aceleradora-la/odoo-argentina-ce-extras",
    "license": "AGPL-3",
    "depends": [
        "account",
        "l10n_ar_afipws_fe",
    ],
    "data": [
        "views/account_move_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
