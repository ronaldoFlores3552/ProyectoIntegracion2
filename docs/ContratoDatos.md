# Contrato de datos: base relacional inicial

Este documento fija la entrada, el grano y la salida de la Parte I. Si la fuente OCDS cambia, este contrato se revisa antes de modificar los modelos.

## Fuente

- Publicador: OECE/OSCE.
- Estándar: OCDS, releases compilados en JSON Lines comprimido.
- Archivos de entrada: `data/raw/<año>.jsonl.gz`.
- Procedencia verificable: `data/raw/manifest.json` contiene URL, fecha, tamaño y SHA-256 de cada descarga.

## Grano de análisis

La tabla `fact_award_item` tiene una fila por:

> proceso (`process_ocid`) × adjudicación (`award_id`) × proveedor (`supplier_id`) × ítem adjudicado (`item_id`).

La identificación analítica de una adjudicación usa la clave compuesta
`process_ocid` + `award_id`. `award_id` por sí solo no se debe asumir globalmente
único entre procesos.

Una adjudicación sin ítem se conserva con valores nulos en las columnas de ítem; una fila sin proveedor no forma parte de la tabla analítica.

## Salida

- Formato: Parquet.
- Ruta: `data/processed/fact_award_item/`.
- Partición: `source_year`.
- Escritura por defecto: falla si la ruta ya existe. Use `--overwrite` solo para regenerar deliberadamente la tabla.

## Tabla derivada: `fact_award`

`fact_award` se deriva de `fact_award_item` y tiene una fila por:

> proceso (`process_ocid`) × adjudicación (`award_id`).

Se publica en `data/processed/fact_award/`, particionada por `source_year`, y
conserva los campos de trazabilidad, entidad, licitación y adjudicación. No
incluye proveedor ni ítem. Por ello `award_amount` aparece una sola vez por
adjudicación y puede agregarse únicamente dentro de una misma moneda.

Antes de publicarla, la transformación verifica que una misma clave compuesta
no tenga dos representaciones distintas de nivel adjudicación. Si ocurre, el
proceso se detiene y exige definir una regla de versión; nunca elige una fila de
forma arbitraria. `fact_award_item` sigue siendo la fuente para análisis a nivel
de proveedor o ítem.

## Tabla derivada: `fact_award_supplier`

`fact_award_supplier` se deriva de `fact_award` y de la relación de proveedores
en `fact_award_item`. Tiene una fila por:

> proceso (`process_ocid`) × adjudicación (`award_id`) × proveedor (`supplier_id`).

Se publica en `data/processed/fact_award_supplier/`, particionada por
`source_year`. Conserva trazabilidad, entidad, contexto de licitación, fecha y
proveedor, e incorpora `award_year` desde `award_date`.

Sus campos monetarios tienen propósitos distintos:

| Campo | Regla de uso |
|---|---|
| `award_amount_total` | Monto oficial de la adjudicación; puede repetirse cuando existan varios proveedores y no se suma por proveedor. |
| `award_amount_single_supplier` | Igual al monto total solo con `supplier_count_per_award = 1`; es nulo cuando haya varios proveedores. |
| `award_currency` | Dimensión obligatoria para cualquier suma de monto. |

La transformación rechaza claves de adjudicación repetidas, proveedores sin
adjudicación, adjudicaciones sin proveedor y nombres no vacíos incompatibles
para el mismo proveedor dentro de una adjudicación. No reparte montos entre
proveedores sin una regla de negocio documentada.

## Tablas de interacción anuales

`entity_supplier_year` se construye desde `fact_award_supplier` al grano
entidad × proveedor × año de adjudicación × moneda. `entity_category_year`
se construye desde `fact_award` al grano entidad × categoría × año de
adjudicación × moneda. Se publican en `data/processed/` y se particionan por
`award_year`, derivado de `award_date` en la zona America/Lima.

Ambas incluyen `award_count`, `amount_known_count`, `amount_sum` y
`latest_award_date`. El monto de proveedor usa exclusivamente
`award_amount_single_supplier`; el de categoría usa `award_amount`. Si faltan
moneda o monto, la fila contribuye al conteo, pero no a `amount_sum`. Una suma
sin ningún monto conocido es nula, no cero. `<MISSING>` representa una moneda
o categoría ausente; el proceso rechaza ese literal si ya aparece en la fuente.

Las filas sin fecha o entidad se excluyen de ambas tablas; las filas sin
proveedor también se excluyen de la tabla de proveedores. `_metadata.json` en
cada salida registra las exclusiones, cobertura de montos, recuentos y `run_id`.
Las razones pueden solaparse; `excluded_rows` es el total de filas excluidas,
no la suma de las razones. Las dos salidas comparten `run_id` cuando se generan
en una misma ejecución; la publicación es atómica por tabla, no para el par.

## Evidencia de identidad OCDS

`data/processed/identity_evidence/` contiene un conjunto publicado como una
unidad, con `_SUCCESS` y `_metadata.json`. La entrada es la fuente JSONL.GZ
verificada frente al manifiesto y `fact_award_supplier` para los años elegidos.
La referencia se identifica por año de archivo, proceso, release, rol y ID;
el cruce exige coincidencia exacta de año, proceso, release y `party.id`.

| Salida Parquet | Grano y propósito |
|---|---|
| `party_identifiers` | Identificador principal o adicional de una `party`, con posición, nombre, roles, esquema y valor originales. Incluye también valores incompletos. |
| `reference_matches` | Una fila por referencia distinta; indica si coincide con cero, una o varias filas de `parties` en ese contexto. |
| `reference_identifiers` | Evidencia de identificador vinculada a la referencia en el mismo contexto. |
| `candidate_shared_identifiers` | Por rol, esquema y valor exactos: grupos asociados a más de un ID de referencia. |
| `candidate_identifier_variants` | Por rol, ID de referencia y esquema: grupos con más de un valor de identificador. |

Los grupos candidatos excluyen esquema o valor vacío y no normalizan ni
fusionan identificadores. Sus coincidencias o contradicciones requieren
revisión; las filas repetidas pueden reflejar distintas posiciones o releases.
Los metadatos guardan los SHA-256 de las fuentes y la cobertura por rol. La
verificación del manifiesto acredita los archivos actuales, pero no prueba por
sí sola que la tabla `fact_award_supplier` se generó con esa misma versión.

## Representaciones de la Parte I

`data/processed/part1/` publica como unidad vectores, coordenadas dispersas,
diccionarios y grafo KNN, con `_SUCCESS` y `_metadata.json`. Las entradas son
las dos interacciones anuales publicadas con el mismo `run_id`; se registran
huellas SHA-256 de sus contenidos actuales. Estas huellas no prueban el origen
histórico de las interacciones ni de las tablas que las preceden.

| Tabla | Grano y regla |
|---|---|
| `entity_features` | Una entidad en la ventana: conteo, logaritmo y proporciones por categoría; vectores original y estandarizado. El orden de categorías y el ajuste están en metadatos. |
| `matrix` | Una entidad × proveedor: `interaction_count` es un conteo de adjudicaciones, suma de conteos entre años y monedas, no una suma de dinero. Incluye los índices de ambos diccionarios. |
| `entity_dictionary`, `supplier_dictionary` | Un ID original y su índice entero base cero. Índices determinados por 256 buckets de hash Spark y orden dentro del bucket; usarlos solo con la matriz de la misma publicación. |
| `graph_nodes` | Una entidad elegible, incluso si no tiene vecinos. |
| `graph_edges` | Arista dirigida `src` → `dst` con distancia euclidiana estandarizada y posición entre vecinos. No hay autoaristas; empates se ordenan por ID. |

La ventana usa `award_year`, no el año del archivo. El escalado de esta versión
se ajusta sobre la ventana descriptiva completa: para una evaluación temporal
futura debe reajustarse solo con entrenamiento. La publicación conserva ID
originales y no afirma que no existan duplicados. El KNN exacto es cuadrático y
se detiene antes de exceder `--max-pairs`.

## Clustering descriptivo de entidades

`artifacts/clustering/` es regenerable y contiene una publicación completa cuando existe `_SUCCESS`. Se deriva de `data/processed/part1/entity_features` para la ventana 2023–2024; `_metadata.json` registra las huellas de las entradas, versiones, escala, criterios y selecciones. Una ejecución nueva se publica por staging y exige `--overwrite` cuando ya existe una salida.

| Archivo | Grano y significado |
|---|---|
| `features.parquet` | Una fila por `entity_id`; conteo de adjudicaciones, `log1p` y tres proporciones de categorías. |
| `assignments.parquet` | Una entidad × método × variante de escalado × configuración. `selected` marca las configuraciones elegidas provisionalmente; `label=-1` representa ruido de HDBSCAN. `distance` corresponde a KMeans y `probability` a HDBSCAN. `outlier_candidate` solo se marca en la configuración seleccionada, según las reglas del reporte. |
| `kmeans_metrics.parquet`, `hdbscan_metrics.parquet` | Una fila por variante y configuración; la silueta de HDBSCAN excluye el ruido. |
| `profiles.parquet` | Un método seleccionado × etiqueta, incluido el ruido cuando existe; incluye tamaño y medianas descriptivas. |

Las etiquetas son arbitrarias y las señales de distancia o ruido no prueban irregularidades. La selección HDBSCAN es sensible al entorno y a la abundancia de vectores idénticos; no constituye una clasificación definitiva.

## Cortes retrospectivos de recomendación

`data/processed/recommendation/` se publica como unidad con `_SUCCESS` y `_metadata.json`, a partir de `fact_award_supplier`. Se valida la clave adjudicación-proveedor y la coherencia entre fecha y año en America/Lima; se registran exclusiones y la huella de la entrada. Los cortes 2023 y 2024 usan, respectivamente, adjudicaciones anteriores al inicio de ese año para entrenamiento y adjudicaciones del año para etiquetas. La fuente actual no demuestra disponibilidad histórica.

Cada carpeta de corte contiene:

| Tabla | Grano y significado |
|---|---|
| `train` | Una entidad × proveedor presente antes del corte; `interaction_count`, `strength=log1p(interaction_count)` e índices de los diccionarios de ese corte. |
| `entities`, `suppliers` | Un ID original conocido en entrenamiento y su índice entero estable para esa publicación. Los índices no se comparten entre cortes. |
| `future_pairs` | Un par distinto observado en el año de evaluación, con indicadores `seen`, `entity_known`, `supplier_known` y `eligible_positive`. Un positivo elegible es nuevo y tiene ambos actores conocidos. |

El catálogo candidato es el conjunto de proveedores de entrenamiento, excluyendo por entidad los proveedores de su `train`. No se publica una matriz densa de candidatos. El entrenamiento de 2023 se usa para selección; el de 2024 se usa para reentrenamiento y prueba final. Filtrar por fecha no prueba qué información estaba disponible entonces.

Los artefactos regenerables `artifacts/recommendation_baseline`, `recommendation_neighbors`, `recommendation_als` y `recommendation_test` contienen `_SUCCESS`, `_metadata.json`, rankings por entidad y métricas por entidad a 10 y 20. La selección ALS registra ambas configuraciones de validación y la elegida; la prueba final registra la configuración y métricas de los tres métodos. No se serializan modelos. Todos los resultados se refieren a adjudicaciones observadas, no a preferencias ni a elegibilidad legal.

`artifacts/recommendation_content/` contiene un experimento TF-IDF exploratorio para validación 2023. Se obtienen descripciones de `fact_award_item` mediante el cruce por proceso, adjudicación y proveedor con eventos elegibles anteriores al corte. Se verifica que los conteos de los eventos concilien con la matriz de entrenamiento. Los perfiles de entidad y proveedor se construyen únicamente con esos ítems y se comparan por coseno; los rankings excluyen relaciones previas. Los metadatos registran parámetros, huellas de cortes y entradas, cobertura y métricas. La ventana de prueba 2024 ya fue observada antes de formular este experimento y no constituye una prueba final independiente para él. Las huellas acreditan las entradas actuales, no las versiones históricas disponibles al corte.

## Campos principales

| Grupo | Campos |
|---|---|
| Trazabilidad | `source_year`, `process_ocid`, `release_id`, `release_date`, `published_date` |
| Entidad | `entity_id`, `entity_name`, `procuring_entity_id`, `procuring_entity_name` |
| Licitación | `tender_id`, `tender_title`, `procurement_category`, `procurement_method`, `number_of_tenderers` |
| Adjudicación | `award_id`, `award_date`, `award_amount`, `award_currency` |
| Proveedor | `supplier_id`, `supplier_name` |
| Ítem | `item_id`, `item_description`, `item_classification_id`, `item_amount`, `item_quantity`, `item_unit_name` |

## Decisiones iniciales

- Se conserva el monto de adjudicación y el monto de ítem por separado. No se asume que los ítems sumen exactamente el total de la adjudicación.
- La resolución de proveedores duplicados aún no se aplica aquí: primero se conserva el identificador publicado y se realizará en un módulo dedicado, dejando trazabilidad entre identificador original y canónico.
- Los postores de `tender.tenderers` no se incorporan a esta tabla. Se utilizarán después para construir un grafo de co-participación separado.

