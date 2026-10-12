# -*- coding: utf-8 -*-
"""Genera index.html (dashboard) desde data.json + portfolios.json.

Cambios v2:
 - graficos ARREGLADOS: las barras usaban una variable `c` inexistente -> error de JS y
   los dos cuadros salian vacios. Ahora los colores son literales.
 - cargos con empresa ("Consejero de BANK BRADESCO" en vez de "Director").
 - mas secciones: KPIs ampliados, evolucion por dia, empresas por movimiento neto,
   insiders mas activos, clusters, contracorriente, congreso agrupado por politico.
 - NOMBRES CLICABLES: abre el portfolio de esa persona (evolucion + ganado/perdido).
"""
import json, io, os, html, collections

BASE = r"C:/Users/carlo/insider-monitor"
data = json.load(io.open(os.path.join(BASE, "data.json"), encoding="utf-8"))
regs = data["registros"]
avisos = data["avisos"]
port = {}
pp = os.path.join(BASE, "portfolios.json")
if os.path.exists(pp):
    port = json.load(io.open(pp, encoding="utf-8"))

def fmt(n):
    return f"{n:,.0f}".replace(",", ".")

def e(t):
    return html.escape(str(t if t is not None else ""))

# ── filas de compras / ventas ──
compras, ventas = [], []
for r in regs:
    for t in r["txs"]:
        if t.get("dudoso") or not t["importe"]:
            continue
        fila = {"insider": r["insider"], "cargo": r.get("cargo") or "", "cargo_largo": r.get("cargo_largo") or r.get("cargo") or "",
                "empresa": r["empresa"], "ticker": r["ticker"], "fecha": t["fecha"], "importe": t["importe"],
                "acciones": t["acciones"], "precio": t["precio"], "codigo": t["codigo"],
                "cambio90": r.get("cambio90")}
        if t["codigo"] in ("P", "p"):
            compras.append(fila)
        elif t["codigo"] in ("S", "s"):
            ventas.append(fila)
compras.sort(key=lambda x: -x["importe"])
ventas.sort(key=lambda x: -x["importe"])
total_c = sum(c["importe"] for c in compras)
total_v = sum(v["importe"] for v in ventas)

# ── agregado por persona ──
per = {}
for r in regs:
    n = r["insider"]
    d = per.setdefault(n, {"n": 0, "compra": 0.0, "venta": 0.0, "empresas": set(), "cargo": r.get("cargo") or "",
                           "cargo_largo": r.get("cargo_largo") or "", "fecha": ""})
    for t in r["txs"]:
        if t.get("dudoso") or not t["importe"]:
            continue
        if t["codigo"] in ("P", "p"):
            d["compra"] += t["importe"]
            d["n"] += 1
        elif t["codigo"] in ("S", "s"):
            d["venta"] += t["importe"]
            d["n"] += 1
        if t["fecha"] > d["fecha"]:
            d["fecha"] = t["fecha"]
    d["empresas"].add(r["ticker"] or r["empresa"][:18])
activos = sorted([{**v, "nombre": k, "neto": v["compra"] - v["venta"], "empresas": sorted(v["empresas"])[:3]}
                  for k, v in per.items()], key=lambda x: -(x["compra"] + x["venta"]))[:25]

# ── por dia (compras vs ventas) ──
por_dia = collections.defaultdict(lambda: {"c": 0.0, "v": 0.0})
for c in compras:
    por_dia[c["fecha"]]["c"] += c["importe"]
for v in ventas:
    por_dia[v["fecha"]]["v"] += v["importe"]
dias = sorted(por_dia)

# ── por empresa (movimiento neto) ──
por_emp = collections.defaultdict(lambda: {"c": 0.0, "v": 0.0, "gente": set()})
for x in compras:
    k = x["ticker"] or x["empresa"][:16]
    por_emp[k]["c"] += x["importe"]
    por_emp[k]["gente"].add(x["insider"])
for x in ventas:
    k = x["ticker"] or x["empresa"][:16]
    por_emp[k]["v"] += x["importe"]
    por_emp[k]["gente"].add(x["insider"])
emps = sorted([{**v, "k": k, "neto": v["c"] - v["v"], "gente": len(v["gente"])} for k, v in por_emp.items()],
              key=lambda x: -abs(x["neto"]))[:12]

# ── clusters (varios insiders comprando la misma empresa) ──
cl_comp = collections.defaultdict(set)
for c in compras:
    cl_comp[c["ticker"] or c["empresa"]].add(c["insider"])
clusters = sorted([(k, sorted(v)) for k, v in cl_comp.items() if len(v) >= 2], key=lambda x: -len(x[1]))[:10]

# ── contracorriente (compras con la accion hundida) ──
contra = [c for c in compras if c.get("cambio90") is not None and c["cambio90"] <= -25]
contra.sort(key=lambda x: x["cambio90"])

# ── congreso ──
cong = data.get("congreso") or {}
ops_cong = cong.get("operaciones") or []
pol = collections.defaultdict(lambda: {"n": 0, "compra": 0.0, "venta": 0.0, "tk": set()})
for o in ops_cong:
    p = pol[o["politico"]]
    p["n"] += 1
    imp = o.get("importe_max") or o.get("importe_min") or 0
    if o["operacion"] == "COMPRA":
        p["compra"] += imp
    else:
        p["venta"] += imp
    if o["ticker"]:
        p["tk"].add(o["ticker"])
politicos = sorted([{**v, "nombre": k, "tk": sorted(v["tk"])[:6]} for k, v in pol.items()],
                   key=lambda x: -(x["compra"] + x["venta"]))

TIPOS = {"cluster_compra": "clúster de compras", "compra_grande": "compra grande", "venta_masiva": "venta masiva",
         "ceo_cfo_compra": "CEO/CFO comprando", "contracorriente": "a contracorriente",
         "congreso_compra_grande": "Congreso · compra grande", "congreso_opciones": "Congreso · opciones"}

# ═══ filas HTML ═══
def cl_attrs(nombre, cual="p"):
    if nombre in port:
        return f' class="cl" data-{cual}="{e(nombre)}"', " ↗"
    return ' class=""', ""

def fila_tabla(x, importe_txt, color):
    at, flecha = cl_attrs(x["insider"])
    cambio = x.get("cambio90")
    cam = f'{cambio:+.0f}%' if cambio is not None else "—"
    camcl = "up" if (cambio or 0) >= 0 else "dn"
    return (f'<tr{at}><td><b>{e(x["insider"])}</b>{flecha}</td>'
            f'<td title="{e(x.get("cargo_largo") or "")}">{e(x["cargo"] or "—")}</td>'
            f'<td><b>{e(x["ticker"] or x["empresa"][:26])}</b><br><span class="dimsub">{e(x["empresa"][:34])}</span></td>'
            f'<td>{e(x["fecha"])}</td><td class="{color}">{importe_txt}</td>'
            f'<td>{x["precio"]:,.2f}</td><td class="{camcl}">{cam}</td></tr>')

filas_compra = "".join(fila_tabla(c, f'{fmt(c["importe"])}$', "up") for c in compras[:25])
filas_venta = "".join(fila_tabla(v, f'{fmt(v["importe"])}$', "dn") for v in ventas[:25])

filas_activos = "".join(
    f'<tr{cl_attrs(a["nombre"])[0]}><td><b>{e(a["nombre"])}</b>{cl_attrs(a["nombre"])[1]}</td>'
    f'<td title="{e(a["cargo_largo"])}">{e(a["cargo"] or "—")}</td><td>{a["n"]}</td>'
    f'<td class="up">{fmt(a["compra"])}$</td><td class="dn">{fmt(a["venta"])}$</td>'
    f'<td class="{"up" if a["neto"] >= 0 else "dn"}">{fmt(a["neto"])}$</td>'
    f'<td class="dimsub">{e(", ".join(a["empresas"]))}</td></tr>'
    for a in activos)

filas_pol = "".join(
    f'<tr class="cl" data-c="{e(p["nombre"])}"><td><b>{e(p["nombre"])}</b> ↗</td><td>{p["n"]}</td>'
    f'<td class="up">{fmt(p["compra"])}$</td><td class="dn">{fmt(p["venta"])}$</td>'
    f'<td class="dimsub">{e(", ".join(p["tk"]))}</td></tr>'
    for p in politicos[:25])

filas_cong = "".join(
    f'<tr><td class="cl" data-c="{e(o["politico"])}">{e(o["politico"])}</td><td>{e(o["fecha"])}</td>'
    f'<td class="{"up" if o["operacion"] == "COMPRA" else "dn"}">{e(o["operacion"])}</td>'
    f'<td><b>{e(o["ticker"] or "—")}</b></td>'
    f'<td>{(fmt(o["importe_min"]) + " - " + fmt(o["importe_max"]) if o.get("importe_max") else "> " + fmt(o["importe_min"])) if o.get("importe_min") else "—"}</td>'
    f'<td class="dimsub">{e(o["activo"][:34])}</td></tr>'
    for o in ops_cong[:40])

avisos_html = "".join(
    f'<div class="aler"><b>{e(a["detalle"])}</b><div class="m">{e(TIPOS.get(a["tipo"], a["tipo"]))} · peso {a["peso"]:.1f}</div></div>'
    for a in avisos[:16]) or '<div class="m">Sin avisos.</div>'

clusters_html = "".join(
    f'<div class="aler"><b>{e(k)}</b> · {len(v)} insiders comprando<div class="m">{e(", ".join(v))}</div></div>'
    for k, v in clusters) or '<div class="m">Sin clústeres.</div>'

contra_html = "".join(
    f'<div class="aler"><b>{e(c["insider"])}</b> compra {fmt(c["importe"])}$ en <b>{e(c["ticker"])}</b> '
    f'<span class="dn">{c["cambio90"]:+.0f}% en 90 días</span><div class="m">{e(c["cargo_largo"])}</div></div>'
    for c in contra[:8]) or '<div class="m">Ninguna compra grande con la acción hundida.</div>'

# ═══ datos para el JS ═══
JS_COMP = [{"n": (c["insider"] + " · " + (c["ticker"] or c["empresa"])[:12]), "v": round(c["importe"])} for c in compras[:12]]
JS_VENT = [{"n": (v["insider"] + " · " + (v["ticker"] or v["empresa"])[:12]), "v": round(v["importe"])} for v in ventas[:12]]
JS_DIA = {"d": dias, "c": [round(por_dia[d]["c"]) for d in dias], "v": [round(por_dia[d]["v"]) for d in dias]}
JS_EMP = [{"n": x["k"], "v": round(x["neto"])} for x in emps]
JS_PORT = {k: {"cargo": v.get("cargo_largo") or v.get("cargo") or "", "empresas": v.get("empresas", [])[:4],
               "curva": v.get("curva", []), "resumen": v.get("resumen", {}),
               "posiciones": v.get("posiciones", [])[:8],
               "ops": [{kk: o.get(kk) for kk in ("fecha", "codigo", "acciones", "precio", "importe", "ticker")}
                       for o in v.get("ops", [])[-25:]]}
           for k, v in port.items()}
JS_CONG = {p["nombre"]: {"n": p["n"], "compra": round(p["compra"]), "venta": round(p["venta"]), "tk": p["tk"],
                         "ops": [{"f": o["fecha"], "op": o["operacion"], "tk": o["ticker"], "act": o["activo"][:40],
                                  "min": o.get("importe_min"), "max": o.get("importe_max")}
                                 for o in ops_cong if o["politico"] == p["nombre"]][:25]}
            for p in politicos}

n_con_port = sum(1 for n in per if n in port)

TPL = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor de insiders · SEC Form 4</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#12100e;--card:#1c1917;--line:#2e2926;--txt:#e8e3dd;--dim:#a8a29e;--acc:#d97706;--up:#4ade80;--dn:#f87171}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:18px}
h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:26px 0 10px;color:var(--acc)}
.sub{color:var(--dim);font-size:13px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:8px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi b{display:block;font-size:21px;margin-top:4px}
.kpi span{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}
.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:620px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase}
.up{color:var(--up)} .dn{color:var(--dn)} .dimsub{color:#a8a29e;font-size:11.5px}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;background:#3a2f22;color:var(--acc);white-space:nowrap}
.aler{border-left:3px solid var(--acc);padding:8px 12px;margin:8px 0;background:#211d1a;border-radius:0 8px 8px 0}
.aler b{font-size:14px} .aler .m{color:var(--dim);font-size:12px}
.charts{display:grid;grid-template-columns:1fr;gap:12px}
@media(min-width:900px){.charts{grid-template-columns:1fr 1fr}}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;height:420px}
canvas{max-width:100%}
a{color:var(--acc)}
tr.cl{cursor:pointer} tr.cl:hover{background:#241f1c}
td.cl{cursor:pointer}
#mask{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:50;overflow-y:auto;padding:16px}
#mask.on{display:block}
#modal{max-width:880px;margin:14px auto;background:#181512;border:1px solid var(--line);border-radius:12px;padding:18px}
#modal h3{margin:0 0 2px;font-size:19px}
#modal .x{float:right;cursor:pointer;color:var(--dim);font-size:22px;line-height:1;border:0;background:none}
.kpis2{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:12px 0}
.kpis2 div{background:#1f1b18;border:1px solid var(--line);border-radius:8px;padding:9px}
.kpis2 span{display:block;color:var(--dim);font-size:11px;text-transform:uppercase}
.kpis2 b{font-size:16px}
#cajaCurva{height:290px;margin:12px 0}
.cod{font-size:11px;padding:1px 6px;border-radius:4px;background:#2a2523}
</style></head><body>
<h1>Monitor de insiders · SEC Form 4</h1>
<div class="sub">Fuente: SEC EDGAR (oficial). Ventana: últimos __VENTANA__ días · __FILINGS__ formularios · __NREG__ declaraciones ·
__NINS__ insiders · __NPORT__ con portfolio · generado __GEN__</div>

<div class="grid">
  <div class="kpi"><span>Compras</span><b class="up">__NCOMP__</b></div>
  <div class="kpi"><span>Ventas</span><b class="dn">__NVENT__</b></div>
  <div class="kpi"><span>Importe compras</span><b class="up">__IMPC__</b></div>
  <div class="kpi"><span>Importe ventas</span><b class="dn">__IMPV__</b></div>
  <div class="kpi"><span>Neto comprador</span><b class="__NETOCLS__">__NETO__</b></div>
  <div class="kpi"><span>Avisos raros</span><b>__NAV__</b></div>
  <div class="kpi"><span>Empresas</span><b>__NEMP__</b></div>
  <div class="kpi"><span>Congreso · ops</span><b>__NCONG__</b></div>
</div>

<h2>🔍 Movimientos que llaman la atención</h2>
<div class="card">__AVISOS__</div>

<h2>📈 Cómo se mueve el dinero</h2>
<div class="charts">
  <div class="chartbox"><canvas id="cCompras"></canvas></div>
  <div class="chartbox"><canvas id="cVentas"></canvas></div>
  <div class="chartbox"><canvas id="cDia"></canvas></div>
  <div class="chartbox"><canvas id="cEmp"></canvas></div>
</div>

<h2>↘️ Compras a contracorriente <span class="badge">la señal más clásica</span></h2>
<div class="card">__CONTRA__</div>

<h2>👥 Varios insiders comprando la misma empresa</h2>
<div class="card">__CLUSTERS__</div>

<h2>🏛️ Congreso · por político</h2>
<div class="sub" style="margin:0 0 8px">Los importes declarados son <b>rangos</b> (el político declara "1-5 M$"); aquí se usa el extremo alto. Pincha en un nombre para ver sus operaciones.</div>
<div class="card wrap"><table>
<tr><th>Político</th><th>Ops</th><th>Comprado</th><th>Vendido</th><th>Tickers</th></tr>
__FILAS_POL__
</table></div>

<h2>🏛️ Congreso · operaciones declaradas</h2>
<div class="card wrap"><table>
<tr><th>Político</th><th>Fecha op.</th><th>Operación</th><th>Ticker</th><th>Importe</th><th>Activo</th></tr>
__FILAS_CONG__
</table></div>

<h2>🧑‍💼 Insiders más activos</h2>
<div class="sub" style="margin:0 0 8px">Los que llevan <b>↗</b> abren su portfolio: evolución y si han ganado o perdido.</div>
<div class="card wrap"><table>
<tr><th>Insider</th><th>Cargo</th><th>Ops</th><th>Compras</th><th>Ventas</th><th>Neto</th><th>Empresas</th></tr>
__FILAS_ACTIVOS__
</table></div>

<h2>Mayores compras</h2>
<div class="card wrap"><table>
<tr><th>Insider</th><th>Cargo</th><th>Empresa</th><th>Fecha</th><th>Importe</th><th>Precio</th><th>90 días</th></tr>
__FILAS_COMPRA__
</table></div>

<h2>Mayores ventas</h2>
<div class="card wrap"><table>
<tr><th>Insider</th><th>Cargo</th><th>Empresa</th><th>Fecha</th><th>Importe</th><th>Precio</th><th>90 días</th></tr>
__FILAS_VENTA__
</table></div>

<div class="sub" style="margin-top:22px">Datos públicos (SEC Form 4) con retraso de 1-2 días. Cada portfolio se reconstruye con los formularios de los últimos 18 meses: posición según el flag «adquirido/dispuesto» del propio formulario, coste medio por acción y valoración al precio de hoy. Uso informativo: <b>no es una señal de inversión</b>.</div>

<div id="mask"><div id="modal"></div></div>

<script>
const C=__JS_COMP__, V=__JS_VENT__, DIA=__JS_DIA__, EMP=__JS_EMP__;
const PORT=__JS_PORT__, CONG=__JS_CONG__;
const F=n=>Math.round(n||0).toLocaleString('es-ES');
const f2=n=>(n||0).toLocaleString('es-ES',{maximumFractionDigits:2});
const optH=(t)=>({indexAxis:'y',responsive:true,maintainAspectRatio:false,
 plugins:{legend:{display:false},title:{display:true,text:t,color:'#e8e3dd',font:{size:14}},
   tooltip:{callbacks:{label:c=>F(c.parsed.x)+'$'}}},
 scales:{x:{ticks:{color:'#a8a29e',callback:v=>(v/1e6).toFixed(0)+' M$'},grid:{color:'#2e2926'}},
         y:{ticks:{color:'#e8e3dd',font:{size:11}},grid:{display:false}}}});
new Chart(document.getElementById('cCompras'),{type:'bar',data:{labels:C.map(x=>x.n),datasets:[{label:'Compra',data:C.map(x=>x.v),backgroundColor:'#4ade80',borderRadius:4}]},options:optH('Mayores compras')});
new Chart(document.getElementById('cVentas'),{type:'bar',data:{labels:V.map(x=>x.n),datasets:[{label:'Venta',data:V.map(x=>x.v),backgroundColor:'#f87171',borderRadius:4}]},options:optH('Mayores ventas')});
new Chart(document.getElementById('cDia'),{type:'bar',data:{labels:DIA.d,datasets:[
  {label:'Compras',data:DIA.c,backgroundColor:'#4ade80',borderRadius:3},
  {label:'Ventas',data:DIA.v,backgroundColor:'#f87171',borderRadius:3}]},
 options:{responsive:true,maintainAspectRatio:false,
  plugins:{legend:{labels:{color:'#e8e3dd'}},title:{display:true,text:'Compras vs ventas por día',color:'#e8e3dd',font:{size:14}},
    tooltip:{callbacks:{label:c=>c.dataset.label+': '+F(c.parsed.y)+'$'}}},
  scales:{x:{ticks:{color:'#a8a29e',font:{size:10}},grid:{display:false}},
          y:{ticks:{color:'#a8a29e',callback:v=>(v/1e6).toFixed(0)+' M$'},grid:{color:'#2e2926'}}}}});
new Chart(document.getElementById('cEmp'),{type:'bar',data:{labels:EMP.map(x=>x.n),datasets:[
  {label:'Movimiento neto',data:EMP.map(x=>x.v),backgroundColor:EMP.map(x=>x.v>=0?'#4ade80':'#f87171'),borderRadius:4}]},
 options:optH('Empresas con más movimiento neto (comprado − vendido)')});

function cerrar(){document.getElementById('mask').classList.remove('on');document.getElementById('modal').innerHTML='';if(chCurva){chCurva.destroy();chCurva=null;}}
document.getElementById('mask').addEventListener('click',ev=>{if(ev.target.id==='mask')cerrar();});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')cerrar();});

let chCurva=null;
const NOM={P:'Compra',S:'Venta',A:'Concesión',M:'Ejercicio opciones',F:'Retención fiscal',G:'Regalo',D:'Disposición',C:'Conversión',I:'Compra (opciones)',J:'Otro'};
function abrir(n){
  const p=PORT[n];
  if(!p){cerrar();return;}
  const r=p.resumen||{}, gan=(r.resultado||0)>=0;
  const pct=(r.resultado_pct==null?'—':(r.resultado_pct>=0?'+':'')+f2(r.resultado_pct)+'%');
  let pos=''; (p.posiciones||[]).forEach(x=>{pos+='<tr><td><b>'+(x.ticker||'—')+'</b><br><span class="dimsub">'+(x.empresa||'')+'</span></td><td>'+f2(x.acciones)+'</td><td>'+F(x.coste)+'$</td><td>'+F(x.valor)+'$</td><td class="'+(x.resultado>=0?'up':'dn')+'">'+F(x.resultado)+'$</td></tr>';});
  let ops=''; (p.ops||[]).slice().reverse().forEach(o=>{const c=(o.codigo||'').toUpperCase(), esP=c==='P', esS=c==='S';
    ops+='<tr><td>'+o.fecha+'</td><td><span class="cod '+(esP?'up':esS?'dn':'dimsub')+'">'+(NOM[c]||c)+'</span></td><td>'+(o.ticker||'—')+'</td><td>'+f2(o.acciones)+'</td><td>'+f2(o.precio)+'$</td><td>'+F(o.importe)+'$</td></tr>';});
  document.getElementById('modal').innerHTML=
   '<button class="x" onclick="cerrar()">✕</button>'
   +'<h3>'+n+' <span class="badge">portfolio</span></h3>'
   +'<div class="dimsub">'+(p.cargo||'')+' · '+(p.empresas||[]).join(' · ')+'</div>'
   +'<div class="kpis2">'
   +'<div><span>Resultado total</span><b class="'+(gan?'up':'dn')+'">'+(gan?'+':'')+F(r.resultado||0)+'$ ('+pct+')</b></div>'
   +'<div><span>Latente (aún en cartera)</span><b class="'+((r.latente||0)>=0?'up':'dn')+'">'+F(r.latente||0)+'$</b></div>'
   +'<div><span>Realizado (ventas)</span><b class="'+((r.realizado||0)>=0?'up':'dn')+'">'+F(r.realizado||0)+'$</b></div>'
   +'<div><span>Valor de cartera</span><b>'+F(r.valor_actual||0)+'$</b></div>'
   +'<div><span>Coste de lo que tiene</span><b>'+F(r.coste_actual||0)+'$</b></div>'
   +'<div><span>Comprado (mercado)</span><b class="up">'+F(r.comprado||0)+'$</b></div>'
   +'<div><span>Vendido</span><b class="dn">'+F(r.vendido||0)+'$</b></div>'
   +'<div><span>Formularios 4</span><b>'+F(r.n_filings||0)+'</b></div>'
   +'</div>'
   +'<div class="dimsub">Ventana analizada: '+(r.primera_fecha||'?')+' → hoy</div>'
   +(((r.resultado_pct!=null)&&(r.resultado_pct>200||r.resultado_pct<-80))?'<div class="aler" style="border-left-color:#f87171"><b>Variación atípica ('+f2(r.resultado_pct)+'%)</b><div class="m">Los precios salen de Yahoo por el símbolo del ticker. Un emisor extranjero puede declarar el precio en su divisa local, o el símbolo puede coincidir con otra empresa: míralo con pinzas.</div></div>':'')
   +((p.curva&&p.curva.length)?'<div id="cajaCurva"><canvas id="cCurva"></canvas></div>':'<div class="dimsub" style="margin:14px 0">Sin compras ni ventas en mercado abierto: no hay evolución que dibujar.</div>')
   +(pos?'<h4 style="margin:16px 0 6px">Posiciones al cierre</h4><div class="wrap"><table><tr><th>Ticker</th><th>Acciones</th><th>Coste neto</th><th>Valor hoy</th><th>Resultado</th></tr>'+pos+'</table></div>':'')
   +(ops?'<h4 style="margin:16px 0 6px">Últimas operaciones declaradas</h4><div class="wrap"><table><tr><th>Fecha</th><th>Operación</th><th>Ticker</th><th>Acciones</th><th>Precio</th><th>Importe</th></tr>'+ops+'</table></div>':'')
   +'<div class="dimsub" style="margin-top:14px">Cómo se calcula: la posición se reconstruye con el flag «adquirido/dispuesto» de cada formulario (así cuentan también las acciones recibidas por concesión, no solo las compradas), a <b>coste medio por acción</b>, y se valora al precio de hoy. <b>Resultado total = latente (lo que aún tiene) + realizado (lo ya vendido)</b>. Ventana: 18 meses de formularios Form 4.</div>';
  document.getElementById('mask').classList.add('on');
  if(chCurva){chCurva.destroy();chCurva=null;}
  if(p.curva&&p.curva.length){
    chCurva=new Chart(document.getElementById('cCurva'),{type:'line',data:{labels:p.curva.map(x=>x.f),datasets:[
      {label:'Valor de la cartera',data:p.curva.map(x=>x.v),borderColor:'#4ade80',backgroundColor:'rgba(74,222,128,.12)',fill:true,tension:.25,pointRadius:0,borderWidth:2},
      {label:'Coste de lo que tiene',data:p.curva.map(x=>x.i),borderColor:'#a8a29e',borderDash:[5,4],fill:false,tension:.25,pointRadius:0,borderWidth:1.5}]},
     options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{color:'#e8e3dd',boxWidth:12}},tooltip:{callbacks:{label:c=>c.dataset.label+': '+F(c.parsed.y)+'$'}}},
      scales:{x:{ticks:{color:'#a8a29e',maxTicksLimit:6,font:{size:10}},grid:{color:'#2e2926'}},
              y:{ticks:{color:'#a8a29e',callback:v=>(v/1000).toFixed(0)+'k$'},grid:{color:'#2e2926'}}}}});
  }
}
function abrirCongreso(n){
  const p=CONG[n]; if(!p){return;}
  let ops=''; (p.ops||[]).forEach(o=>{ops+='<tr><td>'+o.f+'</td><td class="'+(o.op==='COMPRA'?'up':'dn')+'">'+o.op+'</td><td><b>'+(o.tk||'—')+'</b></td><td>'+(o.min?F(o.min)+(o.max?' - '+F(o.max):' +'):'—')+'$</td><td class="dimsub">'+(o.act||'')+'</td></tr>';});
  document.getElementById('modal').innerHTML=
   '<button class="x" onclick="cerrar()">✕</button><h3>'+n+' <span class="badge">Congreso</span></h3>'
   +'<div class="dimsub">Operaciones declaradas (PTR). Los importes son rangos, no cifras exactas.</div>'
   +'<div class="kpis2"><div><span>Operaciones</span><b>'+F(p.n)+'</b></div>'
   +'<div><span>Comprado (extremo alto)</span><b class="up">'+F(p.compra)+'$</b></div>'
   +'<div><span>Vendido (extremo alto)</span><b class="dn">'+F(p.venta)+'$</b></div></div>'
   +'<div class="wrap"><table><tr><th>Fecha</th><th>Operación</th><th>Ticker</th><th>Importe</th><th>Activo</th></tr>'+ops+'</table></div>';
  document.getElementById('mask').classList.add('on');
}
document.querySelectorAll('[data-p]').forEach(el=>el.addEventListener('click',()=>abrir(el.dataset.p)));
document.querySelectorAll('[data-c]').forEach(el=>el.addEventListener('click',()=>abrirCongreso(el.dataset.c)));
</script>
</body></html>"""

reemplazos = {
    "__VENTANA__": str(data.get("ventana_dias", 5)), "__FILINGS__": str(data.get("filings_analizados", 0)),
    "__NREG__": str(len(regs)), "__NINS__": str(len(per)), "__NPORT__": str(n_con_port),
    "__GEN__": e(data["generado"].replace("T", " ")),
    "__NCOMP__": str(len(compras)), "__NVENT__": str(len(ventas)),
    "__IMPC__": f"{total_c/1e6:,.1f} M$", "__IMPV__": f"{total_v/1e6:,.1f} M$",
    "__NETO__": f"{(total_c-total_v)/1e6:,.1f} M$", "__NETOCLS__": "up" if total_c >= total_v else "dn",
    "__NAV__": str(len(avisos)), "__NEMP__": str(len(por_emp)), "__NCONG__": str(len(ops_cong)),
    "__AVISOS__": avisos_html, "__CLUSTERS__": clusters_html, "__CONTRA__": contra_html,
    "__FILAS_COMPRA__": filas_compra, "__FILAS_VENTA__": filas_venta, "__FILAS_ACTIVOS__": filas_activos,
    "__FILAS_POL__": filas_pol, "__FILAS_CONG__": filas_cong,
    "__JS_COMP__": json.dumps(JS_COMP, ensure_ascii=False), "__JS_VENT__": json.dumps(JS_VENT, ensure_ascii=False),
    "__JS_DIA__": json.dumps(JS_DIA, ensure_ascii=False), "__JS_EMP__": json.dumps(JS_EMP, ensure_ascii=False),
    "__JS_PORT__": json.dumps(JS_PORT, ensure_ascii=False), "__JS_CONG__": json.dumps(JS_CONG, ensure_ascii=False),
}
HTML = TPL
for k, v in reemplazos.items():
    HTML = HTML.replace(k, v)

with io.open(os.path.join(BASE, "index.html"), "w", encoding="utf-8") as fh:
    fh.write(HTML)

print("index.html generado:", f"{len(HTML):,}", "bytes")
print(f"compras: {len(compras)} | ventas: {len(ventas)} | avisos: {len(avisos)} | insiders: {len(per)} | con portfolio: {n_con_port}")
print(f"clusters: {len(clusters)} | contracorriente: {len(contra)} | politicos: {len(politicos)} | ops congreso: {len(ops_cong)}")
