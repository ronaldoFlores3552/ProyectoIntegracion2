"""Consorcios, concentración por comprador y tamaño de la co-participación."""
import collections as C
import gzip
import json
import sys
from datetime import datetime, timedelta

WIN = {2023, 2024}


def yl(s):
    if not s:
        return None
    return (datetime.fromisoformat(s.replace("Z", "+00:00")) - timedelta(hours=5)).year


NONCOMP = {"Contratación Directa", "Regímen Especial", "Contratación Internacional", "Convenio", "Adjudicación Abreviada"}
cons_cat = C.Counter()
all_cat = C.Counter()
cons_aw = C.Counter()
buyer_sup = C.defaultdict(C.Counter)
buyer_proc = C.Counter()
buyer_nc = C.Counter()
pairs = 0
pairs_cap = 0
part_wins = C.Counter()
part_procs = C.Counter()
for f in sys.argv[1:]:
    # Los releases OCDS se publican en UTF-8; declararlo evita depender de cp1252 en Windows.
    with gzip.open(f, "rt", encoding="utf-8") as h:
        for line in h:
            r = json.loads(line)
            t = r.get("tender", {})
            aws = [a for a in r.get("awards", []) if yl(a.get("date")) in WIN]
            if not aws:
                continue
            b = r["buyer"]["id"]
            buyer_proc[b] += 1
            if t.get("procurementMethodDetails") in NONCOMP or t.get("procurementMethod") == "direct":
                buyer_nc[b] += 1
            cat = t.get("mainProcurementCategory")
            n = len(t.get("tenderers") or [])
            pairs += n * (n - 1) // 2
            m = min(n, 30)
            pairs_cap += m * (m - 1) // 2
            for x in t.get("tenderers") or []:
                part_procs[x["id"]] += 1
            for a in aws:
                for s in a.get("suppliers", []):
                    buyer_sup[b][s["id"]] += 1
                    part_wins[s["id"]] += 1
                    all_cat[cat] += 1
                    if "CONSORCIO" in (s.get("name") or "").upper():
                        cons_cat[cat] += 1
                        cons_aw[s["id"]] += 1


def q(s, p):
    s = sorted(s)
    return s[int(p * (len(s) - 1))]


print("consorcios, % de adjudicaciones por categoría:", {k: f"{100 * cons_cat[k] / all_cat[k]:.1f} %" for k in all_cat})
v = list(cons_aw.values())
print("adjudicaciones por consorcio: mediana", q(v, .5), "| % con una sola:", f"{100 * sum(x == 1 for x in v) / len(v):.1f} %")
ncs = [buyer_nc[b] / buyer_proc[b] for b in buyer_proc]
print("% procesos no competitivos por comprador: mediana", f"{q(ncs, .5):.2f}", "p75", f"{q(ncs, .75):.2f}", "p90", f"{q(ncs, .9):.2f}")
big = [b for b in buyer_proc if sum(buyer_sup[b].values()) >= 30]
top = [max(buyer_sup[b].values()) / sum(buyer_sup[b].values()) for b in big]
print(f"compradores con >=30 adjudicaciones: {len(big)} | cuota del principal proveedor: mediana {q(top, .5):.2f} p90 {q(top, .9):.2f} max {q(top, 1):.2f}")
print("pares de co-participación (todos):", pairs, "| con tope 30 participantes por proceso:", pairs_cap)
won = sum(1 for p in part_procs if part_wins[p] > 0)
print("participantes distintos:", len(part_procs), "| ganaron alguna vez:", won, "| en >=5 procesos:", sum(1 for p in part_procs.values() if p >= 5))
