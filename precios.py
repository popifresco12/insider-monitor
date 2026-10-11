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

if __name__ == "__main__":
    for t in ("COE", "ANET", "GGR", "BBD", "CRBG", "NVDA", "IHT"):
        ctx = contexto(t)
        if ctx.get("ok"):
            print(f"  {t:6} {ctx['precio']:>10.2f} | 90d {str(ctx['cambio90']):>7}% | desde maximo {str(ctx['drawdown']):>7}% | {ctx['sesiones']} sesiones")
        else:
            print(f"  {t:6} sin datos")
