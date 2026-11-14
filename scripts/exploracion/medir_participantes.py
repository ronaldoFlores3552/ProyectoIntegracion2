"""Participantes de OCDS Perú en las adjudicaciones 2023-2024."""
import collections as C
import gzip
import json
import re
import sys
from datetime import datetime, timedelta

files = sys.argv[1:]
WIN = {2023, 2024}


def year_lima(s):
    if not s:
        return None
    return (datetime.fromisoformat(s.replace("Z", "+00:00")) - timedelta(hours=5)).year


def supplier_class(sid, name):
    m = re.fullmatch(r"PE-RUC-(\d+)", sid or "")
    n = (name or "").upper()
    if m and len(m.group(1)) == 11:
        p = m.group(1)[:2]
        if p == "20":
            return "RUC20 persona jurídica"
        if p == "10":
            return "RUC10 persona natural"
        return f"RUC{p} otro"
    if "CONSORCIO" in n:
        return "ID corto, nombre consorcio"
    return "ID corto u otro esquema"


def buyer_type(name):
    n = (name or "").upper()
    rules = [
        ("Municipalidad distrital", r"MUNICIPALIDAD (DEL CENTRO POBLADO|DE CENTRO POBLADO|DISTRITAL)|CENTRO POBLADO"),
        ("Municipalidad provincial", r"MUNICIPALIDAD (PROVINCIAL|METROPOLITANA)"),
        ("Gobierno regional", r"GOBIERNO REGIONAL|REGION |^REGIÓN|DIRECCION REGIONAL|DIRECCIÓN REGIONAL|GERENCIA (SUB)?REGIONAL"),
        ("Salud", r"HOSPITAL|SALUD|ESSALUD|RED ASISTENCIAL|INSTITUTO NACIONAL (DE ENFERMEDADES|MATERNO|DE SALUD|DEL NIÑO|DE CIENCIAS NEUROL|DE OFTALM|DE REHABIL|CARDIOV)|DIRIS|INEN|CENARES"),
        ("Educación", r"UNIVERSIDAD|UGEL|UNIDAD DE GESTION EDUCATIVA|UNIDAD DE GESTIÓN EDUCATIVA|EDUCACION|EDUCACIÓN|INSTITUTO (DE EDUCACION|SUPERIOR|PEDAG)"),
        ("Defensa e interior", r"EJERCITO|EJÉRCITO|MARINA DE GUERRA|FUERZA AEREA|FUERZA AÉREA|POLICIA|POLICÍA|COMANDO|DEFENSA|INTERIOR|INPE"),
        ("Empresa pública", r"S\.A\.|SEDAPAL|PETROPERU|PETRÓLEOS|ELECTRO|EMPRESA|EPS |SERVICIO DE AGUA|SIMA|ENAPU|CORPAC|BANCO"),
        ("Gobierno nacional (otros)", r"MINISTERIO|PROGRAMA|SUPERINTENDENCIA|ORGANISMO|AUTORIDAD|INSTITUTO|SERVICIO NACIONAL|PODER JUDICIAL|MINISTERIO PUBLICO|JURADO|CONTRALORIA|CONGRESO|PRESIDENCIA|DESPACHO|PROYECTO ESPECIAL|SUNAT|RENIEC|ONPE|DEFENSORIA|TRIBUNAL|CONSEJO|ACADEMIA|AGENCIA|CENTRO NACIONAL|FONDO|COMISION|OFICINA"),
    ]
    for label, pat in rules:
        if re.search(pat, n):
            return label
    return "Otro / no clasificado"


seen_ocid = C.Counter()
roles = C.Counter()
buyers = {}
sup = C.defaultdict(lambda: {"awards": 0, "buyers": set(), "name": None, "amount_single_pen": 0.0})
award_n = 0
award_multi = 0
award_amt_by_class = C.Counter()
award_n_by_class = C.Counter()
proc = []
tenderer_ids = C.Counter()
tenderer_wins = C.Counter()
cons_with_members = 0
cons_total = set()
for f in files:
    # Los releases OCDS se publican en UTF-8; declararlo evita depender de cp1252 en Windows.
    with gzip.open(f, "rt", encoding="utf-8") as h:
        for line in h:
            r = json.loads(line)
            seen_ocid[r["ocid"]] += 1
            parties = {p["id"]: p for p in r.get("parties", [])}
            for p in r.get("parties", []):
                roles[tuple(sorted(p.get("roles", [])))] += 1
            win_awards = [a for a in r.get("awards", []) if year_lima(a.get("date")) in WIN]
            if not win_awards:
                continue
            b = r.get("buyer", {})
            bid = b.get("id")
            bp = parties.get(bid, {})
            addr = bp.get("address") or {}
            if bid not in buyers:
                buyers[bid] = {"name": b.get("name"), "dept": addr.get("department"), "awards": 0, "procs": 0,
                               "type": buyer_type(b.get("name")), "suppliers": set()}
            buyers[bid]["procs"] += 1
            t = r.get("tender", {})
            tl = t.get("tenderers") or []
            tids = {x.get("id") for x in tl}
            winners = set()
            for a in win_awards:
                award_n += 1
                buyers[bid]["awards"] += 1
                ss = a.get("suppliers") or []
                if len(ss) > 1:
                    award_multi += 1
                v = a.get("value") or {}
                for s in ss:
                    sid, nm = s.get("id"), s.get("name")
                    winners.add(sid)
                    d = sup[sid]
                    d["awards"] += 1
                    d["buyers"].add(bid)
                    d["name"] = nm
                    buyers[bid]["suppliers"].add(sid)
                    cls = supplier_class(sid, nm)
                    award_n_by_class[cls] += 1
                    if len(ss) == 1 and v.get("currency") == "PEN" and v.get("amount") is not None:
                        award_amt_by_class[cls] += float(v["amount"])
                        d["amount_single_pen"] += float(v["amount"])
                    if "CONSORCIO" in (nm or "").upper():
                        cons_total.add(sid)
            for x in tl:
                tenderer_ids[x.get("id")] += 1
                if x.get("id") in winners:
                    tenderer_wins[x.get("id")] += 1
            proc.append({
                "method": t.get("procurementMethod"), "details": t.get("procurementMethodDetails"),
                "cat": t.get("mainProcurementCategory"),
                "n": t.get("numberOfTenderers"), "len": len(tl), "has_list": "tenderers" in t,
                "winner_missing": bool(winners) and not winners <= tids,
            })

for sid, d in sup.items():
    if "INTEGRADO POR" in (d["name"] or "").upper():
        cons_with_members += 1


def pct(a, b):
    return f"{100 * a / b:.1f} %" if b else "n/a"


out = {}
print("== Universo")
print("registros/ocid únicos:", len(seen_ocid), "| ocid repetidos entre archivos:", sum(1 for v in seen_ocid.values() if v > 1))
print("procesos con adjudicación 2023-2024:", len(proc), "| adjudicaciones:", award_n, "| con varios proveedores:", award_multi)
print("compradores:", len(buyers), "| proveedores adjudicados:", len(sup))
print("\n== Roles de parties (combinaciones, todos los registros)")
for k, v in roles.most_common(12):
    print(v, k)

print("\n== Compradores")
deps = C.Counter(b["dept"] for b in buyers.values())
print("con departamento:", pct(sum(v for k, v in deps.items() if k), len(buyers)), "| departamentos distintos:", len([k for k in deps if k]))
print("top departamentos (n compradores):", deps.most_common(8))
types = C.Counter(b["type"] for b in buyers.values())
aw_types = C.Counter()
for b in buyers.values():
    aw_types[b["type"]] += b["awards"]
for k, v in types.most_common():
    print(f"  {k}: {v} compradores ({pct(v, len(buyers))}), {pct(aw_types[k], award_n)} de adjudicaciones")
aw = sorted(b["awards"] for b in buyers.values())
q = lambda s, p: s[int(p * (len(s) - 1))]
print("adjudicaciones por comprador: p25", q(aw, .25), "mediana", q(aw, .5), "p75", q(aw, .75), "p99", q(aw, .99), "max", aw[-1])
ns = sorted(len(b["suppliers"]) for b in buyers.values())
print("proveedores distintos por comprador: mediana", q(ns, .5), "p75", q(ns, .75), "max", ns[-1])
print("compradores con >=10 adjudicaciones:", pct(sum(1 for a in aw if a >= 10), len(aw)), "| >=30:", pct(sum(1 for a in aw if a >= 30), len(aw)))

print("\n== Proveedores adjudicados")
cls = C.Counter(supplier_class(s, d["name"]) for s, d in sup.items())
tot_amt = sum(award_amt_by_class.values())
tot_n = sum(award_n_by_class.values())
for k, v in cls.most_common():
    print(f"  {k}: {v} proveedores ({pct(v, len(sup))}) | {pct(award_n_by_class[k], tot_n)} de filas adjudicación-proveedor | {pct(award_amt_by_class[k], tot_amt)} del monto PEN de adjudicaciones con un solo proveedor")
print("consorcios (por nombre):", len(cons_total), "| con integrantes en el nombre ('Integrado por'):", cons_with_members)
sa = sorted(d["awards"] for d in sup.values())
sb = sorted(len(d["buyers"]) for d in sup.values())
print("adjudicaciones por proveedor: mediana", q(sa, .5), "p75", q(sa, .75), "p99", q(sa, .99), "max", sa[-1])
print("proveedores con 1 sola adjudicación:", pct(sum(1 for a in sa if a == 1), len(sa)), "| con 1 solo comprador:", pct(sum(1 for b in sb if b == 1), len(sb)))
print("proveedores con >=5 compradores:", pct(sum(1 for b in sb if b >= 5), len(sb)))

print("\n== Postores (tender.tenderers)")
P = len(proc)
print("procesos con lista de postores:", pct(sum(p["has_list"] and p["len"] > 0 for p in proc), P))
print("procesos con numberOfTenderers:", pct(sum(p["n"] is not None for p in proc), P))
both = [p for p in proc if p["n"] is not None and p["len"] > 0]
print("numberOfTenderers == len(lista) en", pct(sum(p["n"] == p["len"] for p in both), len(both)), "de los que tienen ambos")
with_list = [p for p in proc if p["len"] > 0]
print("procesos con lista que omiten al menos un ganador:", sum(p["winner_missing"] for p in with_list), "de", len(with_list))
nt = C.Counter(min(p["len"], 6) for p in proc if p["len"] > 0)
print("distribución n.º postores (6 = 6+):", sorted(nt.items()))
print("postores distintos:", len(tenderer_ids), "| proveedores adjudicados:", len(sup), "| postores que nunca ganaron en la ventana:", pct(sum(1 for t in tenderer_ids if tenderer_wins[t] == 0), len(tenderer_ids)))

print("\n== Método")
md = C.Counter((p["method"], p["details"]) for p in proc)
for (m, d), v in md.most_common(15):
    sub = [p for p in proc if p["method"] == m and p["details"] == d and p["len"] > 0]
    single = sum(p["len"] == 1 for p in sub)
    print(f"  {m} | {d}: {v} procesos ({pct(v, P)}) | postor único {pct(single, len(sub))} de {len(sub)} con lista")
for cat in ("goods", "services", "works"):
    sub = [p for p in proc if p["cat"] == cat and p["len"] > 0]
    print(f"  categoría {cat}: postor único {pct(sum(p['len'] == 1 for p in sub), len(sub))} de {len(sub)}")
