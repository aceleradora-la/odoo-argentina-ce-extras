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
        # Verificar si es una factura FCE ANTES de llamar al método original
        is_fce = False
        if self.l10n_latam_document_type_id:
            doc_code = self.l10n_latam_document_type_id.code
            # Códigos FCE: 111, 112, 113, 114, 201, 202, 203, 206, 207, 208
            if doc_code in ['111', '112', '113', '114', '201', '202', '203', '206', '207', '208']:
                is_fce = True
        
        # Si es FCE y tiene un valor definido en la factura, agregarlo ANTES del método original
        # para que tenga prioridad
        if is_fce and self.l10n_ar_afip_fce_transmission:
            # Asegurar que existe la lista de Opcionales
            if 'Opcionales' not in invoice_info:
                invoice_info['Opcionales'] = []
            
            # Remover el opcional 27 si ya existe (puede haber sido agregado previamente)
            invoice_info['Opcionales'] = [
                opt for opt in invoice_info['Opcionales']
                if opt.get('Id') != 27
            ]
            
            # Agregar el opcional 27 con el valor de la factura
            invoice_info['Opcionales'].append({
                'Id': 27,
                'Valor': self.l10n_ar_afip_fce_transmission,
            })
        
        # Llamar al método original (puede agregar otros opcionales o el 27 si no está definido en la factura)
        res = super(AccountMove, self).wsfe_invoice_add_info(ws, invoice_info)
        
        # Si es FCE y ya agregamos el opcional 27 desde la factura, asegurarnos de que no se duplique
        # (el método original puede agregarlo desde la configuración general)
        if is_fce and self.l10n_ar_afip_fce_transmission:
            # Remover duplicados del opcional 27, manteniendo solo el primero (el de la factura)
            if 'Opcionales' in invoice_info:
                opcionales = invoice_info['Opcionales']
                seen_27 = False
                filtered_opcionales = []
                for opt in opcionales:
                    if opt.get('Id') == 27:
                        if not seen_27:
                            filtered_opcionales.append(opt)
                            seen_27 = True
                        # Ignorar duplicados
                    else:
                        filtered_opcionales.append(opt)
                invoice_info['Opcionales'] = filtered_opcionales
        
        return res
