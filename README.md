# Monitor de insiders y Congreso

Monitor automatico de movimientos de **insiders corporativos** (SEC Form 4) y de
**congresistas de EEUU** (declaraciones de la Camara), con deteccion de movimientos anomalos.

## Que hace

- **Insiders**: descarga los Form 4 de los ultimos dias desde **SEC EDGAR** (fuente oficial, gratis)
  y detecta anomalias: clusters de varios insiders comprando, compras grandes, compras de CEO/CFO
  y **compras a contracorriente** (directivo comprando con la accion hundida).
- **Congreso**: descarga el indice oficial de divulgaciones de la Camara de Representantes
  (`disclosures-clerk.house.gov`) y parsea los PTR en PDF con `pdftotext`.
- **Precios**: contexto de mercado de cada valor via la API publica de Yahoo Finance.
- **Dashboard**: `index.html` con los datos embebidos (funciona abierto en local, sin servidor).

## Ficheros

| Fichero | Que es |
|---|---|
| `fetch_insiders.py` | descarga y parsea los Form 4 de la SEC + detector de anomalias |
| `congreso.py` | indice oficial de la Camara + parseo de los PTR en PDF |
| `precios.py` | contexto de precio (Yahoo Finance) |
| `run_all.py` | pipeline completo (insiders + congreso + dashboard) |
| `build_dashboard.py` | genera `index.html` con los datos dentro |
| `data.json` | salida con todos los datos del dia |

## Uso

```bash
py -3 run_all.py              # pipeline completo
py -3 run_all.py --sin-sec    # solo congreso + dashboard (reutiliza data.json)
```

## Aviso

Son datos publicos **con retraso** (Form 4: 1-2 dias; PTR del Congreso: hasta 45). Sirven para
informarse, **no para copiar**: la evidencia muestra que copiar estos movimientos rinde por debajo
del indice de referencia.
