#!/usr/bin/env python3
"""Recalculate the four .3 tabs from unrounded TTM data, preserving styles."""
import argparse
import json
from pathlib import Path

from growth_qoq import qoq_matrix, qoq_series
from write_quarter_profit import BASE, DEFAULT_WIKI_TOKEN, load_env_file, request, spreadsheet_token, tenant_token
from write_revenue_sheets import conditions, values, write_verify
from write_individual_profit_sheets import col_name, display_number

ROOT = Path(__file__).resolve().parents[1]
PLANS = [
    ('Oj41pd', 'YhOty9', 2, '1.3赛道年TTM利润环比涨幅'),
    ('y61pqJ', 'dzdlsz', 2, '2.3 赛道年TT营收环比涨幅'),
    ('xMYegN', 'O4pM2w', 3, '3.3单个年TTM利润环比涨幅'),
    ('YoTOcI', 'E9yBZl', 3, '4.3单个年TTM营收环比涨幅'),
]


def load(name):
    return json.loads((ROOT / 'data' / name).read_text())


def save(name, data):
    (ROOT / 'data' / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def recalculate():
    derived, profit, revenue = load('derived_sheets.json'), load('individual_profit.json'), load('revenue_sheets.json')
    periods = load('quarter_profit.json')['periods']
    assert periods == profit['periods'] == revenue['periods']
    derived['qoq'] = qoq_matrix(derived['ttm'], 31)
    derived['displayed_growth'] = 'qoq'
    profit['displayed_growth'] = 'qoq'
    for company in profit['data'].values():
        company['qoq'] = qoq_series(company['ttm'])
    revenue['industry']['qoq'] = qoq_matrix(revenue['industry']['ttm'], 31)
    revenue['displayed_growth'] = 'qoq'
    revenue['method'] = ('Current SW2021 membership; total_revenue with revenue fallback; single quarter from cumulative differences; '
                         'TTM=sum of four quarters; displayed growth is QoQ=TTM/previous-quarter TTM-1. '
                         'YoY is retained only as historical audit data. Missing constituents stay blank. '
                         'Industry sums omit companies missing current/previous cumulative and disclose counts.')
    for company in revenue['individual']['data'].values():
        company['qoq'] = qoq_series(company['ttm'])
    save('derived_sheets.json', derived)
    save('individual_profit.json', profit)
    save('revenue_sheets.json', revenue)
    company_matrix = lambda data, names, field: [[data[name][field][i] for name in names] for i in range(len(periods))]
    industry_profit_ttm = [row if row is not None else [None] * 31 for row in derived['ttm']]
    matrices = {
        'Oj41pd': (industry_profit_ttm, derived['qoq']),
        'y61pqJ': (revenue['industry']['ttm'], revenue['industry']['qoq']),
        'xMYegN': (company_matrix(profit['data'], profit['companies'], 'ttm'), company_matrix(profit['data'], profit['companies'], 'qoq')),
        'YoTOcI': (company_matrix(revenue['individual']['data'], revenue['individual']['companies'], 'ttm'),
                   company_matrix(revenue['individual']['data'], revenue['individual']['companies'], 'qoq')),
    }
    return periods, matrices


def replace_text(value):
    if isinstance(value, str):
        return value.replace('同比', '环比')
    if isinstance(value, list):
        return [replace_text(v) for v in value]
    if isinstance(value, dict):
        return {k: replace_text(v) for k, v in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Recalculate and validate local data only.')
    args = parser.parse_args()
    periods, matrices = recalculate()
    for ttm, qoq in matrices.values():
        for i, row in enumerate(qoq):
            for j, value in enumerate(row):
                current = ttm[i][j]
                previous = ttm[i + 1][j] if i + 1 < len(ttm) else None
                if current is None or previous in (None, 0):
                    assert value is None
                else:
                    assert isinstance(value, (int, float)) and abs((1 + value) * previous - current) <= max(1, abs(current)) * 1e-12
    if args.check:
        print(json.dumps({sid: sum(v is not None for row in qoq for v in row) for sid, (_, qoq) in matrices.items()}))
        return
    load_env_file()
    token = tenant_token()
    book = spreadsheet_token(token, DEFAULT_WIKI_TOKEN)
    metadata = request('GET', f'{BASE}/sheets/v3/spreadsheets/{book}/sheets/query', token)['data']['sheets']
    metadata = {s['sheet_id']: s for s in metadata}
    before, results = {}, []
    # Validate all four source pages before touching any of the four growth pages.
    for sid, source, start_row, title in PLANS:
        ttm, qoq = matrices[sid]
        end_col = col_name(len(ttm[0]) + 1)
        source_data = values(token, book, f'{source}!A{start_row}:{end_col}{start_row + len(ttm) - 1}')
        expected = [[f'{p[2:4]}年Q{(int(p[4:6]) - 1) // 3 + 1}'] + [display_number(v) for v in row] for p, row in zip(periods, ttm)]
        assert all(actual[1:] == wanted[1:] and (actual[0] == wanted[0] or all(v is None for v in wanted[1:]))
                   for actual, wanted in zip(source_data, expected)) and len(source_data) == len(expected), f'TTM source differs from local audit data: {source}'
        assert values(token, book, f'{sid}!B1:{end_col}1') == values(token, book, f'{source}!B1:{end_col}1'), f'Column order differs: {sid}'
        meta = metadata[sid]
        grid = meta['grid_properties']
        target = f"{sid}!A1:{col_name(grid['column_count'])}{grid['row_count']}"
        before[sid] = {'metadata': meta, 'values': values(token, book, target), 'conditions': conditions(token, book, sid)}
    backup = ROOT / 'work/growth_qoq_before.json'
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(json.dumps(before, ensure_ascii=False, indent=2))
    for sid, source, start_row, title in PLANS:
        ttm, qoq = matrices[sid]
        labels = [[f'{p[2:4]}年Q{(int(p[4:6]) - 1) // 3 + 1}'] for p in periods]
        write_verify(token, book, sid, labels, first_row=start_row)
        targets = write_verify(token, book, sid, qoq, first_row=start_row, first_col=2)
        ranges = [f'{sid}!{col_name(offset + 2)}{start_row}:{col_name(min(offset + 81, len(qoq[0]) + 1))}{start_row + len(qoq) - 1}'
                  for offset in range(0, len(qoq[0]), 80)]
        request('PUT', f'{BASE}/sheets/v2/spreadsheets/{book}/styles_batch_update', token,
                {'data': [{'ranges': ranges, 'style': {'formatter': '0.00%'}}]})
        changed_text = []
        for r, row in enumerate(before[sid]['values'], 1):
            for c, value in enumerate(row, 1):
                replacement = replace_text(value)
                if replacement != value:
                    write_verify(token, book, sid, [[replacement]], first_row=r, first_col=c)
                    changed_text.append(f'{col_name(c)}{r}')
        request('POST', f'{BASE}/sheets/v2/spreadsheets/{book}/sheets_batch_update', token,
                {'requests': [{'updateSheet': {'properties': {'sheetId': sid, 'title': title}}}]})
        assert conditions(token, book, sid) == before[sid]['conditions'], f'Conditional format changed: {sid}'
        results.append({'sheet_id': sid, 'title': title, 'source_ttm_sheet': source, 'ranges': targets,
                        'numeric_cells': sum(v is not None for row in qoq for v in row), 'updated_text_cells': changed_text,
                        'conditional_formats_preserved': True,
                        'latest_example': {'current_ttm': ttm[0][0], 'previous_quarter_ttm': ttm[1][0], 'qoq': qoq[0][0]}})
        print(json.dumps({'verified': title, 'numeric_cells': results[-1]['numeric_cells']}, ensure_ascii=False), flush=True)
    after = request('GET', f'{BASE}/sheets/v3/spreadsheets/{book}/sheets/query', token)['data']['sheets']
    for sid, _, _, title in PLANS:
        meta = next(m for m in after if m['sheet_id'] == sid)
        assert meta['title'] == title and '同比' not in meta['title']
        grid = meta['grid_properties']
        actual = values(token, book, f"{sid}!A1:{col_name(grid['column_count'])}{grid['row_count']}")
        assert '同比' not in json.dumps(actual, ensure_ascii=False), sid
        # Text replacement must not touch classification, company names or labels.
        start_row = next(plan[2] for plan in PLANS if plan[0] == sid)
        before_text = {(r, c): replace_text(v) for r, row in enumerate(before[sid]['values']) for c, v in enumerate(row)
                       if isinstance(v, (str, list, dict)) and not (c == 0 and start_row - 1 <= r < start_row + len(periods) - 1)}
        assert all(actual[r][c] == v for (r, c), v in before_text.items())
    save('growth_qoq_sync.json', {'latest_financial_period': periods[0], 'growth': 'qoq',
                                'formula': 'current TTM / previous-quarter TTM - 1',
                                'missing_or_zero_previous': 'blank', 'denominator': 'signed, matching previous growth convention',
                                'all_numeric': True, 'sheets': results})
    print(json.dumps({'completed': True, 'numeric_cells': sum(r['numeric_cells'] for r in results)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
