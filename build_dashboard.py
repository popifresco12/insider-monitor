# -*- coding: utf-8 -*-
"""Genera index.html (dashboard) desde data.json. Datos embebidos: sin CORS, sin fetch."""
import json, io, os, datetime

BASE = r"C:/Users/carlo/insider-monitor"
data = json.load(io.open(os.path.join(BASE, "data.json"), encoding="utf-8"))
regs, avisos = data["registros"], data["avisos"]

# ── agregados ──
compras, ventas = [], []
for r in regs:
    for t in r["txs"]:
        if t.get("dudoso") or not t["importe"]:
            continue
        fila = {"insider": r["insider"], "cargo": r["cargo"], "empresa": r["empresa"],
                "ticker": r["ticker"], "fecha": t["fecha"], "importe": t["importe"],
                "acciones": t["acciones"], "precio": t["precio"], "url": r["url"]}
        if t["codigo"] in ("P", "p"):
            compras.append(fila)
        elif t["codigo"] in ("S", "s"):
            ventas.append(fila)
compras.sort(key=lambda x: -x["importe"])
ventas.sort(key=lambda x: -x["importe"])
total_c = sum(c["importe"] for c in compras)
total_v = sum(v["importe"] for v in ventas)

tipos = {}
for a in avisos:
    tipos[a["tipo"]] = tipos.get(a["tipo"], 0) + 1

def fmt(n):
    return f"{n:,.0f}".replace(",", ".")

HTML = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor de insiders · SEC Form 4</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#12100e;--card:#1c1917;--line:#2e2926;--txt:#e8e3dd;--dim:#a8a29e;--acc:#d97706;--up:#4ade80;--dn:#f87171}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:18px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 10px;color:var(--acc)}}
.sub{{color:var(--dim);font-size:13px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:8px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}}
.kpi b{{display:block;font-size:22px;margin-top:4px}}
.kpi span{{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.4px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}}
.wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px;min-width:640px}}
th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase}}
.up{{color:var(--up)}} .dn{{color:var(--dn)}}
.badge{{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;background:#3a2f22;color:var(--acc);white-space:nowrap}}
.aler{{border-left:3px solid var(--acc);padding:8px 12px;margin:8px 0;background:#211d1a;border-radius:0 8px 8px 0}}
.aler b{{font-size:14px}} .aler .m{{color:var(--dim);font-size:12px}}
.charts{{display:grid;grid-template-columns:1fr;gap:12px}}
@media(min-width:900px){{.charts{{grid-template-columns:1fr 1fr}}}}
.chartbox{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;height:420px}}
canvas{{max-width:100%}}
a{{color:var(--acc)}}
</style></head><body>
<h1>Monitor de insiders · SEC Form 4</h1>
<div class="sub">Fuente: SEC EDGAR (oficial). Ventana: últimos {data['ventana_dias']} días · {data['filings_analizados']} formularios analizados · generado {data['generado']}</div>

<div class="grid">
  <div class="kpi"><span>Compras</span><b class="up">{len(compras)}</b></div>
  <div class="kpi"><span>Ventas</span><b class="dn">{len(ventas)}</b></div>
  <div class="kpi"><span>Importe compras</span><b class="up">{total_c/1e6:,.1f} M$</b></div>
  <div class="kpi"><span>Importe ventas</span><b class="dn">{total_v/1e6:,.1f} M$</b></div>
  <div class="kpi"><span>Avisos raros</span><b>{len(avisos)}</b></div>
</div>

<h2>🔍 Movimientos que llaman la atención</h2>
<div class="card">
{''.join(f'<div class="aler"><b>{a["detalle"]}</b><div class="m">tipo: {a["tipo"]} · peso {a["peso"]:.1f}</div></div>' for a in avisos[:14]) or '<div class="m">Sin avisos.</div>'}
</div>

<div class="charts">
  <div class="chartbox"><canvas id="cCompras"></canvas></div>
  <div class="chartbox"><canvas id="cVentas"></canvas></div>
</div>

<h2>Mayores compras</h2>
<div class="card wrap"><table>
<tr><th>Insider</th><th>Cargo</th><th>Empresa</th><th>Fecha</th><th>Importe</th><th>Precio</th></tr>
{''.join(f'<tr><td>{c["insider"]}</td><td>{c["cargo"] or "—"}</td><td><b>{c["ticker"] or c["empresa"][:26]}</b><br><span style="color:#a8a29e">{c["empresa"][:34]}</span></td><td>{c["fecha"]}</td><td class="up">{c["importe"]:,.0f}$</td><td>{c["precio"]:,.2f}</td></tr>' for c in compras[:25])}
</table></div>

<h2>Mayores ventas</h2>
<div class="card wrap"><table>
<tr><th>Insider</th><th>Cargo</th><th>Empresa</th><th>Fecha</th><th>Importe</th><th>Precio</th></tr>
{''.join(f'<tr><td>{v["insider"]}</td><td>{v["cargo"] or "—"}</td><td><b>{v["ticker"] or v["empresa"][:26]}</b><br><span style="color:#a8a29e">{v["empresa"][:34]}</span></td><td>{v["fecha"]}</td><td class="dn">{v["importe"]:,.0f}$</td><td>{v["precio"]:,.2f}</td></tr>' for v in ventas[:25])}
</table></div>

<div class="sub" style="margin-top:22px">Los datos son públicos (SEC Form 4) y llegan con retraso de 1-2 días desde la operación. Uso informativo: <b>no es una señal de inversión</b>.</div>

<script>
const C={json.dumps([{"n":(c["insider"]+" · "+(c["ticker"] or c["empresa"])[:14]),"v":round(c["importe"],0)} for c in compras[:12]], ensure_ascii=False)};
const V={json.dumps([{"n":(v["insider"]+" · "+(v["ticker"] or v["empresa"])[:14]),"v":round(v["importe"],0)} for v in ventas[:12]], ensure_ascii=False)};
const opt=(t,c)=>({{indexAxis:'y',responsive:true,maintainAspectRatio:false,
 plugins:{{legend:{{display:false}},title:{{display:true,text:t,color:'#e8e3dd',font:{{size:14}}}}}},
 scales:{{x:{{ticks:{{color:'#a8a29e',callback:v=>(v/1e6).toFixed(0)+' M$'}},grid:{{color:'#2e2926'}}}},
          y:{{ticks:{{color:'#e8e3dd',font:{{size:11}}}},grid:{{display:false}}}}}}}});
new Chart(document.getElementById('cCompras'),{{type:'bar',data:{{labels:C.map(x=>x.n),datasets:[{{label:'Compra',data:C.map(x=>x.v),backgroundColor:c,borderRadius:4}}]}},options:opt('Mayores compras', getComputedStyle(document.documentElement).getPropertyValue('--up'))}});
new Chart(document.getElementById('cVentas'),{{type:'bar',data:{{labels:V.map(x=>x.n),datasets:[{{label:'Venta',data:V.map(x=>x.v),backgroundColor:c,borderRadius:4}}]}},options:opt('Mayores ventas', getComputedStyle(document.documentElement).getPropertyValue('--dn'))}});
</script>
</body></html>"""

with io.open(os.path.join(BASE, "index.html"), "w", encoding="utf-8") as fh:
    fh.write(HTML)
print("index.html generado:", len(HTML), "bytes")
print("compras:", len(compras), "| ventas:", len(ventas), "| avisos:", len(avisos))
print("top compra:", compras[0]["insider"], compras[0]["ticker"], f'{compras[0]["importe"]:,.0f}$' if compras else "-")
