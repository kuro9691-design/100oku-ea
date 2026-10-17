import json
d = json.load(open('docs/audit_20261017/recall_fx_articles.json', encoding='utf-8'))
print("total rows:", len(d))
by_symbol = {}
for r in d:
    by_symbol[r['symbol']] = by_symbol.get(r['symbol'], 0) + 1
print(by_symbol)
excluded = [r for r in d if r['excluded']]
print("excluded:", len(excluded))
for r in excluded:
    print(" -", r['date'], r['symbol'], r['excluded_reason'])
unconfirmed = [r for r in d if r['direction'] == '要個別確認']
print("direction unconfirmed:", len(unconfirmed))
for r in unconfirmed:
    print(" -", r['date'], r['symbol'])
buckets = {"oshime_modori": 0, "tenkan": 0, "dai3ha": 0, "other": 0}
for r in d:
    p = r['pattern']
    if '押し目' in p or '戻り目' in p or '戻り売り' in p:
        buckets["oshime_modori"] += 1
    elif 'トレンド転換' in p:
        buckets["tenkan"] += 1
    elif '第3波' in p or '波' in p:
        buckets["dai3ha"] += 1
    else:
        buckets["other"] += 1
print(buckets)
sl_known = sum(1 for r in d if not r['sl']['description'].startswith('不明'))
print("SL description present:", sl_known)
prior = sum(1 for r in d if r['prior_stopout'])
print("prior_stopout:", prior)
tp_known = sum(1 for r in d if r['tp']['stages'] > 0)
print("TP stage info present:", tp_known)
