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
from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ar_afip_fce_transmission = fields.Selection(
        [
            ('SCA', 'SCA - TRANSFERENCIA AL SISTEMA DE CIRCULACION ABIERTA'),
            ('ADC', 'ADC - AGENTE DE DEPOSITO COLECTIVO'),
        ],
        string="Opción de transmisión FCE",
        copy=False,
        help="Modo de transmisión para Factura de Crédito Electrónica (FCE). "
             "Si no se define, se usa la configuración general."
    )

    def wsfe_invoice_add_info(self, ws, invoice_info):
        """
        Sobrescribe el método para priorizar el campo de la factura sobre la configuración general.
        Si la factura tiene un valor definido, lo usa. Si no, deja que el método original use la configuración general.
        """
        # Si la factura tiene un valor definido, temporalmente establecerlo en el parámetro de configuración
        # para que el método original lo use en lugar de buscar en la configuración general
        config_param_name = "l10n_ar_afipws_fe.fce_transmission"
        original_config_value = None
        
        if self.l10n_ar_afip_fce_transmission:
            # Guardar el valor original del parámetro de configuración
            config_param = self.env['ir.config_parameter'].sudo()
            original_config_value = config_param.get_param(config_param_name, "")
            
            # Temporalmente establecer el valor de la factura en el parámetro de configuración
            # El método original buscará este parámetro y usará el valor de la factura
            config_param.set_param(config_param_name, self.l10n_ar_afip_fce_transmission)
        
        # Llamar al método original que ahora usará el valor de la factura si existe
        res = super(AccountMove, self).wsfe_invoice_add_info(ws, invoice_info)
        
        # Restaurar el parámetro de configuración original si lo modificamos
        if self.l10n_ar_afip_fce_transmission:
            config_param = self.env['ir.config_parameter'].sudo()
            if original_config_value:
                config_param.set_param(config_param_name, original_config_value)
            else:
                # Si no había valor original, eliminar el parámetro
                config_param.set_param(config_param_name, "")
        
        return res
