# -*- coding: utf-8 -*-
"""Congreso: indice oficial de la Camara + PTRs en PDF -> operaciones parseadas.

Fuente 100% oficial y gratuita:
  1) ZIP anual:  https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.zip
     (contiene {YEAR}FD.txt con nombre, tipo, fecha y DocID)
  2) PDF de cada PTR: https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{YEAR}/{DocID}.pdf
     se convierte a texto con pdftotext -layout (ya instalado en git-bash)

Nota: el ZIP se cachea 24h; los PDFs se cachean para siempre (no cambian).
"""
import io, os, re, csv, json, time, zipfile, subprocess, urllib.request, datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
BASE = r"C:/Users/carlo/insider-monitor"
CACHE = os.path.join(BASE, "congreso_cache")
os.makedirs(CACHE, exist_ok=True)

def get(url, binary=False, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*",
        "Referer": "https://disclosures-clerk.house.gov/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if binary else r.read().decode("utf-8", "replace")

def indice(year=None):
    """Descarga (y cachea 24h) el indice anual. Devuelve lista de dicts."""
    year = year or datetime.date.today().year
    zpath = os.path.join(CACHE, f"{year}FD.zip")
    if not (os.path.exists(zpath) and time.time() - os.path.getmtime(zpath) < 86400):
        data = get(f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip", binary=True)
        io.open(zpath, "wb").write(data)
    z = zipfile.ZipFile(zpath)
    name = f"{year}FD.txt"
    if name not in z.namelist():
        return []
    txt = z.read(name).decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(txt), delimiter="\t"))
    return rows

def ptr_recientes(dias=30, year=None):
    """PTRs (FilingType == 'P') archivados en los ultimos N dias."""
    year = year or datetime.date.today().year
    corte = datetime.date.today() - datetime.timedelta(days=dias)
    out = []
    for r in indice(year):
        if (r.get("FilingType") or "").strip() != "P":
            continue
        try:
            m, d, y = (r["FilingDate"] or "").split("/")
            fecha = datetime.date(int(y), int(m), int(d))
        except Exception:
            continue
        if fecha >= corte:
            r["_fecha"] = fecha.isoformat()
            out.append(r)
    out.sort(key=lambda r: r["_fecha"], reverse=True)
    return out

# linea tipo: "  SP  Intel Corporation - Common Stock  P  05/29/2026 05/29/2026 $1,000,001 - $5,000,000"
RE_OP = re.compile(
    r"^\s*(?P<owner>[A-Z]{1,3})\s+(?P<asset>.+?)\s+(?P<tipo>P|S|E)\s+"
    r"(?P<fecha>\d{2}/\d{2}/\d{4})\s+(?P<notif>\d{2}/\d{2}/\d{4})\s+"
    r"\$(?P<min>[\d,]+)\s*(?:-\s*\$?(?P<max>[\d,]+))?")
RE_TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,6})\)")
RE_TIPO_ACT = re.compile(r"\[([A-Z]{2})\]")

def txt_de_pdf(docid, year=None):
    year = year or datetime.date.today().year
    p = os.path.join(CACHE, f"{docid}.txt")
    if os.path.exists(p):
        return io.open(p, encoding="utf-8", errors="replace").read()
    url = f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{docid}.pdf"
    try:
        data = get(url, binary=True)
    except Exception:
        return ""
    pdf = os.path.join(CACHE, f"{docid}.pdf")
    io.open(pdf, "wb").write(data)
    try:
        subprocess.run(["pdftotext", "-layout", pdf, p], check=False,
                       capture_output=True, timeout=90)
    except Exception:
        return ""
    time.sleep(0.4)
    return io.open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""

def operaciones(docid, year=None):
    txt = txt_de_pdf(docid, year)
    ops = []
    if not txt:
        return ops
    crudas = txt.splitlines()
    # el rango de importe salta de linea: "$1,000,001 -" / "$5,000,000". Unir esas lineas.
    lineas = []
    i = 0
    while i < len(crudas):
        l = crudas[i]
        while re.search(r"\$[\d,]+\s*-\s*$", l) and i + 1 < len(crudas):
            i += 1
            l = l.rstrip() + " " + crudas[i].strip()
        lineas.append(l)
        i += 1
    for i, linea in enumerate(lineas):
        m = RE_OP.match(linea)
        if not m:
            continue
        asset = re.sub(r"\s+", " ", m.group("asset")).strip()
        # el ticker suele caer en las 2 lineas siguientes (formato multipagina de la Camara)
        contexto = " ".join([asset] + [re.sub(r"\s+", " ", x).strip() for x in lineas[i+1:i+3]])
        tk = RE_TICKER.findall(contexto)
        ta = RE_TIPO_ACT.findall(contexto)
        ops.append({
            "owner": m.group("owner"),
            "activo": asset[:90],
            "ticker": tk[0] if tk else "",
            "tipo_activo": ta[0] if ta else "",
            "operacion": "COMPRA" if m.group("tipo").upper().startswith("P") else "VENTA",
            "fecha": m.group("fecha"),
            "importe_min": int(m.group("min").replace(",", "")),
            "importe_max": int(m.group("max").replace(",", "")) if m.group("max") else None,
            "opciones": "[OP]" in contexto or "option" in contexto.lower(),
        })
    return ops

def recoger(dias=30, max_pdfs=None):
    """PTRs recientes + sus operaciones, ya con el nombre del politico."""
    ptrs = ptr_recientes(dias)
    if max_pdfs:
        ptrs = ptrs[:max_pdfs]
    todo = []
    for r in ptrs:
        quien = f"{r.get('First','').strip()} {r.get('Last','').strip()}".strip()
        di = r.get("DocID")
        for op in operaciones(di, r.get("Year")):
            op.update({"politico": quien, "distrito": r.get("StateDst"),
                       "docid": di, "fecha_archivo": r["_fecha"],
                       "pdf": f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{r.get('Year')}/{di}.pdf"})
            todo.append(op)
    return todo

if __name__ == "__main__":
    idx = indice()
    print("indice:", len(idx), "filas")
    pr = ptr_recientes(45)
    print("PTRs ultimos 45 dias:", len(pr))
    for r in pr[:6]:
        print("   ", r["_fecha"], "|", (r.get("First", "") + " " + r.get("Last", "")).strip()[:34], "|", r.get("StateDst"), "| DocID", r.get("DocID"))
    print()
    print("operaciones del ultimo PTR:")
    if pr:
        ops = operaciones(pr[0]["DocID"], pr[0].get("Year"))
        print("  politico:", (pr[0].get("First","") + " " + pr[0].get("Last","")).strip(), "| operaciones:", len(ops))
        for o in ops[:12]:
            print(f"   {o['fecha']} {o['operacion']:6} {o['ticker'] or '(sin ticker)':8} {o['importe_min']:>10,} - {o['importe_max'] or 0:>10,} | {o['activo'][:48]}")
