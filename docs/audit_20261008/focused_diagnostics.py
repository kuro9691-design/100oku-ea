"""Follow-up local identity and reference-window diagnostics, without outcomes."""
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode = True
from oku100.io import read_bars
from oku100.leak import AccessAudit,CausalSeries
from oku100.pipeline import DecisionPipeline
from scripts.ph44_h1_dow_stoporder import find_orders
from scripts.ph34_range_spread import dedup_72h

old=json.loads((Path(__file__).with_name("audit_v1.json")).read_text(encoding="utf-8"))
d1,h4,h1=[read_bars(ROOT/"data"/f"{tf}.csv") for tf in ("d1","h4","h1")]
with (ROOT/"btc_candidate_indicators.csv").open(encoding="utf-8-sig",newline="") as f:
    table=list(csv.DictReader(f))
end=datetime.fromisoformat(table[-1]["timestamp"])
frozen_h1=[b for b in h1 if b.timestamp<=end]
orders=find_orders(frozen_h1)
ph44=dedup_72h([(o.entry_index,frozen_h1[o.entry_index].timestamp,0) for o in orders if o.status=="filled"])
rows=old["ag_candidates"]
eligible=[r for r in rows if r["actionable"] and r["stop"] is not None and r["target"] is not None]
strict=[r for r in rows if r["category"]=="entry_candidate"]
pipeline=DecisionPipeline()
p=pipeline.params

def states(index):
    indexes=pipeline._resolve_indexes(d1,h4,h1,h1[index].timestamp)
    causal=[CausalSeries(b,i,AccessAudit(i)) for b,i in zip((d1,h4,h1),indexes)]
    return (
        pipeline._state(causal[0],indexes[0],p.N_d1,p.d1_fast_ma_period,p.d1_direction_ma_period,p.d1_direction_ma_period),
        pipeline._state(causal[1],indexes[1],p.N_h4,p.h4_fast_ma_period,p.h4_direction_ma_period,p.h4_direction_ma_period),
        pipeline._state(causal[2],indexes[2],p.N_h1,p.h1_fast_ma_period,p.h1_slow_ma_period,p.h1_direction_ma_period))

windows=[]
for label,center,direction,lo,hi in [("2024-07-06",30770,1,30746,30794),("2024-07-24",None,-1,31178,31212),("2024-07-28",31308,1,31284,31332)]:
    detail=[]
    for i in range(lo,hi+1):
        score=pipeline._score_direction(direction,*states(i),0)
        c=score["criteria"]
        candidate=c["A"].passed and (c["B"].passed or c["B-2"].passed) and all(c[k].passed for k in ("C","D","E","F"))
        detail.append(dict(index=i,timestamp=h1[i].timestamp.isoformat(),candidate=candidate,
                           criteria={k:{"passed":v.passed,"evidence":v.evidence} for k,v in c.items()},
                           entry=score["entry"],stop=score["stop"],target=score["target"],rr=score["rr"]))
    windows.append(dict(article=label,reference_status="historical estimate, unverified execution timestamp",
                        direction=direction,center=center,criterion_pass_counts={k:sum(r["criteria"][k]["passed"] for r in detail) for k in ("A","B","B-2","C","D","E","F")},
                        strict_candidates=[r["index"] for r in detail if r["candidate"]],
                        center_detail=next((r for r in detail if r["index"]==center),None),rows=detail))

bar_gaps=[{"after":a.timestamp.isoformat(),"hours":(b.timestamp-a.timestamp).total_seconds()/3600} for a,b in zip(h1,h1[1:]) if (b.timestamp-a.timestamp).total_seconds()!=3600]
result={"indicator_range":{"first":table[0]["timestamp"],"last":table[-1]["timestamp"]},
        "PH44_through_indicator_end":len(ph44),"AG_strict_through_indicator_end":sum(datetime.fromisoformat(r["timestamp"])<=end for r in strict),
        "AG_backtest_eligible_signal_bars":len(eligible),
        "AG_backtest_eligible_but_not_strict":sum(r["category"]!="entry_candidate" for r in eligible),
        "AG_strict_gap_entry_count":sum((r["direction"]=="long" and h1[r["index"]].open>r["entry"]) or (r["direction"]=="short" and h1[r["index"]].open<r["entry"]) for r in strict),
        "AG_strict_warnings":dict(Counter(w for r in strict for w in r["warnings"])),
        "h1_non_hourly_steps":bar_gaps,"windows":windows,
        "note":"Signal bars are not trades; position occupancy was not simulated. No performance computed."}
with Path(__file__).with_name("focused.json").open("x",encoding="utf-8") as f:
    json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps({k:v for k,v in result.items() if k!="windows"},ensure_ascii=False,indent=2))
for window in windows:
    print(json.dumps({k:v for k,v in window.items() if k!="rows"},ensure_ascii=False,indent=2))
