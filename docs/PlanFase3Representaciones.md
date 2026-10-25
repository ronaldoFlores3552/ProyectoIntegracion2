# Diseño técnico: Fase 3 — representaciones analíticas

**Fecha:** 2026-10-24  
**Estado:** entrega 3.1 implementada y validada; interacciones altas pendientes.

## Objetivo

Convertir las tablas OCDS publicadas en representaciones pequeñas, auditables y
reutilizables para concentración, clustering, recomendación y grafos. Esta fase
no entrena modelos ni interpreta patrones: solo fija los objetos de entrada y
sus reglas de construcción.

## Punto de partida y condición de avance

| Insumo | Ruta | Uso |
|---|---|---|
| Detalle por ítem | `data/processed/fact_award_item/` | Clasificaciones e inspección por ítem. |
| Adjudicación | `data/processed/fact_award/` | Fecha, entidad, categoría y monto no repetido. |
| Perfil de calidad | `artifacts/quality/fact_award_item/` | Diagnóstico de nulos, duplicados y cobertura. |
| EDA | `notebooks/01_calidad_y_eda.ipynb` | Observaciones y decisiones narradas. |

Antes de publicar una representación se debe registrar en el notebook la
decisión sobre las 35 fechas de adjudicación ausentes. Para las primeras tablas
temporales se excluirán del corte por año, se contará la exclusión y no se
imputará ninguna fecha.

## Principios no negociables

1. La clave de adjudicación es `process_ocid` + `award_id`.
2. `award_amount` se agrega solo desde `fact_award`, nunca desde
   `fact_award_item`.
3. `award_currency` siempre acompaña una suma de monto; no habrá sumas entre
   PEN, USD, EUR u otras monedas.
4. Las categorías nulas se conservan como `<MISSING>` en agregados; no se
   eliminan filas por ese motivo.
5. Una salida se publica de forma atómica y solo es válida con `_SUCCESS`.
6. Ningún notebook escribe tablas oficiales. Los notebooks leen Parquet y
   documentan experimentos; las transformaciones oficiales viven en `src/` y
   tienen pruebas.

## Entregas, en orden

### 3.1 `fact_award_supplier`

**Grano:** proceso × adjudicación × proveedor.

**Ruta:** `data/processed/fact_award_supplier/`, particionada por `source_year`.

| Grupo | Campos mínimos |
|---|---|
| Clave y trazabilidad | `source_year`, `process_ocid`, `award_id`, `release_id` |
| Entidad y tiempo | `entity_id`, `award_date`, `award_year` |
| Proveedor | `supplier_id`, `supplier_name`, `supplier_count_per_award` |
| Contexto | `procurement_category`, `procurement_method` |
| Monto | `award_amount_total`, `award_currency`, `award_amount_single_supplier` |

`award_amount_total` conserva el valor oficial de la adjudicación, pero no se
suma por proveedor. `award_amount_single_supplier` solo toma ese valor cuando
`supplier_count_per_award = 1`; si hay varios proveedores se publica nulo. No
se reparte el monto entre proveedores sin una regla de negocio explícita.

**Validaciones:** clave única, todas las claves provienen de `fact_award`,
`supplier_count_per_award >= 1`, conservación de moneda y reporte de claves sin
proveedor. En la corrida actual se espera un proveedor por adjudicación, pero la
tabla no debe depender de esa coincidencia futura.

**Primera ejecución 2023–2024:** publicada con 128 395 filas, 128 395
adjudicaciones, cero claves repetidas y un proveedor por adjudicación en todos
los casos. Por eso `award_amount_single_supplier` coincide con
`award_amount_total` en esta corrida. Esta coincidencia es un resultado
observado, no una condición asumida por la transformación.

### 3.2 Interacciones altas, no matrices todavía

Estas tablas son la fuente canónica de las futuras matrices y grafos. Se
almacenan altas en Parquet porque son inspeccionables, no fuerzan memoria y se
pueden filtrar por fecha o moneda.

| Tabla | Grano | Ruta | Métricas permitidas |
|---|---|---|---|
| `entity_supplier_year` | entidad × proveedor × `award_year` × moneda | `data/processed/entity_supplier_year/` | número de adjudicaciones; suma de `award_amount_single_supplier` por moneda; recencia máxima. |
| `entity_category_year` | entidad × categoría × `award_year` × moneda | `data/processed/entity_category_year/` | número de adjudicaciones; suma de `award_amount` por moneda; recencia máxima. |

`award_year` deriva de `award_date`, no de `source_year`. Las adjudicaciones sin
fecha se excluyen de estas dos tablas y su cantidad queda registrada en los
metadatos de corrida.

### 3.3 Matrices y aristas bajo demanda

Cuando una pregunta de investigación lo requiera, un único módulo de features
leerá las tablas altas y construirá una representación específica:

| Consumidor | Entrada | Representación mínima | Baseline posterior |
|---|---|---|---|
| Recomendación | `entity_supplier_year` | matriz dispersa entidad × proveedor con conteo de adjudicaciones | proveedor más frecuente/global y por entidad. |
| Tipologías | `entity_category_year` | vector entidad × categoría con conteos o proporciones | segmentación por variables descriptivas simples. |
| Red contractual | `entity_supplier_year` | arista bipartita entidad–proveedor ponderada por conteo | grado ponderado y no ponderado. |

No se guardarán matrices densas, grafos serializados ni embeddings durante esta
fase. Esos objetos dependen de filtro temporal, ponderación, normalización y
semilla; deben ser artefactos de un experimento documentado, no una fuente de
verdad general.

## Diseño mínimo de código

Solo se crearán módulos necesarios para publicar salidas oficiales:

1. `src/processing/build_fact_award_supplier.py` para la tabla relacional.
2. `src/features/build_interactions.py` para las dos agregaciones altas.

Cada módulo tendrá `--overwrite`, rutas de entrada y salida explícitas,
validación de `_SUCCESS`, publicación atómica, una prueba proporcional y una
entrada en la guía de réplica. No se crearán scripts de exportación a TXT ni
scripts de análisis ad hoc.

## Criterios de cierre de Fase 3

- Las tres tablas existen con `_SUCCESS` y contratos documentados.
- Las claves, conteos y cobertura temporal se reconcilian con sus fuentes.
- Las sumas monetarias conservan la moneda como dimensión.
- Las exclusiones por fecha y los `<MISSING>` se cuantifican, no se ocultan.
- El notebook describe qué representación alimentará cada técnica y qué
  baseline la acompañará.
- Las pruebas, Ruff y al menos una ejecución local reproducible pasan.

## Fuera de alcance

Esta fase no crea clustering, recomendadores entrenados, comunidades, PageRank,
embeddings, API ni frontend. Esos componentes comienzan solo cuando las
representaciones anteriores estén validadas.
