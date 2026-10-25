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

