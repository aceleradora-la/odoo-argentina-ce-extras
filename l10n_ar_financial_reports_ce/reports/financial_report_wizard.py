# -*- coding: utf-8 -*-
# Reportes financieros interactivos estilo Enterprise para Odoo Community.
#
# Arquitectura (skill odoo-community-report): un TransientModel es la ÚNICA
# fuente de datos. get_report_data() (grupos + totales) y get_group_lines()
# (detalle por grupo, lazy) alimentan la pantalla OWL, el PDF QWeb y el Excel
# (controlador HTTP). No duplicar la lógica en otro lado.

from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, formatLang

# Tipos de cuenta que NO arrastran saldo inicial de ejercicios anteriores
# (resultados): su saldo inicial arranca en el inicio del ejercicio fiscal.
NO_CARRY_TYPES = (
    'income', 'income_other',
    'expense', 'expense_depreciation', 'expense_direct_cost',
    'off_balance',
)

REPORT_TITLES = {
    'partner_ledger': 'Libro mayor de la empresa',
    'general_ledger': 'Libro mayor',
    'aged_receivable': 'Cuenta por cobrar vencida',
    'aged_payable': 'Cuenta por pagar vencida',
}

AGED_BUCKET_KEYS = ('not_due', 'b1', 'b2', 'b3', 'b4', 'older')

# Campos que la pantalla puede modificar vía update_filters().
UPDATABLE_FIELDS = {
    'date_from', 'date_to', 'date_at', 'target_move',
    'account_type_filter', 'period_length', 'based_on', 'show_details',
}


class L10nArFinancialReportWizard(models.TransientModel):
    _name = 'l10n_ar.financial.report.wizard'
    _description = 'Reportes Financieros Interactivos (Community)'

    report_type = fields.Selection([
        ('partner_ledger', 'Libro mayor de la empresa'),
        ('general_ledger', 'Libro mayor'),
        ('aged_receivable', 'Cuenta por cobrar vencida'),
        ('aged_payable', 'Cuenta por pagar vencida'),
    ], string='Reporte', required=True, default='partner_ledger')
    company_ids = fields.Many2many(
        'res.company', string='Compañías',
        default=lambda self: self.env.companies,
        help='Vacío = compañía activa. Como en el resto de Odoo, el reporte '
             'incluye la información de todas las compañías seleccionadas.')
    # Rango para los libros mayores.
    date_from = fields.Date(string='Desde')
    date_to = fields.Date(string='Hasta')
    # Fecha de corte para las cuentas vencidas.
    date_at = fields.Date(string='Al')
    target_move = fields.Selection([
        ('posted', 'Asientos registrados'),
        ('all', 'Todos los asientos'),
    ], string='Asientos', required=True, default='posted')
    account_type_filter = fields.Selection([
        ('both', 'Por cobrar y por pagar'),
        ('receivable', 'Por cobrar'),
        ('payable', 'Por pagar'),
    ], string='Cuentas', default='both',
        help='Tipos de cuenta incluidos en el Libro mayor de la empresa.')
    period_length = fields.Integer(
        string='Días por período', default=30,
        help='Largo de cada tramo de antigüedad (cuentas vencidas).')
    based_on = fields.Selection([
        ('date_maturity', 'Según fecha límite'),
        ('date', 'Según fecha de factura'),
    ], string='Antigüedad según', default='date_maturity')
    show_details = fields.Boolean(
        string='Detalle en PDF/Excel', default=True,
        help='Incluye los apuntes de cada grupo en las exportaciones.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        company = self.env.company
        fy = company.compute_fiscalyear_dates(today)
        if 'date_from' in fields_list and not res.get('date_from'):
            res['date_from'] = fy['date_from']
        if 'date_to' in fields_list and not res.get('date_to'):
            res['date_to'] = fy['date_to']
        if 'date_at' in fields_list and not res.get('date_at'):
            res['date_at'] = today
        return res

    # ------------------------------------------------------------------
    # Helpers de formato / dominio
    # ------------------------------------------------------------------
    def _is_aged(self):
        return self.report_type in ('aged_receivable', 'aged_payable')

    def _get_companies(self):
        """Como en el resto de Odoo: todas las compañías seleccionadas."""
        return self.company_ids or self.env.company

    def _main_company(self):
        return self._get_companies()[0]

    def _currency(self):
        return self._main_company().currency_id

    def _get_states(self):
        return ['posted'] if self.target_move == 'posted' else ['posted', 'draft']

    def _fmt(self, value):
        return formatLang(self.env, value or 0.0,
                          currency_obj=self._currency())

    def _fmt_date(self, value):
        return format_date(self.env, value) if value else ''

    def _money_cell(self, value):
        """Celda monetaria: display formateado + valor crudo (Excel) + clase."""
        currency = self._currency()
        value = currency.round(value or 0.0)
        cls = ''
        if currency.is_zero(value):
            cls = 'o_arfr_zero'
        elif value < 0:
            cls = 'text-danger'
        return {'display': self._fmt(value), 'value': value, 'class': cls}

    def _text_cell(self, text):
        return {'display': text or '', 'value': text or ''}

    def _partner_label(self, partner):
        if not partner:
            return 'Sin contacto'
        if partner.vat:
            return '%s (CUIT: %s)' % (partner.name or partner.display_name,
                                      partner.vat)
        return partner.name or partner.display_name

    def _common_domain(self):
        return [
            ('company_id', 'child_of', self._get_companies().ids),
            ('parent_state', 'in', self._get_states()),
            ('display_type', 'not in', ('line_section', 'line_note')),
        ]

    def _partner_account_types(self):
        mapping = {
            'receivable': ['asset_receivable'],
            'payable': ['liability_payable'],
        }
        return mapping.get(self.account_type_filter,
                           ['asset_receivable', 'liability_payable'])

    def _ledger_account_domain(self):
        if self.report_type == 'partner_ledger':
            return [('account_id.account_type', 'in',
                     self._partner_account_types())]
        return []

    def _check_config(self):
        self.ensure_one()
        if self._is_aged():
            if not self.date_at:
                raise UserError('Indique la fecha de corte del reporte.')
        else:
            if not self.date_from or not self.date_to:
                raise UserError('Indique el rango de fechas del reporte.')
            if self.date_from > self.date_to:
                raise UserError('La fecha "Desde" no puede ser posterior a "Hasta".')

    # ------------------------------------------------------------------
    # Metadatos de columnas (la pantalla, el PDF y el Excel iteran esto)
    # ------------------------------------------------------------------
    def _aged_bucket_labels(self):
        p = max(self.period_length or 30, 1)
        return {
            'not_due': 'A la fecha',
            'b1': '1-%d' % p,
            'b2': '%d-%d' % (p + 1, 2 * p),
            'b3': '%d-%d' % (2 * p + 1, 3 * p),
            'b4': '%d-%d' % (3 * p + 1, 4 * p),
            'older': 'Antiguos',
        }

    def _get_columns(self):
        """[{'key','label','type'}] — type: text | text_right | date | monetary."""
        self.ensure_one()
        if self.report_type == 'partner_ledger':
            return [
                {'key': 'journal', 'label': 'Diario', 'type': 'text'},
                {'key': 'account', 'label': 'Cuenta', 'type': 'text'},
                {'key': 'date', 'label': 'Fecha de factura', 'type': 'date'},
                {'key': 'date_maturity', 'label': 'Fecha límite', 'type': 'date'},
                {'key': 'matching', 'label': 'Conciliación', 'type': 'text'},
                {'key': 'debit', 'label': 'Deber', 'type': 'monetary'},
                {'key': 'credit', 'label': 'Haber', 'type': 'monetary'},
                {'key': 'amount_currency', 'label': 'Moneda del importe',
                 'type': 'text_right'},
                {'key': 'balance', 'label': 'Balance', 'type': 'monetary'},
            ]
        if self.report_type == 'general_ledger':
            return [
                {'key': 'journal', 'label': 'Diario', 'type': 'text'},
                {'key': 'date', 'label': 'Fecha', 'type': 'date'},
                {'key': 'partner', 'label': 'Empresa', 'type': 'text'},
                {'key': 'label', 'label': 'Etiqueta', 'type': 'text'},
                {'key': 'debit', 'label': 'Deber', 'type': 'monetary'},
                {'key': 'credit', 'label': 'Haber', 'type': 'monetary'},
                {'key': 'amount_currency', 'label': 'Moneda del importe',
                 'type': 'text_right'},
                {'key': 'balance', 'label': 'Balance', 'type': 'monetary'},
            ]
        labels = self._aged_bucket_labels()
        return (
            [{'key': 'date', 'label': 'Fecha de factura', 'type': 'date'}]
            + [{'key': k, 'label': labels[k], 'type': 'monetary'}
               for k in AGED_BUCKET_KEYS]
            + [{'key': 'total', 'label': 'Total', 'type': 'monetary'}]
        )

    # ------------------------------------------------------------------
    # Contrato de datos principal
    # ------------------------------------------------------------------
    def get_report_data(self):
        """{'header': {...}, 'groups': [...], 'totals': {...}}.

        groups: [{'key': int, 'name': str, 'values': {col_key: cell}}]
        cell:   {'display': str, 'value': num|str, 'class': str}
        El detalle por grupo NO viaja acá: se pide lazy con get_group_lines().
        """
        self.ensure_one()
        self._check_config()
        if self._is_aged():
            groups, totals = self._aged_groups()
        else:
            groups, totals = self._ledger_groups()

        if self._is_aged():
            period_label = 'Al %s' % self._fmt_date(self.date_at)
            end_date = self.date_at
        else:
            same_year = (self.date_from.month, self.date_from.day) == (1, 1) \
                and (self.date_to.month, self.date_to.day) == (12, 31) \
                and self.date_from.year == self.date_to.year
            period_label = str(self.date_from.year) if same_year else \
                '%s - %s' % (self._fmt_date(self.date_from),
                             self._fmt_date(self.date_to))
            end_date = self.date_to

        has_unposted = bool(self.env['account.move'].search_count([
            ('state', '=', 'draft'),
            ('company_id', 'child_of', self._get_companies().ids),
            ('date', '<=', end_date),
        ], limit=1))

        header = {
            'report_type': self.report_type,
            'title': REPORT_TITLES[self.report_type],
            'company_name': ', '.join(
                self._get_companies().mapped('display_name')),
            'currency_name': self._currency().name,
            'period_label': period_label,
            'date_from': fields.Date.to_string(self.date_from) or False,
            'date_to': fields.Date.to_string(self.date_to) or False,
            'date_at': fields.Date.to_string(self.date_at) or False,
            'target_move': self.target_move,
            'account_type_filter': self.account_type_filter,
            'period_length': self.period_length,
            'based_on': self.based_on,
            'show_details': self.show_details,
            'is_aged': self._is_aged(),
            'has_unposted': has_unposted,
            'columns': self._get_columns(),
        }
        return {'header': header, 'groups': groups, 'totals': totals}

    @api.model
    def get_or_create_report_data(self, wizard_id=None, report_type=None):
        """La pantalla puede recargarse (F5, cambio de compañía) y perder el
        wizard: los params del client action no sobreviven al reload y el
        registro transient puede ser aspirado. Restaura el wizard si existe;
        si no, crea uno nuevo con defaults (incluidas las compañías activas
        del momento) y devuelve los datos junto con el wizard_id vigente."""
        wizard = self.browse(wizard_id).exists() if wizard_id else self.browse()
        if not wizard:
            vals = {}
            if report_type in dict(self._fields['report_type'].selection):
                vals['report_type'] = report_type
            wizard = self.create(vals)
        data = wizard.get_report_data()
        data['wizard_id'] = wizard.id
        return data

    def get_group_lines(self, group_keys=None):
        """Detalle (apuntes) por grupo: {group_key: [line, ...]}.

        line = {'name': str, 'is_initial': bool, 'values': {col_key: cell}}.
        group_keys=None devuelve TODOS los grupos (Desplegar todo / export).
        """
        self.ensure_one()
        self._check_config()
        if self._is_aged():
            return self._aged_lines(group_keys)
        return self._ledger_lines(group_keys)

    def get_export_data(self):
        """Payload común para PDF y Excel (mismos datos que la pantalla)."""
        self.ensure_one()
        data = self.get_report_data()
        lines_by_group = self.get_group_lines() if self.show_details else {}
        return {'data': data, 'lines_by_group': lines_by_group}

    def update_filters(self, values):
        """La pantalla cambia filtros sin cerrar el reporte."""
        self.ensure_one()
        vals = {k: v for k, v in (values or {}).items() if k in UPDATABLE_FIELDS}
        for key in ('date_from', 'date_to', 'date_at'):
            if key in vals and not vals[key]:
                vals.pop(key)
        if 'period_length' in vals:
            vals['period_length'] = max(int(vals['period_length'] or 30), 1)
        if vals:
            self.write(vals)
        return self.get_report_data()

    # ------------------------------------------------------------------
    # Libros mayores (por empresa / por cuenta)
    # ------------------------------------------------------------------
    def _ledger_group_field(self):
        return 'partner_id' if self.report_type == 'partner_ledger' \
            else 'account_id'

    def _ledger_init_map(self, keys=None):
        """{group_key: saldo inicial} antes de date_from.

        Cuentas de resultado (Libro mayor): el saldo inicial arranca en el
        inicio del ejercicio fiscal de date_from, no arrastra años anteriores.
        """
        AML = self.env['account.move.line']
        gfield = self._ledger_group_field()
        base = self._common_domain() + self._ledger_account_domain()
        if keys is not None:
            base += [(gfield, 'in', [k or False for k in keys])]
        init = defaultdict(float)
        if self.report_type == 'partner_ledger':
            domains = [base + [('date', '<', self.date_from)]]
        else:
            fy_start = self._main_company().compute_fiscalyear_dates(
                self.date_from)['date_from']
            domains = [
                base + [('date', '<', self.date_from),
                        ('account_id.account_type', 'not in', NO_CARRY_TYPES)],
                base + [('date', '<', self.date_from),
                        ('date', '>=', fy_start),
                        ('account_id.account_type', 'in', NO_CARRY_TYPES)],
            ]
        for domain in domains:
            for rec, balance in AML._read_group(domain, [gfield], ['balance:sum']):
                init[rec.id if rec else 0] += balance or 0.0
        return init

    def _ledger_group_label(self, key, record):
        if self.report_type == 'partner_ledger':
            return self._partner_label(record)
        if not record:
            return 'Sin cuenta'
        return '%s %s' % (record.code or '', record.name or '')

    def _ledger_groups(self):
        AML = self.env['account.move.line']
        gfield = self._ledger_group_field()
        currency = self._currency()
        base = self._common_domain() + self._ledger_account_domain()
        period_domain = base + [('date', '>=', self.date_from),
                                ('date', '<=', self.date_to)]

        init_map = self._ledger_init_map()
        period = {}
        records = {}
        for rec, debit, credit, balance in AML._read_group(
                period_domain, [gfield],
                ['debit:sum', 'credit:sum', 'balance:sum']):
            key = rec.id if rec else 0
            period[key] = (debit or 0.0, credit or 0.0, balance or 0.0)
            records[key] = rec

        all_keys = set(period) | set(init_map)
        missing = [k for k in all_keys if k not in records and k]
        if missing:
            model = 'res.partner' if gfield == 'partner_id' else 'account.account'
            for rec in self.env[model].browse(missing):
                records[rec.id] = rec

        groups = []
        total_debit = total_credit = total_balance = 0.0
        for key in all_keys:
            debit, credit, pbalance = period.get(key, (0.0, 0.0, 0.0))
            balance = init_map.get(key, 0.0) + pbalance
            if currency.is_zero(debit) and currency.is_zero(credit) \
                    and currency.is_zero(balance):
                continue
            total_debit += debit
            total_credit += credit
            total_balance += balance
            groups.append({
                'key': key,
                'name': self._ledger_group_label(key, records.get(key)),
                'values': {
                    'debit': self._money_cell(debit),
                    'credit': self._money_cell(credit),
                    'balance': self._money_cell(balance),
                },
            })
        groups.sort(key=lambda g: (g['key'] == 0, (g['name'] or '').upper()))
        totals = {
            'debit': self._money_cell(total_debit),
            'credit': self._money_cell(total_credit),
            'balance': self._money_cell(total_balance),
        }
        return groups, totals

    def _ledger_lines(self, group_keys=None):
        AML = self.env['account.move.line']
        gfield = self._ledger_group_field()
        currency = self._currency()
        is_partner = self.report_type == 'partner_ledger'
        base = self._common_domain() + self._ledger_account_domain()
        domain = base + [('date', '>=', self.date_from),
                         ('date', '<=', self.date_to)]
        if group_keys is not None:
            domain += [(gfield, 'in', [k or False for k in group_keys])]

        init_map = self._ledger_init_map(group_keys)
        lines_by_group = defaultdict(list)
        running = dict(init_map)
        for line in AML.search(domain, order='date asc, id asc'):
            rec = line[gfield]
            key = rec.id if rec else 0
            running[key] = running.get(key, 0.0) + line.balance
            if line.currency_id and line.currency_id != currency:
                amount_cur = formatLang(self.env, line.amount_currency,
                                        currency_obj=line.currency_id)
            else:
                amount_cur = ''
            values = {
                'journal': self._text_cell(line.journal_id.code),
                'date': self._text_cell(self._fmt_date(line.date)),
                'debit': self._money_cell(line.debit),
                'credit': self._money_cell(line.credit),
                'amount_currency': self._text_cell(amount_cur),
                'balance': self._money_cell(running[key]),
            }
            if is_partner:
                values.update({
                    'account': self._text_cell(line.account_id.code),
                    'date_maturity': self._text_cell(
                        self._fmt_date(line.date_maturity)),
                    'matching': self._text_cell(line.matching_number or ''),
                })
            else:
                values.update({
                    'partner': self._text_cell(
                        line.partner_id.name if line.partner_id else ''),
                    'label': self._text_cell(line.name or line.ref or ''),
                })
            lines_by_group[key].append({
                'name': line.move_id.name or '/',
                'is_initial': False,
                'values': values,
            })

        # Fila de saldo inicial al comienzo de cada grupo (si no es cero).
        result = {}
        keys = set(lines_by_group) | {
            k for k, v in init_map.items() if not currency.is_zero(v)}
        for key in keys:
            rows = lines_by_group.get(key, [])
            init = init_map.get(key, 0.0)
            if not currency.is_zero(init):
                rows.insert(0, {
                    'name': 'Saldo inicial',
                    'is_initial': True,
                    'values': {'balance': self._money_cell(init)},
                })
            result[key] = rows
        return result

    # ------------------------------------------------------------------
    # Cuentas vencidas (por cobrar / por pagar)
    # ------------------------------------------------------------------
    def _aged_residual_lines(self):
        """[(apunte, residual en moneda de la compañía al date_at)].

        Con date_at >= hoy alcanza amount_residual. Para fechas pasadas se
        reconstruye el residual restando las conciliaciones parciales con
        max_date <= date_at.
        """
        account_type = 'asset_receivable' \
            if self.report_type == 'aged_receivable' else 'liability_payable'
        AML = self.env['account.move.line']
        currency = self._currency()
        domain = self._common_domain() + [
            ('account_id.account_type', '=', account_type),
            ('date', '<=', self.date_at),
        ]
        today = fields.Date.context_today(self)
        if self.date_at >= today:
            lines = AML.search(domain + [('amount_residual', '!=', 0)])
            return [(line, line.amount_residual) for line in lines]

        lines = AML.search(domain)
        if not lines:
            return []
        partials = self.env['account.partial.reconcile'].search([
            ('max_date', '<=', self.date_at),
            '|',
            ('debit_move_id', 'in', lines.ids),
            ('credit_move_id', 'in', lines.ids),
        ])
        debit_recon = defaultdict(float)
        credit_recon = defaultdict(float)
        for partial in partials:
            debit_recon[partial.debit_move_id.id] += partial.amount
            credit_recon[partial.credit_move_id.id] += partial.amount
        result = []
        for line in lines:
            residual = line.balance \
                - debit_recon.get(line.id, 0.0) \
                + credit_recon.get(line.id, 0.0)
            if not currency.is_zero(residual):
                result.append((line, residual))
        return result

    def _aged_bucket_key(self, line):
        due = line.date_maturity if self.based_on == 'date_maturity' \
            else line.date
        due = due or line.date
        diff = (self.date_at - due).days
        if diff <= 0:
            return 'not_due'
        p = max(self.period_length or 30, 1)
        index = min((diff - 1) // p + 1, 5)
        return AGED_BUCKET_KEYS[index]

    def _aged_line_amounts(self):
        """[(apunte, bucket_key, importe con signo de presentación)]."""
        sign = 1 if self.report_type == 'aged_receivable' else -1
        return [(line, self._aged_bucket_key(line), sign * residual)
                for line, residual in self._aged_residual_lines()]

    def _aged_groups(self):
        currency = self._currency()
        sums = defaultdict(lambda: defaultdict(float))
        partners = {}
        for line, bucket, amount in self._aged_line_amounts():
            key = line.partner_id.id if line.partner_id else 0
            partners.setdefault(key, line.partner_id)
            sums[key][bucket] += amount
            sums[key]['total'] += amount

        groups = []
        totals_acc = defaultdict(float)
        for key, buckets in sums.items():
            if currency.is_zero(buckets['total']) and all(
                    currency.is_zero(buckets[b]) for b in AGED_BUCKET_KEYS):
                continue
            values = {}
            for bucket in (*AGED_BUCKET_KEYS, 'total'):
                values[bucket] = self._money_cell(buckets[bucket])
                totals_acc[bucket] += buckets[bucket]
            groups.append({
                'key': key,
                'name': self._partner_label(partners.get(key)),
                'values': values,
            })
        groups.sort(key=lambda g: (g['key'] == 0, (g['name'] or '').upper()))
        totals = {bucket: self._money_cell(totals_acc[bucket])
                  for bucket in (*AGED_BUCKET_KEYS, 'total')}
        return groups, totals

    def _aged_lines(self, group_keys=None):
        result = defaultdict(list)
        keys = set(group_keys) if group_keys is not None else None
        for line, bucket, amount in self._aged_line_amounts():
            key = line.partner_id.id if line.partner_id else 0
            if keys is not None and key not in keys:
                continue
            invoice_date = line.move_id.invoice_date or line.date
            values = {
                'date': self._text_cell(self._fmt_date(invoice_date)),
                bucket: self._money_cell(amount),
                'total': self._money_cell(amount),
            }
            result[key].append({
                'name': line.move_id.name or '/',
                'is_initial': False,
                'values': values,
            })
        return dict(result)

    # ------------------------------------------------------------------
    # Ubicación de los menús junto a los reportes estándar
    # ------------------------------------------------------------------
    @api.model
    def _place_menus(self):
        """Cuelga cada menú propio debajo de su equivalente estándar dentro
        de Reportes, si algún módulo de reportes lo provee (se busca por
        nombre, en los idiomas instalados, para no depender de un módulo
        concreto). Si no se encuentra, el menú queda bajo Reportes. Corre en
        cada instalación/actualización vía <function> en el XML de vistas."""
        root = self.env.ref('account.menu_finance_reports',
                            raise_if_not_found=False)
        if not root:
            return
        mapping = [
            ('l10n_ar_financial_reports_ce.menu_partner_ledger',
             ['Libro Mayor de empresa', 'Libro mayor de la empresa',
              'Partner Ledger']),
            ('l10n_ar_financial_reports_ce.menu_general_ledger',
             ['Libro Mayor', 'Libro mayor', 'General Ledger']),
            ('l10n_ar_financial_reports_ce.menu_aged_receivable',
             ['Cuentas por cobrar vencidas', 'Aged Receivable',
              'Aged Receivables']),
            ('l10n_ar_financial_reports_ce.menu_aged_payable',
             ['Cuentas por pagar vencidas', 'Aged Payable', 'Aged Payables']),
        ]
        Menu = self.env['ir.ui.menu'].sudo()
        our_menus = {}
        for xmlid, _names in mapping:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                our_menus[xmlid] = menu
        our_ids = [m.id for m in our_menus.values()]
        langs = [code for code, _name in self.env['res.lang'].get_installed()]
        for xmlid, names in mapping:
            our = our_menus.get(xmlid)
            if not our:
                continue
            target = None
            for lang in langs:
                for name in names:
                    target = Menu.with_context(lang=lang).search([
                        ('name', '=ilike', name),
                        ('id', 'not in', our_ids),
                        ('parent_path', '=like', '%s%%' % root.parent_path),
                    ], limit=1)
                    if target:
                        break
                if target:
                    break
            if target:
                our.sudo().write({
                    'parent_id': target.parent_id.id,
                    'sequence': target.sequence + 1,
                })

    # ------------------------------------------------------------------
    # Apertura del client action
    # ------------------------------------------------------------------
    def action_generate(self):
        self.ensure_one()
        self._check_config()
        return {
            'type': 'ir.actions.client',
            'tag': 'l10n_ar_financial_report',
            'name': REPORT_TITLES[self.report_type],
            'params': {'wizard_id': self.id, 'report_type': self.report_type},
        }
