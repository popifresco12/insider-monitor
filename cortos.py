# -*- coding: utf-8 -*-
"""cortos.py — posiciones cortas por ticker, gratis y sin clave.

Fuente: `api.nasdaq.com/api/quote/<TICKER>/short-interest` (JSON, sin autenticacion).
FINRA publica el dato dos veces al mes (liquidacion del 15 y del ultimo dia del mes), asi que
se cachea varios dias.

Lo que aporta al monitor: `dias_cobertura` (cuanto tardaria un corto en recomprar su posicion
con el volumen medio) y la variacion frente al periodo anterior. Cruzado con compras de
directivos es la senal clasica de short squeeze: insiders comprando y mucho dinero apostando
a la baja.

Uso:
    from cortos import cargar
    cortos = cargar(["INTC", "PLTR"])   # {ticker: {...}}
"""
from __future__ import annotations

import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cortos_cache.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
URL = "https://api.nasdaq.com/api/quote/{}/short-interest?assetClass=stocks"

# FINRA publica dos veces al mes: 4 dias de cache es mas que suficiente y evita 120 peticiones diarias.
DIAS_CACHE = 4
MAX_HILOS = 1
TIMEOUT = 20


def _num(txt) -> float:
    """'152,855,264' -> 152855264.0 ; '' / None / 'N/A' -> 0.0"""
    if txt is None:
        return 0.0
    s = str(txt).replace(",", "").replace("$", "").strip()
    if not s or s.upper() in ("N/A", "NA", "--"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _leer_cache() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_cache(c: dict) -> None:
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except OSError:
        pass


def _pedir(ticker: str):
    """Devuelve dict con el ultimo periodo, o None si el ticker no tiene dato."""
    pet = urllib.request.Request(URL.format(ticker), headers={"User-Agent": UA,
                                                             "Accept": "application/json"})
    with urllib.request.urlopen(pet, timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    filas = (((d.get("data") or {}).get("shortInterestTable") or {}).get("rows") or [])
    if not filas:
        if "not available" in str(d.get("message", "")).lower():
            raise ValueError("no_dato")
        return None
    # rows viene de mas reciente a mas antiguo
    ult = filas[0]
    interes = _num(ult.get("interest"))
    dias = _num(ult.get("daysToCover"))
    vol = _num(ult.get("avgDailyShareVolume"))
    previo = _num(filas[1].get("interest")) if len(filas) > 1 else 0.0
    cambio = ((interes - previo) / previo * 100.0) if previo else 0.0
    return {
        "fecha": (ult.get("settlementDate") or "").strip(),
        "interes": interes,
        "dias_cobertura": round(dias, 2),
        "volumen_medio": vol,
        "interes_previo": previo,
        "cambio_pct": round(cambio, 1),
    }


def cargar(tickers, hoy: str | None = None, forzar: bool = False) -> dict:
    """Devuelve {ticker: {fecha, interes, dias_cobertura, cambio_pct, ...}}.

    Cachea por ticker DIAS_CACHE dias. Los fallos no se cachean (un 404 de hoy puede
    existir manana), pero tampoco rompen: el ticker se queda fuera del resultado.
    """
    import datetime as dt
    hoy = hoy or dt.date.today().isoformat()
    cache = _leer_cache()
    salida, a_pedir = {}, []

    for t in {str(x).strip().upper() for x in tickers if x}:
        c = cache.get(t)
        if c and not forzar and c.get("datos") and c.get("visto") and (dt.date.fromisoformat(hoy)
                                                    - dt.date.fromisoformat(c["visto"])).days < DIAS_CACHE:
            if c.get("datos"):
                salida[t] = c["datos"]
            continue
        a_pedir.append(t)

    def trabajo(tk):
        import time
        for intento in range(3):
            time.sleep(0.35)
            try:
                r = _pedir(tk)
                if r:
                    return tk, r
            except ValueError:
                return tk, None          # NYSE u otro: no hay dato, no reintentar
            except Exception:
                pass
            time.sleep(1.0 * (intento + 1))
        return tk, None

    if a_pedir:
        with ThreadPoolExecutor(max_workers=MAX_HILOS) as ex:
            for tk, datos in ex.map(trabajo, a_pedir):
                cache[tk] = {"visto": hoy, "datos": datos}
                if datos:
                    salida[tk] = datos
        _guardar_cache(cache)

    return salida
