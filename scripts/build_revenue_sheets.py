#!/usr/bin/env python3
"""Build revenue matrices from cached Tushare consolidated income statements."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from growth_qoq import qoq_matrix, qoq_series

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data' / 'revenue_sheets.json'


def derive(quarters):
    ttm = [sum(quarters[i:i + 4]) if len(quarters[i:i + 4]) == 4
           and all(v is not None for v in quarters[i:i + 4]) else None
           for i in range(len(quarters))]
    yoy = [ttm[i] / ttm[i + 4] - 1 if i + 4 < len(ttm)
           and ttm[i] is not None and ttm[i + 4] not in (None, 0) else None
           for i in range(len(ttm))]
    return ttm, yoy


def build(cache):
    profit = json.loads((ROOT / 'data/quarter_profit.json').read_text())
    individual = json.loads((ROOT / 'data/individual_revenue.json').read_text())
    snapshot = json.loads((cache / 'feishu_snapshot.json').read_text())
    names = next(s['values'][0][1:32] for s in snapshot['sheets']
                 if s['metadata']['sheet_id'] == '676109')
    periods, codes = profit['periods'], profit['l1s']
    assert periods == individual['periods']
    members = json.loads((cache / 'members.json').read_text())
    membership = {}
    for row in members:
        code = row['l1_code'].split('.')[0]
        if code not in codes:
            continue
        previous = membership.setdefault(row['ts_code'], code)
        assert previous == code, f"Conflicting industry: {row['ts_code']}"
    cumulative, manifests = {}, []
    for period in periods:
        path = cache / f'income_{period}.json'
        raw = path.read_bytes()
        rows = json.loads(raw)
        latest = {}
        for row in rows:
            if str(row['report_type']) != '1' or row['end_date'] != period:
                continue
            if (row.get('f_ann_date') or row.get('ann_date') or '') > '20261113':
                continue
            priority = lambda r: (str(r.get('update_flag')) == '1',
                                  r.get('f_ann_date') or '', r.get('ann_date') or '')
            old = latest.get(row['ts_code'])
            if old is None or priority(row) > priority(old):
                latest[row['ts_code']] = row
        cumulative[period] = {code: (r.get('total_revenue') if r.get('total_revenue') is not None
                                     else r.get('revenue')) for code, r in latest.items()}
        manifests.append({'period': period, 'rows': len(rows), 'companies': len(latest),
                          'sha256': hashlib.sha256(raw).hexdigest()})
    quarters, stats = [], []
    for period in periods:
        month = period[4:6]
        prior = period[:4] + {'06': '0331', '09': '0630', '12': '0930'}.get(month, '0331')
        totals, used, missing, absent = Counter(), Counter(), Counter(), Counter()
        for stock, industry in membership.items():
            current = cumulative[period].get(stock)
            if current is None:
                absent[industry] += 1
                continue
            prev = 0 if month == '03' else cumulative[prior].get(stock)
            if prev is None:
                missing[industry] += 1
                continue
            totals[industry] += (current - prev) / 1e8
            used[industry] += 1
        quarters.append([totals[c] if used[c] else None for c in codes])
        stats.append({'period': period, 'industries': {
            c: {'used': used[c], 'missing_previous': missing[c], 'missing_current': absent[c]}
            for c in codes}})
    industry_ttm, industry_yoy = [], []
    for c in range(len(codes)):
        ttm, yoy = derive([row[c] for row in quarters])
        industry_ttm.append(ttm)
        industry_yoy.append(yoy)
    companies = individual['companies']
    individual_data = {}
    backfills = []
    for name in companies:
        source = individual['data'][name]
        quarter = []
        for i, period in enumerate(periods):
            current = cumulative[period].get(source['ts_code'])
            prior = period[:4] + {'06': '0331', '09': '0630', '12': '0930'}.get(period[4:6], '0331')
            previous = 0 if period[4:6] == '03' else cumulative[prior].get(source['ts_code'])
            value = (current - previous) / 1e8 if current is not None and previous is not None else None
            existing = source['quarter'][i]
            if existing is not None:
                assert value is not None and abs(value - existing) < 1e-6, (name, period, existing, value)
            elif value is not None:
                backfills.append({'company': name, 'period': period, 'quarter': value})
            quarter.append(value)
        ttm, yoy = derive(quarter)
        source.update(quarter=quarter, ttm=ttm)
        individual_data[name] = {**source, 'yoy': yoy, 'qoq': qoq_series(ttm)}
    individual['as_of'] = '20261113'
    (ROOT / 'data/individual_revenue.json').write_text(json.dumps(individual, ensure_ascii=False, indent=2) + '\n')
    result = {
        'as_of': '20261113', 'latest_financial_period': periods[0], 'unit': '亿元',
        'source': 'Tushare income_vip (report_type=1), index_member_all (is_new=Y)',
        'method': 'Current SW2021 membership; total_revenue with revenue fallback; single quarter from cumulative differences; TTM=sum of four quarters; displayed growth is QoQ=TTM/previous-quarter TTM-1. YoY is retained only as historical audit data. Missing constituents stay blank. Industry sums omit companies missing current/previous cumulative and disclose counts.',
        'displayed_growth': 'qoq',
        'periods': periods,
        'industry': {'codes': codes, 'names': names, 'quarter': quarters,
                     'ttm': [list(row) for row in zip(*industry_ttm)],
                     'yoy': [list(row) for row in zip(*industry_yoy)], 'stats': stats,
                     'qoq': qoq_matrix([list(row) for row in zip(*industry_ttm)], len(codes)),
                     'membership': membership},
        'individual': {'companies': companies, 'data': individual_data},
        'individual_backfills': backfills,
        'income_cache_manifest': manifests,
        'individual_source_sha256': hashlib.sha256((ROOT / 'data/individual_revenue.json').read_bytes()).hexdigest(),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def check(data):
    assert len(data['periods']) == 19 and data['periods'][0] == '20260930'
    assert len(data['industry']['codes']) == len(data['industry']['names']) == 31
    for field in ('quarter', 'ttm', 'yoy', 'qoq'):
        values = data['industry'][field]
        assert len(values) == 19 and all(len(row) == 31 for row in values)
        assert all(v is None or isinstance(v, (int, float)) for row in values for v in row)
    assert len(data['individual']['companies']) == 112
    return {field: sum(v is not None for row in data['industry'][field] for v in row)
            for field in ('quarter', 'ttm', 'qoq')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'work')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = json.loads(OUTPUT.read_text()) if args.check else build(args.cache_dir)
    print(json.dumps({'industry_numeric_counts': check(data), 'companies': 112}, ensure_ascii=False))
