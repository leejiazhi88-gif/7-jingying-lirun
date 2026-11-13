#!/usr/bin/env python3
"""Populate revenue tabs through 4.3 using supported conditional value colors.

Feishu's public API neither creates dataBar rules nor copies them with sheets.
Existing data bars are retained; new sheets use positive blue / negative red.
"""
import argparse
import copy
import json
import os
import re
import urllib.parse
from pathlib import Path

from build_revenue_sheets import check
from write_quarter_profit import BASE, DEFAULT_WIKI_TOKEN, load_env_file, request, tenant_token, spreadsheet_token
from write_individual_profit_sheets import col_name, display_number

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'data/revenue_sheet_sync.json'
PLANS = [
    ('7Yy8AS', '676109', 'industry', 'quarter', '季度营收（亿）'),
    ('dzdlsz', 'YhOty9', 'industry', 'ttm', '年TTM营收（亿）'),
    ('y61pqJ', 'Oj41pd', 'industry', 'yoy', '年TTM营收同比涨幅'),
    ('SLBprv', 'mJvCV8', 'individual', 'quarter', '季度营收（亿）'),
    ('YoTOcI', 'Oj41pd', 'individual', 'yoy', '年TTM营收同比涨幅'),
]


def values(token, book, target):
    path = urllib.parse.quote(target, safe='!')
    return request('GET', f'{BASE}/sheets/v2/spreadsheets/{book}/values/{path}', token)['data']['valueRange'].get('values', [])


def conditions(token, book, sid):
    return request('GET', f'{BASE}/sheets/v2/spreadsheets/{book}/condition_formats?sheet_ids={sid}', token)['data']['sheet_condition_formats']


def normalize_conditions(rules):
    result = []
    for entry in rules:
        cf = copy.deepcopy(entry['condition_format'])
        cf.pop('cf_id', None)
        cf['ranges'] = [r.split('!', 1)[1] if '!' in r else '*' for r in cf['ranges']]
        result.append(cf)
    return result


def col_index(col):
    index = 0
    for c in col:
        index = index * 26 + ord(c) - 64
    return index


def covers(cell_range, row, col, sid):
    if cell_range == sid:
        return True
    start, end = cell_range.split('!', 1)[1].split(':')
    def bounds(s, default_row):
        match = re.fullmatch(r'([A-Z]*)([0-9]*)', s)
        return (int(match[2]) if match[2] else default_row,
                col_index(match[1]) if match[1] else None)
    r1, c1 = bounds(start, 1)
    r2, c2 = bounds(end, 1000000)
    return r1 <= row <= r2 and (c1 is None or c1 <= col) and (c2 is None or col <= c2)


def assert_bars(rules, sid, matrix, start_row):
    ranges = [r for entry in rules if entry['condition_format']['rule_type'] == 'dataBar'
              for r in entry['condition_format']['ranges']]
    for r, row in enumerate(matrix, start_row):
        for c, value in enumerate(row, 2):
            if value is not None and not any(covers(area, r, c, sid) for area in ranges):
                raise AssertionError(f'Missing data bar at {sid}!{col_name(c)}{r}')


def write_verify(token, book, sid, matrix, first_row=1, first_col=1):
    targets = []
    for offset in range(0, len(matrix[0]), 80):
        block = [row[offset:offset + 80] for row in matrix]
        target = f'{sid}!{col_name(first_col + offset)}{first_row}:{col_name(first_col + offset + len(block[0]) - 1)}{first_row + len(block) - 1}'
        request('PUT', f'{BASE}/sheets/v2/spreadsheets/{book}/values', token,
                {'valueRange': {'range': target, 'values': block}})
        actual = values(token, book, target)
        if actual != block:
            raise AssertionError(f'Value readback mismatch: {target}')
        targets.append(target)
    return targets


def format_values(token, book, sid, matrix, start_row, percentage):
    if percentage:
        ranges = [f'{sid}!{col_name(offset + 2)}{start_row}:{col_name(min(offset + 81, len(matrix[0]) + 1))}{start_row + len(matrix) - 1}'
                  for offset in range(0, len(matrix[0]), 80)]
        styles = [{'ranges': ranges, 'style': {'formatter': '0.00%'}}]
    else:
        integer, decimal = [], []
        for r, row in enumerate(matrix, start_row):
            for c, value in enumerate(row, 2):
                if value is not None:
                    (decimal if abs(value) < 10 else integer).append(f'{sid}!{col_name(c)}{r}:{col_name(c)}{r}')
        styles = []
        if integer:
            styles.append({'ranges': integer, 'style': {'formatter': '0', 'thousandSeparator': True}})
        if decimal:
            styles.append({'ranges': decimal, 'style': {'formatter': ''}})
    request('PUT', f'{BASE}/sheets/v2/spreadsheets/{book}/styles_batch_update', token, {'data': styles})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = json.loads((ROOT / 'data/revenue_sheets.json').read_text())
    check(data)
    if args.check:
        print('Revenue matrices valid; no API writes.')
        return
    load_env_file()
    token = tenant_token()
    book = spreadsheet_token(token, os.environ.get('FEISHU_WIKI_TOKEN', DEFAULT_WIKI_TOKEN))
    def query():
        return request('GET', f'{BASE}/sheets/v3/spreadsheets/{book}/sheets/query', token)['data']['sheets']
    def sheet_ops(ops):
        return request('POST', f'{BASE}/sheets/v2/spreadsheets/{book}/sheets_batch_update', token, {'requests': ops})
    original = {s['sheet_id']: s for s in query()}
    results = []
    live = {'E9yBZl': values(token, book, 'E9yBZl!A1:DI2')}
    companies = data['individual']['companies']
    assert live['E9yBZl'][0][1:113] == companies
    labels = [f'{p[2:4]}年Q{(int(p[4:6]) - 1) // 3 + 1}' for p in data['periods']]
    for sid, source, group, field, heading in PLANS:
        if group == 'industry':
            matrix = data['industry'][field]
            headers = [[heading] + data['industry']['names']]
            start_row = 2
        else:
            matrix = [[data['individual']['data'][name][field][i] for name in companies] for i in range(len(labels))]
            headers = [[heading] + companies, live['E9yBZl'][1][:113]]
            start_row = 3
        written = matrix if field == 'yoy' else [[display_number(v) for v in row] for row in matrix]
        full = headers + [[label] + row for label, row in zip(labels, written)]
        columns = original[sid]['grid_properties']['column_count']
        if columns < len(full[0]):
            request('POST', f'{BASE}/sheets/v2/spreadsheets/{book}/dimension_range', token,
                    {'dimension': {'sheetId': sid, 'majorDimension': 'COLUMNS', 'length': len(full[0]) - columns}})
        targets = write_verify(token, book, sid, full)
        format_values(token, book, sid, written, start_row, field == 'yoy')
        end_col = col_name(len(full[0]))
        def header_ranges(row):
            return [f'{sid}!{col_name(offset + 1)}{row}:{col_name(min(offset + 80, len(full[0])))}{row}'
                    for offset in range(0, len(full[0]), 80)]
        header_styles = [{'ranges': header_ranges(1),
                          'style': {'font': {'bold': True}, 'backColor': '#DEE0E3'}}]
        if group == 'individual':
            header_styles.append({'ranges': header_ranges(2), 'style': {'formatter': '', 'backColor': '#F2F3F5'}})
        request('PUT', f'{BASE}/sheets/v2/spreadsheets/{book}/styles_batch_update', token, {'data': header_styles})
        sheet_ops([{'updateSheet': {'properties': {'sheetId': sid, 'frozenRowCount': start_row - 1, 'frozenColCount': 1}}}])
        rules = conditions(token, book, sid)
        target = f'{sid}!B{start_row}:{end_col}{start_row + len(written) - 1}'
        expected = [{'ranges': [target], 'rule_type': 'cellIs',
                     'attrs': [{'operator': operator, 'formula': ['0']}],
                     'style': {'back_color': background, 'fore_color': foreground}}
                    for operator, background, foreground in [('greaterThan', '#D6E4FF', '#245BDB'), ('lessThan', '#FFE2E3', '#C02A33')]]
        normalized = normalize_conditions(rules)
        # Idempotently recognize these two rules on repeated syncs.
        pending = [cf for cf in expected if dict(cf, ranges=[target.split('!', 1)[1]]) not in normalized]
        if pending:
            reply = request('POST', f'{BASE}/sheets/v2/spreadsheets/{book}/condition_formats/batch_create', token,
                            {'sheet_condition_formats': [{'sheet_id': sid, 'condition_format': cf} for cf in pending]})
            assert all(r['res_code'] == 0 for r in reply['data']['responses']), reply
        rules = conditions(token, book, sid)
        normalized = normalize_conditions(rules)
        for cf in expected:
            assert dict(cf, ranges=[target.split('!', 1)[1]]) in normalized, 'Conditional format readback mismatch'
        results.append({'sheet_id': sid, 'title': original[sid]['title'], 'reference': source,
                        'ranges': targets, 'numeric_cells': sum(v is not None for row in written for v in row),
                        'conditional_format_mode': 'positive blue / negative red; public API cannot create native data bars',
                        'conditional_formats': rules})
        print(json.dumps({'verified': original[sid]['title'], 'sheet_id': sid}, ensure_ascii=False), flush=True)
    # Existing 4.2 retains its headers and native conditional formats.
    matrix = [[display_number(data['individual']['data'][name]['ttm'][i]) for name in companies] for i in range(len(labels))]
    write_verify(token, book, 'E9yBZl', [[label] for label in labels], first_row=3)
    targets = write_verify(token, book, 'E9yBZl', matrix, first_row=3, first_col=2)
    format_values(token, book, 'E9yBZl', matrix, 3, False)
    rules = conditions(token, book, 'E9yBZl')
    assert_bars(rules, 'E9yBZl', matrix, 3)
    results.append({'sheet_id': 'E9yBZl', 'title': original['E9yBZl']['title'], 'ranges': targets,
                             'numeric_cells': sum(v is not None for row in matrix for v in row),
                             'data_bar_rules': len(rules), 'data_bar_coverage': 'all populated data cells', 'conditional_formats': rules})
    final = query()
    expected = [s['title'] for s in sorted(original.values(), key=lambda s: s['index'])]
    assert [s['title'] for s in sorted(final, key=lambda s: s['index'])] == expected
    AUDIT.write_text(json.dumps({'as_of': data['as_of'], 'latest_financial_period': data['periods'][0],
                                'sheets': results,
                                'final_sheets': final}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'completed': True, 'numeric_cells': sum(r['numeric_cells'] for r in results),
                      'all_numeric': True, 'new_conditional_formats': 'positive blue / negative red'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
