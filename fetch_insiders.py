# -*- coding: utf-8 -*-
"""Fetcher de Form 4 (insiders SEC) + detector de movimientos raros.

Fuente: SEC EDGAR full-text search (oficial, gratis, sin key).
Output: ~/insider-monitor/data.json
"""
import json, io, os, re, time, urllib.request, urllib.parse, datetime, collections, html
import precios as px          # saneado de precios/importes contra el mercado (importe_fiable)

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

TRAD = {
    "chief executive officer": "Consejero Delegado (CEO)",
    "chief financial officer": "Director Financiero (CFO)",
    "chief operating officer": "Director de Operaciones (COO)",
    "chief technology officer": "Director de Tecnologia (CTO)",
    "chief legal officer": "Director Juridico",
    "chief accounting officer": "Director de Contabilidad",
    "chief credit officer": "Director de Credito",
    "chief cust offcr": "Director de Custodia",
    "president and ceo": "Presidente y Consejero Delegado",
    "chairman and ceo": "Presidente del Consejo y Consejero Delegado",
    "ceo and president": "Consejero Delegado y Presidente",
    "head of business development": "Responsable de Desarrollo de Negocio",
    "head of r&d": "Responsable de I+D",
    "ceo": "Consejero Delegado (CEO)",
    "cfo": "Director Financiero (CFO)",
    "eco": "Consejero Delegado (CEO)",
    "president": "Presidente",
    "chairman": "Presidente del Consejo",
    "evp": "Vicepresidente Ejecutivo",
}

def traducir_cargo(raw, empresa, es_director, es_officer, es_10pct, con_empresa=False):
    """Traduce el cargo del Form 4. Los genericos ('Director', '10% owner') NO dicen de que:
    se devuelven siempre con la empresa; los titulos especificos solo llevan la empresa si con_empresa."""
    r = (raw or "").strip()
    rl = r.lower()
    suf = f" de {empresa}" if con_empresa else ""
    if rl in ("director", "board member"):
        return f"Consejero de {empresa}"
    if rl in ("10% owner", "ten percent owner"):
        return f"Accionista >10% de {empresa}"
    if rl in ("see remarks", "see explanation"):
        return f"Directivo de {empresa} (cargo detallado en las notas del formulario)"
    if not r:
        if es_director:
            return f"Consejero de {empresa}"
        if es_10pct:
            return f"Accionista >10% de {empresa}"
        if es_officer:
            return f"Directivo de {empresa}"
        return "Declarante"
    for k, v in sorted(TRAD.items(), key=lambda x: -len(x[0])):
        if k in rl:
            return v + suf
    return r + suf

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
    cargo_en = tag("officerTitle", owner)
    cik_owner = tag("rptOwnerCik", owner)
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
        m = re.search(r"<transactionAcquiredDisposedCode>\s*<value>(.*?)</value>", blk, re.S)
        ad = (m.group(1).strip().upper()[:1] if m else "")
        # saneado contra el precio de mercado: hay declarantes que escriben el IMPORTE TOTAL
        # en el campo de precio por accion (ver precios.importe_fiable)
        precio, importe = px.importe_fiable(shares, precio, ticker, fecha)
        # validacion final: descartar importes que el saneado no haya podido arreglar
        raro = False
        if importe > 2_000_000_000 or precio > 100_000:
            raro = True
            importe = 0.0
        txs.append({"codigo": codigo, "fecha": fecha, "acciones": shares, "precio": precio,
                    "importe": importe, "ad": ad, "dudoso": raro})
    emp = html.unescape(empresa)
    return {
        "insider": html.unescape(insider), "empresa": emp, "ticker": ticker.strip(),
        "cargo": traducir_cargo(html.unescape(cargo_en), emp, es_director, es_officer, diez_por_ciento),
        "cargo_largo": traducir_cargo(html.unescape(cargo_en), emp, es_director, es_officer, diez_por_ciento, con_empresa=True),
        "cargo_en": html.unescape(cargo_en),
        "cik": cik_owner.strip(),
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
                               "detalle": f"{r['insider']} ({r.get('cargo_largo') or 'insider'}) compra {t['importe']:,.0f}$ en {r['empresa']} ({r['ticker']})"})
            if t["codigo"] in ("S", "s") and t["importe"] >= 5_000_000:
                avisos.append({"tipo": "venta_masiva", "peso": 1.5 + t["importe"] / 10_000_000,
                               "detalle": f"{r['insider']} ({r.get('cargo_largo') or 'insider'}) VENDE {t['importe']:,.0f}$ en {r['empresa']} ({r['ticker']})"})
    # c) CEO/CFO comprando
    for r in regs:
        c = ((r.get("cargo_en") or "") + " " + (r.get("cargo") or "")).lower()
        for t in r["txs"]:
            if t["codigo"] in ("P", "p") and any(k in c for k in ("chief executive", "ceo", "chief financial", "cfo", "consejero delegado", "director financiero")):
                avisos.append({"tipo": "ceo_cfo_compra", "peso": 4,
                               "detalle": f"COMPRA de {r['cargo']} ({r['insider']}) en {r['empresa']} ({r['ticker']}): {t['importe']:,.0f}$"})
    # d) contracorriente: insider comprando con la accion hundida (la señal mas clasica)
    try:
        import precios as px
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import precios as px
    tickers = {}
    for r in regs:
        for t in r["txs"]:
            if t.get("dudoso") or not t["importe"]:
                continue
            if t["codigo"] in ("P", "p") and t["importe"] >= 100_000 and r["ticker"]:
                tickers.setdefault(r["ticker"], []).append((r, t))
    for ticker, items in list(tickers.items()):
        ctx = px.contexto(ticker)
        if not ctx.get("ok"):
            continue
        for r, t in items:
            r["precio_actual"] = ctx["precio"]
            r["cambio90"] = ctx["cambio90"]
            r["drawdown"] = ctx["drawdown"]
            if ctx["cambio90"] is not None and ctx["cambio90"] <= -25:
                avisos.append({"tipo": "contracorriente", "peso": 3.5 + abs(ctx["cambio90"]) / 25,
                               "detalle": f"{r['insider']} ({r.get('cargo_largo') or 'insider'}) COMPRA {t['importe']:,.0f}$ en {r['empresa']} ({ticker}) con la accion {ctx['cambio90']:.0f}% abajo en 90 dias (desde maximo {ctx['drawdown']:.0f}%)"})
            elif ctx["drawdown"] is not None and ctx["drawdown"] <= -40:
                avisos.append({"tipo": "contracorriente", "peso": 3.0,
                               "detalle": f"{r['insider']} ({r.get('cargo_largo') or 'insider'}) COMPRA {t['importe']:,.0f}$ en {r['empresa']} ({ticker}) a {ctx['drawdown']:.0f}% del maximo anual"})
    avisos.sort(key=lambda a: -a["peso"])
    return avisos

# ── ejecutar ──
def main():
    print("1) listando Form 4 recientes...")
    # ventana de 5 dias: en fin de semana o festivo federal el rango de 2 dias queda VACIO
    # (la SEC no publica sabados, domingos ni festivos) y no hay que perder el informe del dia.
    filings = listar_form4(5)
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
    # GUARDA: si no hay registros NO se sobrescribe data.json (un festivo o un fallo de red
    # dejaba el informe vacio y se perdia el del dia anterior). Se conserva el anterior.
    prev_path = os.path.join(BASE, "data.json")
    if not regs:
        print("!! 0 registros: se CONSERVA el data.json anterior (no se sobrescribe)")
        return
    data = {
        "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "ventana_dias": 5,
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

if __name__ == "__main__":
    main()
