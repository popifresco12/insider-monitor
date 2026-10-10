# -*- coding: utf-8 -*-
"""Fetcher de Form 4 (insiders SEC) + detector de movimientos raros.

Fuente: SEC EDGAR full-text search (oficial, gratis, sin key).
Output: ~/insider-monitor/data.json
"""
import json, io, os, re, time, urllib.request, urllib.parse, datetime, collections, html

UA = "MonitorInsiders/1.0 (carlosgonzvali@gmail.com)"
BASE = r"C:/Users/carlo/insider-monitor"
os.makedirs(BASE, exist_ok=True)

def get(url, accept="application/json", retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))

def dias_atras(n):
    d = datetime.date.today() - datetime.timedelta(days=n)
    return d.isoformat()

# ── 1. listado de Form 4 de los ultimos N dias ──
def listar_form4(dias=2):
    out = []
    for pagina in range(0, 4):                     # hasta 400 filings
        q = urllib.parse.urlencode({"q": "", "forms": "4", "dateRange": "custom",
                                    "startdt": dias_atras(dias), "enddt": dias_atras(0), "from": pagina * 100})
        d = json.loads(get(f"https://efts.sec.gov/LATEST/search-index?{q}"))
        hits = d["hits"]["hits"]
        if not hits:
            break
        for h in hits:
            src = h["_source"]
            out.append({
                "acc": h["_id"].split(":")[0],
                "doc": h["_id"].split(":")[1],
                "cik": src["ciks"][0],
                "nombres": src.get("display_names") or [],
                "fecha": src.get("file_date"),
                "sic": (src.get("sics") or [None])[0],
            })
        time.sleep(0.3)
    return out

# ── 2. parsear el XML de cada Form 4 ──
def num(txt):
    try:
        return float(str(txt).replace(",", "").strip())
    except Exception:
        return 0.0

def parsear(f):
    url = f"https://www.sec.gov/Archives/edgar/data/{int(f['cik'])}/{f['acc'].replace('-','')}/{f['doc']}"
    try:
        xml = get(url, accept="application/xml")
    except Exception:
        return None
    def tag(t, s):
        m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", s, re.S)
        return (m.group(1).strip() if m else "")
    issuer = re.search(r"<issuer>(.*?)</issuer>", xml, re.S)
    issuer = issuer.group(1) if issuer else ""
    owner = re.search(r"<reportingOwner>(.*?)</reportingOwner>", xml, re.S)
    owner = owner.group(1) if owner else ""
    empresa = tag("issuerName", issuer)
    ticker = tag("issuerTradingSymbol", issuer)
    insider = tag("rptOwnerName", owner)
    es_director = bool(re.search(r"<isDirector>\s*(1|true)", owner, re.I))
    es_officer = bool(re.search(r"<isOfficer>\s*(1|true)", owner, re.I))
    cargo = tag("officerTitle", owner)
    diez_por_ciento = bool(re.search(r"<isTenPercentOwner>\s*(1|true)", owner, re.I))

    txs = []
    for blk in re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", xml, re.S):
        codigo = tag("transactionCode", blk)
        fecha = tag("transactionDate", blk) or tag("value", re.search(r"<transactionDate>(.*?)</transactionDate>", blk, re.S).group(1) if re.search(r"<transactionDate>(.*?)</transactionDate>", blk, re.S) else "")
        m = re.search(r"<transactionDate>\s*<value>(.*?)</value>", blk, re.S)
        fecha = m.group(1) if m else ""
        m = re.search(r"<transactionShares>\s*<value>(.*?)</value>", blk, re.S)
        shares = num(m.group(1)) if m else 0.0
        m = re.search(r"<transactionPricePerShare>\s*<value>(.*?)</value>", blk, re.S)
        precio = num(m.group(1)) if m else 0.0
        importe = round(shares * precio, 2)
        # validacion: descartar importes fisicamente imposibles (bug de parseo de price/shares)
        raro = False
        if importe > 2_000_000_000 or precio > 100_000 or (precio == 0 and shares > 5_000_000):
            raro = True
            if precio <= 0:
                importe = 0.0
        txs.append({"codigo": codigo, "fecha": fecha, "acciones": shares, "precio": precio,
                    "importe": importe, "dudoso": raro})
    return {
        "insider": html.unescape(insider), "empresa": html.unescape(empresa), "ticker": ticker.strip(),
        "cargo": html.unescape(cargo) or ("Director" if es_director else ("10% owner" if diez_por_ciento else ("Officer" if es_officer else ""))),
        "es_officer": es_officer, "es_director": es_director, "es_10pct": diez_por_ciento,
        "fecha_archivo": f["fecha"], "url": url, "txs": txs,
    }

# ── 3. anomalias ──
def puntuar(regs):
    avisos = []
    # a) clusters: varios insiders distintos de la MISMA empresa comprando en ventana corta
    compras = collections.defaultdict(set)
    for r in regs:
        for t in r["txs"]:
            if t["codigo"] in ("P", "p"):               # P = compra en mercado abierto
                compras[r["ticker"] or r["empresa"]].add(r["insider"])
    for emp, gente in compras.items():
        if len(gente) >= 2:
            avisos.append({"tipo": "cluster_compra", "peso": 3 * len(gente),
                           "detalle": f"{len(gente)} insiders distintos COMPRANDO en {emp}: {', '.join(sorted(gente))}"})
    # b) compras grandes
    for r in regs:
        for t in r["txs"]:
            if t.get("dudoso"):
                continue
            if t["codigo"] in ("P", "p") and t["importe"] >= 250_000:
                avisos.append({"tipo": "compra_grande", "peso": 2 + t["importe"] / 1_000_000,
                               "detalle": f"{r['insider']} ({r['cargo'] or 'insider'}) compra {t['importe']:,.0f}$ en {r['empresa']} ({r['ticker']})"})
            if t["codigo"] in ("S", "s") and t["importe"] >= 5_000_000:
                avisos.append({"tipo": "venta_masiva", "peso": 1.5 + t["importe"] / 10_000_000,
                               "detalle": f"{r['insider']} ({r['cargo'] or 'insider'}) VENDE {t['importe']:,.0f}$ en {r['empresa']} ({r['ticker']})"})
    # c) CEO/CFO comprando
    for r in regs:
        c = (r["cargo"] or "").lower()
        for t in r["txs"]:
            if t["codigo"] in ("P", "p") and any(k in c for k in ("chief executive", "ceo", "chief financial", "cfo")):
                avisos.append({"tipo": "ceo_cfo_compra", "peso": 4,
                               "detalle": f"COMPRA de {r['cargo']} ({r['insider']}) en {r['empresa']} ({r['ticker']}): {t['importe']:,.0f}$"})
    avisos.sort(key=lambda a: -a["peso"])
    return avisos

# ── ejecutar ──
print("1) listando Form 4 recientes...")
filings = listar_form4(2)
print("   filings:", len(filings))
uniq, vistos = [], set()
for f in filings:
    if f["acc"] in vistos:
        continue
    vistos.add(f["acc"])
    uniq.append(f)
print("   unicos:", len(uniq))

print("2) descargando y parseando XML (pausa 0.15s por SEC)...")
regs = []
for i, f in enumerate(uniq):
    r = parsear(f)
    if r and r["txs"]:
        regs.append(r)
    if i % 50 == 0:
        print(f"   {i}/{len(uniq)} ... {len(regs)} con transacciones")
    time.sleep(0.15)
print("   registros con transacciones:", len(regs))

avisos = puntuar(regs)
data = {
    "generado": datetime.datetime.now().isoformat(timespec="seconds"),
    "ventana_dias": 2,
    "filings_analizados": len(uniq),
    "registros": regs,
    "avisos": avisos[:40],
}
with io.open(os.path.join(BASE, "data.json"), "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=1)
print("3) guardado en", os.path.join(BASE, "data.json"))
print()
print("=== TOP AVISOS ===")
for a in avisos[:15]:
    print(f"  [{a['peso']:5.1f}] {a['tipo']:16} {a['detalle'][:120]}")
