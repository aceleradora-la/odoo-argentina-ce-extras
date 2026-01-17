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
        # Verificar si la factura tiene un valor definido para FCE transmission
        if self.l10n_ar_afip_fce_transmission:
            # Mapear el valor del campo al texto completo que espera AFIP
            transmission_mapping = {
                'SCA': 'TRANSFERENCIA AL SISTEMA DE CIRCULACION ABIERTA',
                'ADC': 'AGENTE DE DEPOSITO COLECTIVO',
            }
            transmission_value = transmission_mapping.get(
                self.l10n_ar_afip_fce_transmission,
                self.l10n_ar_afip_fce_transmission  # Fallback al valor original si no está en el mapeo
            )
            # Si la factura tiene valor, usar ese valor en lugar del parámetro general
            # El método original busca en ir.config_parameter, pero nosotros lo sobrescribimos
            ws.AgregarOpcional(opcional_id=27, valor=transmission_value)
        else:
            # Si no hay valor en la factura, dejar que el método original use la configuración general
            pass
        
        # Llamar al método original (puede agregar otros opcionales o el 27 si no está definido en la factura)
        # Pero si ya agregamos el 27 arriba, el método original debería no agregarlo de nuevo o nuestro valor prevalece
        return super(AccountMove, self).wsfe_invoice_add_info(ws, invoice_info)
