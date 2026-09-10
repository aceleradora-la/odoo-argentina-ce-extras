# -*- coding: utf-8 -*-
# Export a Excel de los reportes financieros (xlsxwriter). Reusa
# get_export_data() del wizard: mismos datos que la pantalla y el PDF.

import io

import xlsxwriter
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request


class FinancialReportController(http.Controller):

    @http.route('/l10n_ar_financial_reports_ce/xlsx/<int:wizard_id>',
                type='http', auth='user')
    def export_xlsx(self, wizard_id, **kwargs):
        if not (request.env.user.has_group('account.group_account_readonly')
                or request.env.user.has_group('account.group_account_invoice')):
            raise Forbidden()
        wizard = request.env['l10n_ar.financial.report.wizard'].browse(wizard_id)
        if not wizard.exists():
            raise Forbidden()

        export = wizard.get_export_data()
        data = export['data']
        lines_by_group = export['lines_by_group']
        header = data['header']
        columns = header['columns']

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})
        sheet = workbook.add_worksheet(header['title'][:31])

        info_fmt = workbook.add_format({'bold': True})
        head_fmt = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'border': 1, 'bg_color': '#f2f2f2'})
        group_fmt = workbook.add_format({'bold': True, 'border': 1})
        group_money = workbook.add_format({
            'bold': True, 'border': 1, 'num_format': '#,##0.00'})
        group_money_neg = workbook.add_format({
            'bold': True, 'border': 1, 'num_format': '#,##0.00',
            'font_color': '#dc3545'})
        line_fmt = workbook.add_format({'border': 1})
        line_indent = workbook.add_format({'border': 1, 'indent': 1})
        line_money = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
        line_money_neg = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'font_color': '#dc3545'})
        total_fmt = workbook.add_format({'bold': True, 'top': 2})
        total_money = workbook.add_format({
            'bold': True, 'top': 2, 'num_format': '#,##0.00'})
        total_money_neg = workbook.add_format({
            'bold': True, 'top': 2, 'num_format': '#,##0.00',
            'font_color': '#dc3545'})

        def write_cell(row, col_idx, column, cell, text_fmt, money_fmt, money_neg_fmt):
            value = (cell or {}).get('value')
            if column['type'] == 'monetary':
                if value is None:
                    sheet.write_blank(row, col_idx, None, money_fmt)
                else:
                    fmt = money_neg_fmt if value < 0 else money_fmt
                    sheet.write_number(row, col_idx, value, fmt)
            else:
                sheet.write(row, col_idx, (cell or {}).get('display') or '', text_fmt)

        # Encabezado informativo
        sheet.write(0, 0, header['title'], info_fmt)
        sheet.write(1, 0, header['company_name'], info_fmt)
        sheet.write(2, 0, header['period_label'], info_fmt)
        filters_line = ('Asientos registrados'
                        if header['target_move'] == 'posted'
                        else 'Todos los asientos')
        if header.get('filter_text'):
            filters_line += ' - Filtro: %s' % header['filter_text']
        sheet.write(3, 0, filters_line)

        # Fila de grupos (períodos) + fila de etiquetas de columna.
        header_row = 5
        sheet.write(header_row, 0, '', head_fmt)
        col_idx = 1
        for group in header.get('column_groups') or []:
            span = group.get('colspan') or 1
            if span > 1:
                # merge_range con una sola celda lanza excepción.
                sheet.merge_range(header_row, col_idx,
                                  header_row, col_idx + span - 1,
                                  group.get('label') or '', head_fmt)
            else:
                sheet.write(header_row, col_idx,
                            group.get('label') or '', head_fmt)
            col_idx += span
        sheet.write(header_row + 1, 0, '', head_fmt)
        for idx, column in enumerate(columns, start=1):
            sheet.write(header_row + 1, idx, column['label'], head_fmt)
        sheet.set_column(0, 0, 45)
        sheet.set_column(1, len(columns), 16)
        sheet.freeze_panes(header_row + 2, 1)

        row = header_row + 2
        for group in data['groups']:
            sheet.write(row, 0, group['name'], group_fmt)
            for idx, column in enumerate(columns, start=1):
                write_cell(row, idx, column, group['values'].get(column['key']),
                           group_fmt, group_money, group_money_neg)
            row += 1
            for line in lines_by_group.get(group['key']) or []:
                sheet.write(row, 0, line['name'], line_indent)
                for idx, column in enumerate(columns, start=1):
                    write_cell(row, idx, column,
                               line['values'].get(column['key']),
                               line_fmt, line_money, line_money_neg)
                row += 1

        if data['totals']:
            sheet.write(row, 0, 'Total', total_fmt)
            for idx, column in enumerate(columns, start=1):
                write_cell(row, idx, column,
                           data['totals'].get(column['key']),
                           total_fmt, total_money, total_money_neg)

        workbook.close()
        buffer.seek(0)
        filename = '%s.xlsx' % header['title'].replace(' ', '_')
        return request.make_response(
            buffer.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-'
                                 'officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', http.content_disposition(filename)),
            ],
        )
