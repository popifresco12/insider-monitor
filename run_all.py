# -*- coding: utf-8 -*-
"""run_all.py — pipeline completo del monitor:
   1) insiders SEC (Form 4) + contexto de precio + deteccion de anomalias
   2) Congreso (indice oficial Camara + PTRs en PDF parseados)
   3) dashboard HTML unico con ambas secciones

Lo llama el cron. Todo gratis y oficial (SEC EDGAR + disclosures-clerk.house.gov).
"""
import io, os, sys, json, subprocess, datetime

BASE = r"C:/Users/carlo/insider-monitor"
sys.path.insert(0, BASE)

def paso(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60, flush=True)

# ── 1. insiders ──
solo_congreso = "--sin-sec" in sys.argv      # para depurar sin repetir la descarga de la SEC
paso("1/4  Insiders SEC (Form 4)")
if solo_congreso:
    print("  (omitido: --sin-sec, se reutiliza el data.json existente)")
else:
    r = subprocess.run([sys.executable, os.path.join(BASE, "fetch_insiders.py")],
                       capture_output=True, text=True, errors="replace", timeout=3600)
    print("\n".join(r.stdout.splitlines()[-8:]))
    if r.returncode != 0:
        print("  AVISO: fetch_insiders devolvio", r.returncode, r.stderr[-300:])

data = json.load(io.open(os.path.join(BASE, "data.json"), encoding="utf-8"))

# ── 2. congreso ──
paso("2/4  Congreso (indice oficial + PTRs)")
import congreso as cg
ops = []
try:
    ops = cg.recoger(dias=90, max_pdfs=120)  # 90 dias: dentro de 45 se quedaban fuera PTRs con operaciones recientes (p.ej. Pelosi/INTC de julio)
    print("  operaciones de congresistas parseadas:", len(ops))
except Exception as e:
    print("  ERROR congreso:", type(e).__name__, e)

# anomalias del congreso
avisos_c = []
por_ticker = {}
for o in ops:
    if o["tipo_activo"] == "AB":          # entidades privadas / LLC: no son valores cotizados
        continue
    clave = (o["ticker"] or o["activo"][:24])
    por_ticker.setdefault(clave, []).append(o)
    if o.get("opciones") and o["operacion"] == "COMPRA" and o["importe_min"] >= 250_000:
        avisos_c.append({"peso": 5 + o["importe_min"] / 1e6, "tipo": "congreso_opciones",
                         "detalle": f"{o['politico']} compra OPCIONES de {clave} por {o['importe_min']:,}-{o['importe_max'] or 0:,}$ ({o['fecha']})"})
    if o["importe_min"] >= 1_000_000:
        avisos_c.append({"peso": 3 + o["importe_min"] / 1e6, "tipo": "congreso_compra_grande",
                         "detalle": f"{o['politico']} {o['operacion']} de {clave} por {o['importe_min']:,}-{o['importe_max'] or 0:,}$ ({o['fecha']})"})
for clave, lista in por_ticker.items():
    gente = {o["politico"] for o in lista if o["operacion"] == "COMPRA"}
    if len(gente) >= 2:
        avisos_c.append({"peso": 4 * len(gente), "tipo": "congreso_cluster",
                         "detalle": f"{len(gente)} congresistas distintos COMPRANDO {clave}: {', '.join(sorted(gente))}"})
avisos_c.sort(key=lambda a: -a["peso"])

data["congreso"] = {"operaciones": ops, "avisos": avisos_c[:25],
                    "n_operaciones": len(ops)}


# ── 2b. cortos: interes bajista cruzado con compras de insiders ──
paso("2b/4  Cortos (posiciones bajistas) cruzados con compras")
try:
    import cortos as cr

    # que tickers merecen consulta: los que tienen compras de insiders relevantes
    compras = {}
    for reg in data["registros"]:
        tk = reg.get("ticker")
        if not tk:
            continue
        for tx in (reg.get("txs") or []):
            if tx.get("codigo") != "P":
                continue
            e = compras.setdefault(tk, {"importe": 0.0, "insiders": set(),
                                        "empresa": reg.get("empresa", "")})
            e["importe"] += (tx.get("acciones") or 0) * (tx.get("precio") or 0)
            e["insiders"].add(reg.get("insider"))

    candidatos = sorted([t for t, v in compras.items()
                         if v["importe"] >= 100_000 or len(v["insiders"]) >= 2])
    print(f"  tickers con compras relevantes: {len(candidatos)}")
    datos_c = cr.cargar(candidatos)
    print(f"  con dato de cortos: {len(datos_c)} de {len(candidatos)}")

    # filtro de cordura: fuera microcaps con volumen ridiculo (581 acciones y 70 de volumen
    # dan 8 dias de cobertura y no significan nada)
    cortos_ok = {t: v for t, v in datos_c.items()
                 if v["interes"] >= 50_000 and v["volumen_medio"] >= 20_000}

    filas_c = []
    for tk, v in cortos_ok.items():
        c = compras[tk]
        filas_c.append({"ticker": tk, "empresa": c["empresa"], "fecha": v["fecha"],
                        "interes": v["interes"], "dias_cobertura": v["dias_cobertura"],
                        "cambio_pct": v["cambio_pct"], "comprado": round(c["importe"]),
                        "n_insiders": len(c["insiders"])})
    filas_c.sort(key=lambda x: (-x["dias_cobertura"], -x["comprado"]))
    data["cortos"] = {"filas": filas_c[:25], "cobertura": [len(datos_c), len(candidatos)],
                      "fecha_dato": (filas_c[0]["fecha"] if filas_c else "")}

    # avisos: insiders comprando donde el mercado esta muy corto -> candidato a short squeeze
    nuevos = []
    for x in filas_c:
        if x["dias_cobertura"] >= 5 and x["comprado"] >= 100_000:
            nuevos.append({"peso": 6 + min(x["dias_cobertura"], 15) + min(x["comprado"] / 1e6, 5),
                           "tipo": "compra_con_cortos",
                           "detalle": (f"COMPRAN y el valor esta muy corto: {x['n_insiders']} "
                                       f"insider(s) compran {x['comprado']:,}$ en {x['ticker']} "
                                       f"mientras los cortos son el {x['dias_cobertura']:.1f} dias "
                                       f"de volumen ({x['interes']:,} acciones, {x['cambio_pct']:+.0f}% "
                                       f"vs periodo anterior)")})
    nuevos.sort(key=lambda a: -a["peso"])
    if nuevos:
        data["avisos"] = nuevos[:8] + data["avisos"]
    print(f"  avisos de squeeze: {len(nuevos[:8])}")
except Exception as e:
    print("  ERROR cortos:", type(e).__name__, e, "-> se sigue sin esta seccion")
    data["cortos"] = {"filas": [], "cobertura": [0, 0], "fecha_dato": ""}

# avisos combinados (los del congreso pesan mas por ser dinero publico + opciones)
data["avisos_conjuntos"] = (data["avisos"][:30] + avisos_c)[:45]
data["avisos_conjuntos"].sort(key=lambda a: -a["peso"])

json.dump(data, io.open(os.path.join(BASE, "data.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ── 3. portfolios por insider ──
paso("3/4  Portfolios por insider (18 meses de Form 4 + precios)")
try:
    r = subprocess.run([sys.executable, os.path.join(BASE, "portfolio.py")],
                       capture_output=True, text=True, errors="replace", timeout=5400)
    print("\n".join((r.stdout or "").splitlines()[-6:]))
    if r.returncode != 0:
        print("  AVISO: portfolio.py devolvio", r.returncode, (r.stderr or "")[-300:])
except Exception as e:
    print("  ERROR portfolio:", type(e).__name__, e, "-> el dashboard se genera igual, sin portfolios")

# ── 4. dashboard ──
paso("4/4  Dashboard")
r = subprocess.run([sys.executable, os.path.join(BASE, "build_dashboard.py")],
                   capture_output=True, text=True, errors="replace", timeout=600)
print(r.stdout[-600:] or r.stderr[-400:])

print("\nPipeline completado", datetime.datetime.now().isoformat(timespec="seconds"))
