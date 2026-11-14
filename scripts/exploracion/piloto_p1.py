"""Piloto de P1: concentración y participantes por comprador y segmento CUBSO."""
import collections as C
import gzip
import json
import math
import statistics
import sys
from datetime import datetime, timedelta

WIN = {2023, 2024}
NONCOMP_DETAILS = {"Contratación Directa", "Regímen Especial", "Contratación Internacional", "Convenio",
                   "Adjudicación Abreviada"}


def year_lima(s):
    if not s:
        return None
    return (datetime.fromisoformat(s.replace("Z", "+00:00")) - timedelta(hours=5)).year


def q(values, p):
    v = sorted(values)
    return v[int(p * (len(v) - 1))] if v else None


def spearman(x, y):
    def ranks(a):
        order = sorted(range(len(a)), key=lambda i: a[i])
        r = [0.0] * len(a)
        i = 0
        while i < len(a):
            j = i
            while j + 1 < len(a) and a[order[j + 1]] == a[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy) if sx and sy else float("nan")


schemes = C.Counter()
id_len = C.Counter()
seg_cover = C.Counter()
unit = C.defaultdict(lambda: {"sup": C.Counter(), "procs": 0, "noncomp": 0, "parts": []})
buyer = C.defaultdict(lambda: {"procs": 0, "noncomp": 0, "parts": [], "type": None})
for f in sys.argv[1:]:
    # Los releases OCDS se publican en UTF-8; declararlo evita depender de cp1252 en Windows.
    with gzip.open(f, "rt", encoding="utf-8") as h:
        for line in h:
            r = json.loads(line)
            aws = [a for a in r.get("awards", []) if year_lima(a.get("date")) in WIN]
            if not aws:
                continue
            t = r.get("tender", {})
            b = r["buyer"]["id"]
            noncomp = t.get("procurementMethod") == "direct" or t.get("procurementMethodDetails") in NONCOMP_DETAILS
            nparts = len(t.get("tenderers") or [])
            segs = C.Counter()
            for it in t.get("items", []):
                c = it.get("classification") or {}
                schemes[c.get("scheme")] += 1
                cid = c.get("id") or ""
                id_len[len(cid)] += 1
                if len(cid) >= 2:
                    segs[cid[:2]] += 1
            seg = segs.most_common(1)[0][0] if segs else None
            seg_cover[seg is not None] += 1
            buyer[b]["procs"] += 1
            buyer[b]["noncomp"] += noncomp
            if not noncomp and nparts:
                buyer[b]["parts"].append(nparts)
            if seg is None:
                continue
            u = unit[(b, seg)]
            u["procs"] += 1
            u["noncomp"] += noncomp
            if not noncomp and nparts:
                u["parts"].append(nparts)
            for a in aws:
                for s in a.get("suppliers", []):
                    u["sup"][s["id"]] += 1

print("esquemas de clasificación:", schemes.most_common(4))
print("longitud de id:", id_len.most_common(4))
print("procesos con segmento (2 primeros dígitos UNSPSC):", dict(seg_cover))

for minp in (10, 20):
    units = [(k, u) for k, u in unit.items() if u["procs"] >= minp and len(u["parts"]) >= 5]
    tops = [max(u["sup"].values()) / sum(u["sup"].values()) for _, u in units]
    hhi = [sum((c / sum(u["sup"].values())) ** 2 for c in u["sup"].values()) for _, u in units]
    nc = [u["noncomp"] / u["procs"] for _, u in units]
    mp = [statistics.median(u["parts"]) for _, u in units]
    print(f"\n== unidades comprador x segmento con >= {minp} procesos y >= 5 competitivos con participantes: {len(units)}"
          f" | compradores: {len({k[0] for k, _ in units})}")
    print(f"cuota principal proveedor: mediana {q(tops, .5):.2f} p75 {q(tops, .75):.2f} p90 {q(tops, .9):.2f} max {q(tops, 1):.2f}")
    print(f"HHI: mediana {q(hhi, .5):.3f} p90 {q(hhi, .9):.3f} | HHI mínimo posible ~1/n procesos")
    print(f"% no competitivo: mediana {q(nc, .5):.2f} p90 {q(nc, .9):.2f}")
    print(f"mediana de participantes en competitivos: p10 {q(mp, .1)} mediana {q(mp, .5)} p90 {q(mp, .9)}")
    print(f"Spearman cuota principal vs mediana participantes: {spearman(tops, mp):.3f}")
    print(f"Spearman cuota principal vs % no competitivo: {spearman(tops, nc):.3f}")
    print(f"Spearman % no competitivo vs mediana participantes: {spearman(nc, mp):.3f}")
    segs = C.Counter(k[1] for k, _ in units)
    print("segmentos con más unidades:", segs.most_common(8))

bs = [v for v in buyer.values() if v["procs"] >= 10 and len(v["parts"]) >= 5]
nc = [v["noncomp"] / v["procs"] for v in bs]
mp = [statistics.median(v["parts"]) for v in bs]
print(f"\n== compradores con >= 10 procesos y >= 5 competitivos: {len(bs)}")
print(f"% no competitivo: p25 {q(nc, .25):.2f} mediana {q(nc, .5):.2f} p75 {q(nc, .75):.2f} p90 {q(nc, .9):.2f}")
print(f"mediana de participantes: p10 {q(mp, .1)} p25 {q(mp, .25)} mediana {q(mp, .5)} p75 {q(mp, .75)} p90 {q(mp, .9)}")
print(f"Spearman % no competitivo vs participantes: {spearman(nc, mp):.3f}")
