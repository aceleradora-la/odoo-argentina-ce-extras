# -*- coding: utf-8 -*-
# Estructura configurable del Estado de Resultados (estilo Enterprise /
# MIS Builder): líneas que suman cuentas por prefijo de código y líneas
# fórmula que operan sobre los códigos de otras líneas.

import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

CODE_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
RESERVED_CODES = {
    'and', 'or', 'not', 'if', 'else', 'in', 'is', 'for', 'while',
    'def', 'lambda', 'True', 'False', 'None', 'abs', 'min', 'max',
    'sum', 'round',
}


class L10nArPlStructure(models.Model):
    _name = 'l10n_ar.pl.structure'
    _description = 'Estructura de Estado de Resultados'

    name = fields.Char(string='Nombre', required=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'l10n_ar.pl.structure.line', 'structure_id',
        string='Líneas', copy=True)


class L10nArPlStructureLine(models.Model):
    _name = 'l10n_ar.pl.structure.line'
    _description = 'Línea de estructura de Estado de Resultados'
    _order = 'sequence, id'

    structure_id = fields.Many2one(
        'l10n_ar.pl.structure', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    code = fields.Char(
        string='Código', required=True,
        help='Identificador para usar en fórmulas (ej: VN). Solo letras, '
             'números y guión bajo; no puede empezar con número.')
    name = fields.Char(string='Nombre', required=True)
    line_type = fields.Selection([
        ('accounts', 'Suma de cuentas'),
        ('formula', 'Fórmula'),
    ], string='Tipo', required=True, default='accounts')
    account_prefixes = fields.Char(
        string='Prefijos de cuenta',
        help='Prefijos de código de cuenta separados por coma. '
             'Ej: 4.1,4.2 incluye todas las cuentas cuyo código empiece así. '
             'Ojo: una cuenta patrimonial (ej. 1.1.6) computa el movimiento '
             'neto del período, no un costo de venta real (EI + compras - EF).')
    formula = fields.Char(
        string='Fórmula',
        help='Expresión con los códigos de líneas anteriores (por secuencia). '
             'Ej: VN + CV')
    style = fields.Selection([
        ('section', 'Sección'),
        ('total', 'Total destacado'),
    ], string='Estilo', required=True, default='section')

    _sql_constraints = [
        ('code_uniq', 'unique(structure_id, code)',
         'El código debe ser único dentro de la estructura.'),
    ]

    @api.constrains('code')
    def _check_code(self):
        for line in self:
            code = line.code or ''
            if not CODE_RE.match(code) or code in RESERVED_CODES:
                raise ValidationError(
                    'El código "%s" no es válido: use solo letras, números y '
                    'guión bajo (sin empezar con número) y evite palabras '
                    'reservadas.' % code)
