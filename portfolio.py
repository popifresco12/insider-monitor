# -*- coding: utf-8 -*-
"""Portfolio por insider: 18 meses de Form 4 (SEC) + precios de mercado (Yahoo) -> resultado real.

Para cada insider relevante del informe diario:
  1. baja sus filings Form 4 de los ultimos MESES via data.sec.gov/submissions (oficial, gratis)
  2. parsea las transacciones reutilizando el parser de fetch_insiders.py
  3. reconstruye la POSICION dia a dia con el flag adquirido/dispuesto del propio formulario
     (asi cuentan tambien las acciones recibidas por concesion, no solo las compradas)
  4. valora a precios de mercado: latente (lo que tiene) + realizado (lo que ha vendido)

Modelo de coste: coste MEDIO por accion. Cuando el declarante regala/dona o le retienen acciones
para impuestos (codigo F) tambien se aplica el coste medio, que es lo correcto contablemente.
El precio de referencia de una adquisicion es el del formulario; si no lo trae (concesiones), el
cierre de mercado de ese dia. Precios saneados con precios.importe_fiable() (hay declarantes que
escriben el importe TOTAL en el campo de precio por accion).

Salida: portfolios.json  (se consume desde build_dashboard.py)
Uso:    py -3 portfolio.py [n_personas]
"""
import json, io, os, sys, time, datetime, collections, bisect
from concurrent.futures import ThreadPoolExecutor

BASE = r"C:/Users/carlo/insider-monitor"
sys.path.insert(0, BASE)
import fetch_insiders as fi
import precios as px

CACHE = os.path.join(BASE, "portfolio_cache.json")
OUT = os.path.join(BASE, "portfolios.json")
MESES = 18
MAX_FILINGS = 30          # por persona (los mas recientes)
TOP_PERSONAS = 60
HILOS = 6                 # descargas en paralelo (la SEC permite 10 req/s; esto va a ~3-4 req/s)

hoy = datetime.date.today()
desde = (hoy - datetime.timedelta(days=int(30.4 * MESES))).isoformat()
HOY = hoy.isoformat()

# ── cache ──
def cargar_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(io.open(CACHE, encoding="utf-8"))
        except Exception:
            return {}
    return {}

def guardar_cache(c):
    json.dump(c, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

def serie_larga(ticker, cache):
    return px.serie_larga(ticker)

# ── filings Form 4 de una persona ──
def filings_de(cik, cache):
    k = "fil:" + str(cik)
    e = cache.get(k)
    if e and str(e.get("ts", ""))[:10] == HOY:
        return e["filings"], e.get("nombre_oficial")
    try:
        d = json.loads(fi.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"))
    except Exception as ex:
        print(f"      submissions fallo: {type(ex).__name__}")
        return [], None
    rec = (d.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    accs = rec.get("accessionNumber") or []
    dates = rec.get("filingDate") or []
    docs = rec.get("primaryDocument") or []
    out = []
    for form, acc, fdate, doc in zip(forms, accs, dates, docs):
        if form == "4" and fdate >= desde and doc:
            out.append({"acc": acc, "doc": doc, "fecha": fdate})
    out.sort(key=lambda x: x["fecha"], reverse=True)
    out = out[:MAX_FILINGS]
    cache[k] = {"filings": out, "nombre_oficial": d.get("name"),
                "ts": datetime.datetime.now().isoformat(timespec="seconds")}
    return out, d.get("name")

# ── parseo de UN filing, con plan B si el documento es la version XSL ──
def parsear_filing(cik, f):
    """El `primaryDocument` de la SEC suele ser la version XSL (HTML renderizado, aunque la
    extension sea .xml) -> NO tiene <nonDerivativeTransaction> y el parseo devuelve 0 operaciones.
    El XML crudo esta en la misma carpeta del filing; si el nombre directo no vale, se busca en index.json."""
    doc = f["doc"].split("/")[-1]
    r = fi.parsear({"cik": cik, "acc": f["acc"], "doc": doc, "fecha": f["fecha"]})
    if r and r["txs"]:
        return r
    try:
        acc = f["acc"].replace("-", "")
        idx = json.loads(fi.get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/index.json"))
        for it in (idx.get("directory") or {}).get("item") or []:
            n = it.get("name", "")
            if n.endswith(".xml") and "xsl" not in n.lower() and n != doc:
                r2 = fi.parsear({"cik": cik, "acc": f["acc"], "doc": n, "fecha": f["fecha"]})
                if r2 and r2["txs"]:
                    return r2
    except Exception:
        pass
    return r

def bajar_filings(cik, fil):
    """Descarga + parsea los filings en paralelo."""
    with ThreadPoolExecutor(max_workers=HILOS) as ex:
        return [r for r in ex.map(lambda f: parsear_filing(cik, f), fil) if r]

def es_disposicion(o):
    """El formulario trae su propio flag adquirido (A) / dispuesto (D); manda sobre el codigo."""
    if o.get("ad") == "D":
        return True
    if o.get("ad") == "A":
        return False
    return (o.get("codigo") or "").upper() in ("S", "F", "D")

# ── reconstruir el portfolio ──
def portfolio(nombre, cik, cache):
    fil, nombre_oficial = filings_de(cik, cache)
    ops = []
    for r in bajar_filings(cik, fil):
        for t in r["txs"]:
            if t.get("dudoso") or not t.get("fecha"):
                continue
            ops.append({"fecha": t["fecha"], "codigo": (t["codigo"] or "").upper(), "ad": t.get("ad") or "",
                        "acciones": t["acciones"], "precio": t["precio"], "importe": t["importe"],
                        "ticker": r["ticker"], "empresa": r["empresa"]})
    ops.sort(key=lambda o: o["fecha"])

    mov = [o for o in ops if o["ticker"] and o["acciones"] and o["acciones"] > 0]
    tickers = sorted({o["ticker"] for o in mov})
    series = {}
    with ThreadPoolExecutor(max_workers=HILOS) as ex:
        for tk, s in zip(tickers, ex.map(lambda t: serie_larga(t, cache), tickers)):
            if s:
                series[tk] = dict(s)

    sin_precio = sorted(set(tickers) - set(series))
    mov = [o for o in mov if o["ticker"] in series]

    S = {}
    for tk, s in series.items():
        fs = sorted(s)
        S[tk] = (fs, [s[f] for f in fs])

    def precio_en(tk, d):
        fs, cs = S[tk]
        i = bisect.bisect_right(fs, d) - 1
        return cs[i] if i >= 0 else None

    def precio_ref(o):
        """Precio de la operacion: el del formulario si existe; si no, el cierre de ese dia."""
        if o["precio"]:
            return o["precio"]
        return px.precio_fecha(o["ticker"], o["fecha"]) or 0.0

    resumen = {"n_filings": len(fil), "n_ops": len(ops),
               "primera_fecha": mov[0]["fecha"] if mov else (ops[0]["fecha"] if ops else None),
               "n_tickers": len(series), "sin_precio": sin_precio}
    curva, posiciones = [], []

    if mov and series:
        fechas = sorted({f for tk in series for f in series[tk]})
        ordenadas = sorted(mov, key=lambda o: o["fecha"])
        pos = collections.defaultdict(float)     # acciones por ticker
        coste = collections.defaultdict(float)   # coste de referencia acumulado por ticker
        realizado = 0.0
        invertido_total = 0.0
        comprado = vendido = 0.0
        i = 0
        acum = []
        for d in fechas:
            while i < len(ordenadas) and ordenadas[i]["fecha"] <= d:
                o = ordenadas[i]
                i += 1
                tk, nn, p = o["ticker"], o["acciones"], precio_ref(o)
                if es_disposicion(o):
                    if pos[tk] > 0:
                        cm = coste[tk] / pos[tk]
                        realizado += nn * (p - cm)
                        coste[tk] -= nn * cm
                    pos[tk] -= nn
                    if pos[tk] <= 1e-9:
                        pos[tk], coste[tk] = 0.0, 0.0
                    if o["codigo"] == "S":
                        vendido += nn * p
                else:
                    pos[tk] += nn
                    coste[tk] += nn * p
                    invertido_total += nn * p
                    if o["codigo"] == "P":
                        comprado += nn * p
            v = sum(pos[tk] * (precio_en(tk, d) or 0.0) for tk in pos if pos[tk] > 0)
            c = sum(coste[tk] for tk in coste if pos[tk] > 0)
            acum.append((d, v, c, realizado + (v - c)))
        muestreo = acum[::5]
        if acum and (not muestreo or muestreo[-1][0] != acum[-1][0]):
            muestreo.append(acum[-1])
        curva = [{"f": d, "v": round(v), "i": round(c)} for (d, v, c, _) in muestreo]
        valor_final, coste_final, resultado_total = acum[-1][1], acum[-1][2], acum[-1][3]
        latente = valor_final - coste_final
        resumen.update({
            "valor_actual": round(valor_final), "coste_actual": round(coste_final),
            "latente": round(latente), "realizado": round(realizado),
            "resultado": round(resultado_total),
            "resultado_pct": round(100.0 * resultado_total / invertido_total, 1) if invertido_total else None,
            "comprado": round(comprado), "vendido": round(vendido),
            "invertido": round(coste_final),
        })
        ult = fechas[-1]
        for tk in sorted(series):
            if pos[tk] <= 0 and abs(coste[tk]) < 1:
                continue
            p = precio_en(tk, ult)
            val = pos[tk] * (p or 0.0)
            n_ops = sum(1 for o in mov if o["ticker"] == tk)
            empresa = next((o["empresa"] for o in mov if o["ticker"] == tk), "")
            posiciones.append({"ticker": tk, "empresa": empresa[:38],
                               "acciones": round(pos[tk], 2), "coste": round(coste[tk]),
                               "valor": round(val), "resultado": round(val - coste[tk]),
                               "precio": round(p, 2) if p else None, "n_ops": n_ops})
        posiciones.sort(key=lambda x: -abs(x["resultado"]))
    else:
        resumen.update({"valor_actual": 0, "coste_actual": 0, "latente": 0, "realizado": 0,
                        "resultado": 0, "resultado_pct": None, "comprado": 0, "vendido": 0, "invertido": 0})

    return {
        "nombre": nombre, "cik": cik, "nombre_oficial": nombre_oficial,
        "empresas": sorted({o["empresa"] for o in ops})[:6],
        "tickers": sorted({o["ticker"] for o in ops if o["ticker"]}),
        "ops": ops[-70:], "curva": curva, "resumen": resumen, "posiciones": posiciones[:12],
    }

# ── main ──
def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else TOP_PERSONAS
    data = json.load(io.open(os.path.join(BASE, "data.json"), encoding="utf-8"))
    regs = data["registros"]

    vol, meta = collections.defaultdict(float), {}
    for r in regs:
        if not (r.get("cik") or "").strip():
            continue
        v = sum(t["importe"] for t in r["txs"] if not t.get("dudoso") and t["importe"])
        vol[r["insider"]] += v
        meta.setdefault(r["insider"], {"cik": r["cik"].strip(), "cargo": r.get("cargo"),
                                       "cargo_largo": r.get("cargo_largo"), "empresa": r["empresa"],
                                       "ticker": r["ticker"]})
    for a in (data.get("avisos") or []) + (data.get("avisos_conjuntos") or []):
        det = a.get("detalle") or ""
        for nombre in meta:
            if nombre and nombre in det:
                vol[nombre] += 1e9
    seleccion = sorted(vol.items(), key=lambda x: -x[1])[:n]
    print(f"personas con CIK: {len(vol)} | seleccionadas: {len(seleccion)} | ventana: {MESES} meses (desde {desde})")

    cache = cargar_cache()
    out = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(io.open(OUT, encoding="utf-8"))
            out = {k: v for k, v in prev.items() if v.get("_fecha") == HOY}
        except Exception:
            out = {}

    for i, (nombre, _) in enumerate(seleccion, 1):
        m = meta[nombre]
        if nombre in out:
            print(f"  [{i}/{len(seleccion)}] {nombre[:38]:38} (cache)")
            continue
        try:
            p = portfolio(nombre, m["cik"], cache)
        except Exception as ex:
            print(f"  [{i}/{len(seleccion)}] {nombre[:38]:38} ERROR {type(ex).__name__}: {ex}")
            continue
        p["cargo"] = m["cargo"] or ""
        p["cargo_largo"] = m["cargo_largo"] or ""
        p["_fecha"] = HOY
        out[nombre] = p
        rs = p["resumen"]
        print(f"  [{i}/{len(seleccion)}] {nombre[:30]:30} | {rs['n_filings']:2} form | ops {rs['n_ops']:3} | "
              f"valor {rs.get('valor_actual', 0):>13,} | resultado {rs.get('resultado', 0):>13,} "
              f"({rs.get('resultado_pct')}%)")
        if i % 5 == 0:
            guardar_cache(cache)
            json.dump(out, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    guardar_cache(cache)
    json.dump(out, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    con_curva = sum(1 for v in out.values() if v["curva"])
    print(f"\nportfolios.json: {len(out)} personas | con curva de evolucion: {con_curva}")

if __name__ == "__main__":
    main()
