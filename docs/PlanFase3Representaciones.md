# Diseño técnico: Fase 3 — representaciones analíticas

**Fecha:** 2026-10-25

**Estado:** documento de diseño histórico; los artefactos base están publicados localmente. La identidad canónica sigue pendiente. Para resultados vigentes consulte [README_ParteI.md](README_ParteI.md).

Para la propuesta completa de cierre de la Parte I, incluidos vectores, matriz,
grafo KNN y estudio de particionamiento, véase
[ReporteYPlanCierreParte1.md](ReporteYPlanCierreParte1.md). Dicho plan detalla
entregables futuros; no significa que ya se hayan construido.

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
fecha o entidad se excluyen y su cantidad queda registrada en los metadatos de
cada salida. También se excluyen proveedores sin identificador en la tabla de
proveedor. Las razones pueden solaparse. Una moneda ausente se conserva como
`<MISSING>` para conteos, pero no se suma su monto: no sabemos su unidad. Cada
agregado informa `award_count`, `amount_known_count`, `amount_sum` y la fecha
más reciente; un monto sin valores conocidos es nulo, no cero. Las salidas se
publican individualmente y su `_metadata.json` comparte un `run_id` de corrida.

**Corrida local 2023–2024:** cada fuente contiene 128 395 filas; se excluyeron
35 sin fecha y se conservaron 128 360. La tabla de proveedor contiene 108 924
grupos y la de categoría 21 744. No se encontraron claves de grupo duplicadas;
los conteos y montos por moneda concilian con las fuentes elegibles. Estas
cifras son una referencia de los datos usados, no una garantía para otras
descargas.

### Diagnóstico de identidad antes de construir matrices y grafos

El notebook `notebooks/02_diagnostico_resolucion_entidades.ipynb` examina pares
distintos identificador–nombre de `fact_award_supplier`. La normalización de
nombre aplica Unicode NFKC, minúsculas y espacios; no elimina acentos ni
abreviaturas. Para la corrida 2023–2024, cuyos archivos tienen SHA-256
`34a8cd64afee7b8d1cde3f44e30f9101bbd2537add96ccf6db79cca9bafab65a` y
`9f50c84423c65605b4280d2d88b9da0853ebeb0b556d2dedf66add435cbde6e0`,
respectivamente, se observaron:

| Rol | ID distintos | Nombres con varios ID | ID con varios nombres |
|---|---:|---:|---:|
| Proveedor | 62 919 | 2 858 | 338 |
| Comprador | 2 967 | 2 | 0 |

Son grupos candidatos, no entidades duplicadas confirmadas ni una estimación
de la tasa de duplicación. Los nueve pares de proveedor sin nombre y las
variaciones de nombre también requieren revisión. Los datos y tablas existentes
siguen usando los identificadores originales.

Una inspección de un release con `parties` por archivo encontró los campos
`identifier` y `additionalIdentifiers`, con `scheme`, `id` y `legalName` en
la muestra. La extracción `build_identity_evidence` procesa los archivos
completos con Spark y conserva proceso, release, posición, rol y tipo de
identificador. La evidencia y los grupos candidatos se publican bajo
`data/processed/identity_evidence/`; su contrato está en `ContratoDatos.md`.
Los resultados requieren revisión antes de definir un mapeo canónico. La
igualdad de nombres, por sí sola, no autoriza fusionar dos identificadores.

**Ejecución local de referencia, 2023–2024:** se extrajeron 1 785 490 filas
de identificadores de `parties` y 367 832 filas de evidencia vinculadas a
referencias de compradores y proveedores. El cruce usa año de fuente, proceso,
release e identificador de referencia; por ello sus cantidades cuentan
referencias distintas en ese contexto, no adjudicaciones ni entidades únicas.
De 128 340 referencias de proveedor, 128 308 coinciden con una sola `party` y
32 no coinciden. Las 119 762 referencias de comprador coinciden con una sola
`party`. Todas las referencias coincidentes tienen al menos un identificador
con esquema y valor completos.

No se encontraron grupos candidatos de identificador compartido ni variantes
para un mismo identificador de referencia **dentro de un mismo esquema y con
valores exactos**. Esto no descarta duplicados: no compara identificadores de
esquemas distintos, no resuelve las 32 referencias sin coincidencia y no
invalida los 2 858 grupos de nombres de proveedor pendientes de revisión.
Los hashes de los archivos originales se verifican contra el manifiesto; la
procedencia histórica de la tabla `fact_award_supplier` no se verifica por hash.
La siguiente tarea es investigar esas referencias y revisar muestras de los
grupos por nombre en el notebook antes de plantear una regla de identidad.

**Revisión exploratoria de referencia:** el notebook contrastó los 32 casos de
proveedor sin cruce con los JSONL.GZ de los hashes anteriores. Localizó todos
en `awards.suppliers` y sus 29 contextos de release; había 15 referencias en
2023 y 17 en 2024. En esos releases existían `parties`, pero ninguna tenía
un `party.id` igual al proveedor referido. De las 32 referencias, 23 tenían
nombre en `awards.suppliers`; ninguna de esas tenía un nombre exactamente
igual en `parties`. Estos resultados no demuestran por qué falta el vínculo ni
permiten asignarlo a otra organización.

Se revisó también una muestra intencional de los diez nombres normalizados con
más identificadores, con desempate alfabético: los diez empiezan por
«consorcio». Agrupan 723 ID distintos, todos con evidencia vinculada de
esquema `PE-RUC` en esta ejecución. Un ejemplo es «consorcio santa rosa», con
133 ID. La muestra no es representativa, no demuestra que sean organizaciones
distintas ni iguales y el nombre del esquema no valida el valor como RUC.
No se propone ninguna fusión por nombre. Para avanzar se debe establecer una
pregunta de análisis, un criterio trazable y, si corresponde, fuentes que
permitan verificar equivalencias; en ausencia de evidencia, conservar los ID
originales y declarar la limitación en las representaciones.

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
3. `src/processing/build_identity_evidence.py` para extraer y medir evidencia
   OCDS sin modificar las identidades originales.

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
