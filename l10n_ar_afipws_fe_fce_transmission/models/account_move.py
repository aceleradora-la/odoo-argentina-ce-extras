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
        El método original ya agrega el opcional 27 si está en la configuración global.
        Necesitamos reemplazarlo si la factura tiene un valor definido.
        """
        # Llamar al método original primero
        res = super(AccountMove, self).wsfe_invoice_add_info(ws, invoice_info)
        
        # Verificar si es una factura FCE
        # El código de FCE suele ser 111 (Factura de Crédito Electrónica MiPyMEs)
        is_fce = False
        if self.l10n_latam_document_type_id:
            # Verificar si el tipo de documento es FCE
            # Puede ser código 111 o verificar si tiene algún campo que lo identifique
            doc_code = self.l10n_latam_document_type_id.code
            # FCE puede ser código 111, pero también verificar otros códigos relacionados
            # Códigos comunes de FCE: 111 (FCE), 112 (FCE débito), 113 (FCE crédito), 114 (FCE anulación)
            # También incluye variantes: 201, 202, 203, 206, 207, 208
            if doc_code in ['111', '112', '113', '114', '201', '202', '203', '206', '207', '208']:
                is_fce = True
        
        # Si es FCE y tiene un valor definido en la factura, usar ese valor
        if is_fce and self.l10n_ar_afip_fce_transmission:
            # Remover el opcional 27 si ya fue agregado por el método original
            if 'Opcionales' in invoice_info:
                invoice_info['Opcionales'] = [
                    opt for opt in invoice_info['Opcionales']
                    if opt.get('Id') != 27
                ]
            
            # Agregar el opcional 27 con el valor de la factura
            if 'Opcionales' not in invoice_info:
                invoice_info['Opcionales'] = []
            
            invoice_info['Opcionales'].append({
                'Id': 27,
                'Valor': self.l10n_ar_afip_fce_transmission,
            })
        
        return res
