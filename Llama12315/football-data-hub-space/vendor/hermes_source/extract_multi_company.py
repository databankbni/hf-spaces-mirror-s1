#!/usr/bin/env python3
"""多公司盘口数据提取器 — 正确区分AH/OU键名
用法: fetch_titan007_odds.py $MID --company 3,24,8 | python3 extract_multi_company.py
"""
import json, sys

def extract(data):
    results = []
    for name, cdata in data.get('companies', {}).items():
        for mkt_key, mkt_label in [('AH让球盘', 'AH'), ('OU大小球盘', 'OU')]:
            if mkt_key not in cdata:
                results.append({'company': name, 'market': mkt_label, 'error': 'no_data'})
                continue
            d = cdata[mkt_key]
            cl = d.get('赛前终盘closing', {})
            op = d.get('初盘opening', {})
            stale = d.get('stale_warning', False)
            freshness = d.get('data_freshness', '?')
            ph_hist = d.get('plate_history', [])

            # AH vs OU 键名不同
            if mkt_label == 'AH':
                h_key, a_key = '主水', '客水'
            else:
                h_key, a_key = '大球水', '小球水'

            results.append({
                'company': name,
                'market': mkt_label,
                'open_plate': op.get('盘口', '?'),
                'close_plate': cl.get('盘口', '?'),
                'open_water': f"{op.get(h_key, '?')}/{op.get(a_key, '?')}",
                'close_water': f"{cl.get(h_key, '?')}/{cl.get(a_key, '?')}",
                'stale': stale,
                'freshness': freshness,
                'plate_history': ph_hist,
                'rows': len(d.get('历史全行', [])),
            })
    return results

if __name__ == '__main__':
    data = json.load(sys.stdin)
    rows = extract(data)
    # Compact table output
    print(f"{'Company':<18} {'Mkt':<3} {'开盘→终盘':<16} {'终水':<12} {'Stale':<6} {'时效':<10} {'行':>3}")
    print('-' * 75)
    for r in rows:
        if r.get('error'):
            print(f"{r['company']:<18} {r['market']:<3} -- NO DATA --")
            continue
        plate = f"{r['open_plate']}→{r['close_plate']}"
        print(f"{r['company']:<18} {r['market']:<3} {plate:<16} {r['close_water']:<12} "
              f"{'⚠️' if r['stale'] else '✅':<6} {r['freshness']:<10} {r['rows']:>3}")
    # JSON for downstream
    print('\n--- JSON ---')
    print(json.dumps(rows, ensure_ascii=False, indent=2))
