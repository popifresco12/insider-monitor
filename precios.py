# -*- coding: utf-8 -*-
"""Precios via stooq (CSV gratis, sin key) + deteccion de compras a contracorriente.

Se importa desde fetch_insiders.py, o se puede lanzar para probar.
"""
import io, csv, time, urllib.request, datetime, json, os

UA = "MonitorInsiders/1.0 (carlosgonzvali@gmail.com)"
CACHE = r"C:/Users/carlo/insider-monitor/precios_cache.json"

def _cache_load():
    if os.path.exists(CACHE):
        try:
            return json.load(io.open(CACHE, encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _cache_save(c):
    json.dump(c, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

def serie(ticker, rango="1y"):
    """Cierres diarios de Yahoo Finance. Devuelve [(fecha, close), ...] o []."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={rango}&interval=1d")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=35) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        res = (d.get("chart") or {}).get("result") or []
        if not res:
            return []
        res = res[0]
        ts = res.get("timestamp") or []
        cs = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        out = []
        for t, c in zip(ts, cs):
            if c is None:
                continue
            out.append((datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), round(float(c), 4)))
        return out
    except Exception:
        return []

def contexto(ticker):
    """Precio actual, cambio a ~90 sesiones y drawdown desde el maximo de 1 año."""
    if not ticker or not ticker.strip():
        return {"ok": False}
    key = ticker.strip().upper()
    c = _cache_load()
    ent = c.get(key)
    s = None
    if ent:
        try:
            edad = (datetime.datetime.now() - datetime.datetime.fromisoformat(ent["ts"])).total_seconds()
            if edad < 12 * 3600:
                s = ent["serie"]
        except Exception:
            s = None
    if s is None:
        s = serie(key)
        if s:                                    # NO cachear vacios: envenenaria las siguientes 12h
            c[key] = {"serie": s, "ts": datetime.datetime.now().isoformat(timespec="seconds")}
            _cache_save(c)
        time.sleep(0.5)
    if not s:
        return {"ok": False}
    ultimo = s[-1][1]
    p90 = s[-min(90, len(s))][1] if len(s) > 5 else None
    camb90 = round(((ultimo / p90) - 1) * 100, 1) if p90 else None
    maximo = max(x[1] for x in s)
    return {"ok": True, "precio": ultimo, "cambio90": camb90,
            "drawdown": round(((ultimo / maximo) - 1) * 100, 1) if maximo else None,
            "fecha_ultimo": s[-1][0], "sesiones": len(s)}

# ── cache en memoria + utilidades para portfolios (seguras para hilos) ──
import threading
_LOCK = threading.Lock()
_MEM = None

def _mem():
    global _MEM
    with _LOCK:
        if _MEM is None:
            _MEM = _cache_load()
        return _MEM

def serie_larga(ticker, rango="2y"):
    """Serie de 2 años con cache PROPIA (la de `contexto` es de 1 año y alimenta el drawdown)."""
    if not ticker or not ticker.strip():
        return []
    k = "L2Y:" + ticker.strip().upper()
    m = _mem()
    ent = m.get(k)
    if ent:
        try:
            if (datetime.datetime.now() - datetime.datetime.fromisoformat(ent["ts"])).total_seconds() < 12 * 3600:
                return ent["serie"]
        except Exception:
            pass
    s = serie(ticker, rango)
    if s:
        with _LOCK:
            m[k] = {"serie": s, "ts": datetime.datetime.now().isoformat(timespec="seconds")}
            _cache_save(m)
    return s

def precio_fecha(ticker, fecha):
    """Cierre mas cercano ANTERIOR O IGUAL a `fecha` (YYYY-MM-DD). None si no hay datos."""
    if not ticker or not fecha:
        return None
    s = serie_larga(ticker)
    if not s:
        return None
    mejor = None
    for f, c in s:
        if f <= fecha:
            mejor = c
        else:
            break
    return mejor if mejor is not None else s[0][1]

def importe_fiable(shares, precio, ticker, fecha):
    """Devuelve (precio_por_accion, importe) saneados contra el precio de mercado.

    Algunos declarantes escriben el IMPORTE TOTAL en el campo `transactionPricePerShare`
    (caso real: IHT/WIRTH, precio 3.000.000 para 1.829.268 acciones -> 1,64 $/accion, que es
    el precio real; como precio por accion daria 5,5 billones). Si el valor esta a anos luz
    del cierre de ese dia, se reinterpreta como importe total; si tampoco cuadra, se usa el
    cierre de mercado. Las lineas pequenas (<= 100k$) no se comprueban: no compensa la consulta.
    """
    importe = round((shares or 0) * (precio or 0), 2)
    if importe <= 1_000_000:                     # lineas pequenas: no compensa consultar
        return precio, importe
    ref = precio_fecha(ticker, fecha) if ticker else None
    if not shares or not ref or not precio:
        return precio, importe
    # OJO: solo se interviene en el caso ABSURDO (el valor como precio por accion esta a anos luz
    # del de mercado). Diferencias moderadas son legales y NO se tocan: hay emisoras extranjeras que
    # declaran el precio en su divisa local (caso real: BBD a 17,37 en reales con el ADR a 3,32).
    if (precio / ref) <= 20:
        return precio, importe
    total = precio / shares                      # el campo lleva el importe total
    if 0.2 <= (total / ref) <= 5:
        return round(total, 4), round(precio, 2)
    return precio, importe                       # sin certeza: se deja el dato del formulario

if __name__ == "__main__":
    for t in ("COE", "ANET", "GGR", "BBD", "CRBG", "NVDA", "IHT"):
        ctx = contexto(t)
        if ctx.get("ok"):
            print(f"  {t:6} {ctx['precio']:>10.2f} | 90d {str(ctx['cambio90']):>7}% | desde maximo {str(ctx['drawdown']):>7}% | {ctx['sesiones']} sesiones")
        else:
            print(f"  {t:6} sin datos")
