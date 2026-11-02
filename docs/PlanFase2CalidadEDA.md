# Diseño técnico: Fase 2 — calidad y EDA de fact_award_item

**Fecha:** 2026-10-24  
**Estado:** perfil técnico publicado; interpretación y EDA en notebook.

## Objetivo

Medir la calidad, cobertura y estructura de fact_award_item antes de construir features, matrices, grafos o modelos. Esta fase observa y documenta; no elimina filas ni altera la tabla publicada.

## Entrada y salida

| Elemento | Ruta | Regla |
|---|---|---|
| Entrada | data/processed/fact_award_item | Debe contener _SUCCESS. |
| Perfil publicado | artifacts/quality/fact_award_item | Se publica de forma atómica. |
| Metadatos | profile.json | Métricas globales, esquema e interpretación. |
| Resumen temporal | by_source_year/ | Métricas sin sumas de montos. |
| Categorías | category_counts/ | Monedas, categorías y modalidades. |
| Repeticiones | candidate_key_duplicates/ | Grupos repetidos para revisión; no se borran. |

## Métricas iniciales

- Filas, procesos, adjudicaciones, adjudicación–proveedor, proveedores y entidades distintas.
- Nulos o blancos en identificadores, fecha, monto, moneda e identificador de ítem.
- Rango de fechas de adjudicación.
- Conteo de montos positivos, cero, negativos o nulos.
- Repeticiones exactas y repeticiones de la llave candidata proceso, adjudicación, proveedor e ítem.
- Cobertura por source_year y distribución de moneda, categoría y modalidad.
- Cobertura de buyer y procuring_entity, más sus discrepancias de identificador.

## Regla financiera crítica

award_amount pertenece a una adjudicación y puede repetirse por cada ítem de
fact_award_item. Por eso el perfil no suma award_amount. La tabla
`data/processed/fact_award/` ya publica una fila por adjudicación y es la única
base actual para métricas monetarias. Aun allí, los montos solo se pueden sumar
o comparar dentro de una misma moneda; no existe todavía una conversión oficial.

## Ruta de trabajo

El comando siguiente genera el control técnico, pequeño y reproducible. No se usa para escribir conclusiones ni gráficos:

~~~powershell
python -m src.quality.profile_fact_award_item --overwrite
~~~

La exploración, gráficos, hipótesis y conclusiones se mantienen en notebooks/01_calidad_y_eda.ipynb. El notebook solo lee Parquet y JSON ya publicados; no reemplaza ni modifica las tablas oficiales.

## Criterio de cierre

La fase queda lista para representaciones solo cuando exista un perfil publicado, los campos clave tengan diagnóstico, se conozca la cobertura temporal y se documente qué grano puede usarse para conteos y montos.

## Decisiones que este perfil debe informar

1. Identificador y nombre de entidad a usar: buyer o procuring_entity.
2. Llave confiable para adjudicación y adjudicación–proveedor.
3. Fecha analítica para divisiones temporales.
4. Tratamiento de monedas y montos no válidos.
5. Regla para crear matrices entidad–proveedor y los pesos del grafo.

## Primera ejecución sobre 2023–2024

La primera corrida publicó correctamente el perfil. Hallazgos que ya orientan
las siguientes tareas:

- 137 292 filas y 128 395 adjudicaciones con la clave compuesta proceso + adjudicación.
- No hay repeticiones exactas ni de la llave candidata actual.
- source_year es el año del archivo, no el año de adjudicación: award_date va de
  2015-03-19 a 2024-12-26 y tiene 35 valores nulos.
- Los montos son todos positivos y no nulos, pero hay PEN, USD, EUR, GBP, CAD,
  JPY y un valor de moneda ausente. No se deben comparar ni sumar montos entre
  monedas sin una regla de conversión documentada.
- Hay 18 752 filas sin clasificación de ítem. Se preservan como faltantes y se
  evaluará su tratamiento por técnica, sin eliminarlas todavía.
- buyer y procuring_entity no tienen identificadores ausentes ni discrepancias
  entre sí en esta corrida. entity_id seguirá como identificador principal y
  procuring_entity se conservará para control de calidad.
- Se publicó `fact_award` con 128 395 filas y cero claves compuestas repetidas.
  Conserva el monto una sola vez por adjudicación. Su distribución monetaria es
  PEN: 125 513; USD: 2 498; EUR: 337; GBP: 44; JPY: 1; CAD: 1; sin moneda: 1.

