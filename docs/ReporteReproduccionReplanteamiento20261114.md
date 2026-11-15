# Reproducción del replanteamiento P1/P2

**Fecha:** 14 de noviembre de 2026
**Estado:** medición exploratoria reproducida; no valida aún competencia efectiva ni implementa las nuevas tablas Spark.

## Propósito

Este reporte registra la primera ejecución local del PR #2. Su finalidad es
comprobar que los conteos y el piloto descritos en
`ReplanteamientoPreguntas.md` se obtienen desde los mismos raw, antes de
cambiar el modelo de datos o los notebooks analíticos.

## Entrada y entorno

| Elemento | Valor |
|---|---|
| Commit que incorporó el PR localmente | `f5595f6` (origen lógico: `8ef6a14`) |
| Python | 3.12.10 (`.venv312`) |
| Raw 2023 SHA-256 | `34a8cd64afee7b8d1cde3f44e30f9101bbd2537add96ccf6db79cca9bafab65a` |
| Raw 2024 SHA-256 | `9f50c84423c65605b4280d2d88b9da0853ebeb0b556d2dedf66add435cbde6e0` |
| Manifiesto SHA-256 | `726fd91d6a6c7070d1496c1557fb85917ccea58ec95bb362d82fc9dc840e0e92` |
| Salidas locales regenerables | `artifacts/replanteamiento/2026-11-14_pr2_reproduccion/` |

Los comandos ejecutados fueron:

```powershell
.\.venv312\Scripts\python.exe scripts\exploracion\medir_participantes.py data\raw\2023.jsonl.gz data\raw\2024.jsonl.gz
.\.venv312\Scripts\python.exe scripts\exploracion\medir_participantes_extra.py data\raw\2023.jsonl.gz data\raw\2024.jsonl.gz
.\.venv312\Scripts\python.exe scripts\exploracion\piloto_p1.py data\raw\2023.jsonl.gz data\raw\2024.jsonl.gz
```

En Windows, los tres scripts ahora abren explícitamente los JSONL.GZ como
UTF-8. Antes usaban la codificación predeterminada `cp1252` y fallaban al leer
el raw; la corrección no altera sus filtros, cálculos ni resultados.

## Resultados reproducidos

| Medida | Resultado |
|---|---:|
| Procesos con adjudicación en 2023–2024 | 76 651 |
| Adjudicaciones | 83 648 |
| Compradores | 2 756 |
| Proveedores adjudicados | 39 819 |
| Compradores con departamento | 100,0 % (25 departamentos) |
| Procesos con lista de participantes reportados | 99,6 % |
| Participantes reportados distintos | 114 147 |
| Participantes en 5 o más procesos | 26 055 |
| Participantes que nunca ganaron en la ventana | 65,1 % |
| Pares expandidos de co-participación | 13 012 421 |
| Pares al limitar a 30 participantes por proceso | 7 145 680 |

El piloto P1 produjo 1 091 unidades comprador×segmento con al menos 10
procesos y cinco procesos competitivos con participantes; la correlación de
Spearman entre cuota del proveedor principal y mediana de participantes fue
**−0,262**. Con 20 procesos, hubo 392 unidades y la correlación fue **−0,140**.
Esto muestra una señal exploratoria y sensibilidad al umbral; no es una
estimación causal ni una confirmación independiente.

## Decisiones resultantes

1. P1 y P2 son factibles con los raw actuales; se mantienen como preguntas
   principales.
2. `tenderers` se llama **participantes reportados**. Aunque tiene cobertura
   alta, coincide con `numberOfTenderers` en 98,0 % de procesos con ambos
   campos y casi siempre contiene al ganador, sus extremos y discrepancias
   impiden tratarlo sin más como oferta efectiva.
3. La co-participación debe procesarse en Spark y filtrarse/normalizarse antes
   de proyectarla. Los 13 millones de pares son expansiones, no aristas únicas.
4. El KNN previo no se usa para P2: continúa siendo una red de similitud de
   perfiles, no una red de participantes.

## Puerta pendiente: validación OECE

Para cerrar la semántica se necesita una muestra estratificada por modalidad,
departamento y tamaño de lista. Para cada proceso seleccionado se registrará:

- identificador del proceso y participantes publicados en OCDS;
- resultado del cruce con el Listado de ofertantes de OECE, versión y fecha de
  descarga;
- clave de unión, coincidencias, no coincidencias y casos ambiguos;
- comparación con `numberOfTenderers` y evidencia de ganadores en la lista.

La puerta queda cerrada sólo si el cruce reporta cobertura y discrepancias por
estrato. Si la fuente externa no permite validarlo, las fases siguientes siguen
siendo posibles, pero P1 se reportará estrictamente como asociación entre
concentración y participación **reportada**, no como competencia efectiva.

## Próxima implementación autorizada por el diseño

Escribir pruebas y transformación Spark para `fact_tender`,
`fact_tenderer` y `dim_buyer`, con los granos definidos en `ContratoDatos.md`.
No se actualizarán clustering, centralidades, comunidades o la web hasta
conciliar esas nuevas salidas contra estos totales.
