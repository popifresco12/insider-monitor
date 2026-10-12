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
