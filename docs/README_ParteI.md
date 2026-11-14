# Parte I — Transformación, matrices y grafos con Spark

**Actualización:** 25 de octubre de 2026, hora de Lima.  
**Propósito:** explicar qué está construido, cómo reproducirlo y qué límites debe conocer quien continúe el proyecto o lo evalúe. Los datos de salida se regeneran y no se versionan en Git.

## Alcance y preguntas

El objetivo de la [Parte I del enunciado](Proyecto2Integrador.md) es transformar las contrataciones OCDS con Spark, abordar la identidad de compradores y proveedores, y exportar vectores, una matriz de interacción y un grafo, justificando el particionamiento. Las preguntas que guían esta base son: cómo varían los perfiles de compra entre entidades; cómo se distribuyen sus relaciones observadas con proveedores; y cómo pueden afectar los identificadores no resueltos al análisis. Una relación o similitud no demuestra irregularidad ni causalidad.

La fuente es [OCDS – OECE/OSCE](https://data.open-contracting.org/es/publication/135), datos abiertos CC BY 4.0. Esta corrida usa los archivos de **año de fuente** 2023 y 2024 con SHA-256 `34a8cd64afee7b8d1cde3f44e30f9101bbd2537add96ccf6db79cca9bafab65a` y `9f50c84423c65605b4280d2d88b9da0853ebeb0b556d2dedf66add435cbde6e0`. El año de fuente no es el año de adjudicación y estos archivos no se deben interpretar como censo completo del período.

## Flujo y arquitectura

```text
JSONL.GZ + manifest.json
    → fact_award_item → fact_award → fact_award_supplier
    → entity_category_year / entity_supplier_year
    → part1: vectores + matriz dispersa + nodos/aristas KNN
JSONL.GZ + fact_award_supplier → identity_evidence → diagnóstico de identidad
```

Las transformaciones oficiales están en `src/` y usan PySpark 3.5.6. Los notebooks leen o estudian resultados; no publican las tablas oficiales. [ContratoDatos.md](ContratoDatos.md) especifica granos y campos. La [guía de réplica](ComandosEjecutarOrdenReplica.md) contiene las rutas lineales para Docker, Windows y Linux/macOS. El [registro estratégico](README_Estrategico.md) conserva el historial y [ReporteYPlanCierreParte1.md](ReporteYPlanCierreParte1.md) es el plan anterior: sus apartados de pendientes describen el estado en que fue escrito y deben contrastarse con este README.

## Datos y calidad observados

La corrida de referencia generó 137 292 filas de detalle, 119 762 procesos, 128 395 adjudicaciones, 62 919 ID de proveedor y 2 967 ID de entidad en el universo completo. Se encontraron 35 fechas de adjudicación ausentes y 18 752 filas de ítem sin clasificación. `fact_award` evita repetir el monto por ítem. Los montos solo se comparan o suman dentro de una misma moneda; no se hace conversión en esta parte.

Las interacciones anuales conservan año y moneda y excluyen las 35 filas sin fecha: 128 360 registros elegibles en cada tabla de proveedor y categoría. La matriz y los vectores de esta entrega filtran explícitamente **`award_year` 2023–2024**, resultando en **81 724 adjudicaciones elegibles** en cada fuente; las otras 46 636 elegibles tienen fechas fuera de esa ventana. La suma de conteos entre monedas es válida; no se suman sus montos.

## Identidad: política y evidencia

Se preservan los ID originales, sin fusiones por nombre. El diagnóstico encontró 2 858 nombres normalizados de proveedor con varios ID y 338 ID con varios nombres; para compradores, dos nombres con varios ID. Son candidatos, no duplicados confirmados. En 128 340 referencias contextuales de proveedor, 32 no tenían una `party` con el mismo ID; se localizaron en adjudicaciones, pero no pudo identificarse una equivalencia. Una muestra intencional de los diez nombres de proveedor con más ID reunió 723 ID y nombres de consorcios. La cobertura y el detalle están en [notebook 02](../notebooks/02_diagnostico_resolucion_entidades.ipynb).

**Conclusión:** la identidad se aborda mediante diagnóstico, evidencia y una política conservadora; no se ha demostrado una deduplicación completa ni existe mapeo canónico validado. En resultados de modelos y grafos deberá explicarse el posible efecto de fragmentación. Un `PE-RUC` publicado no valida por sí solo su identificador ni autoriza fusionar registros.

## Resultados de las representaciones

Las cifras siguientes corresponden a la publicación local con la ventana de adjudicación 2023–2024 y `k=5`; pueden variar si cambian los datos o el período.

| Artefacto en `data/processed/part1/` | Resultado | Definición |
|---|---:|---|
| `entity_features` | 2 756 vectores | `log1p` del número de adjudicaciones y proporciones de `goods`, `services`, `works`; cuatro dimensiones. |
| `matrix` | 61 939 pares | 2 756 entidades × 39 819 proveedores; suma de 81 724 adjudicaciones; densidad aproximada 0,0564 %. |
| `entity_dictionary`, `supplier_dictionary` | 2 756 / 39 819 ID | Índices de base cero determinados por bucket hash y orden en el bucket. Son válidos con la misma publicación. |
| `graph_nodes` | 2 756 nodos | Entidades del universo de vectores. |
| `graph_edges` | 13 780 aristas | Grafo dirigido, cinco vecinos por entidad, distancia euclidiana sobre las cuatro dimensiones estandarizadas. |

El KNN consideró 7 592 780 pares dirigidos posibles. No incluye autoaristas; los empates se ordenan por ID de destino. El límite predeterminado es 10 000 000 de pares, por encima del cual la ejecución se detiene antes de calcular distancias. Su costo es cuadrático; para un universo mayor se necesita implementar y evaluar una aproximación distribuida, no aumentar el límite sin medir recursos.

El vector escalado se ajusta con **toda la ventana descriptiva 2023–2024**. No debe reutilizarse para una evaluación temporal de modelos: hay que ajustar parámetros y diccionario solo con entrenamiento. Además, un corte por fecha de adjudicación no demuestra que la información estuviera disponible en aquella fecha; algunos releases observados son posteriores. Sin versiones históricas verificables, cualquier evaluación temporal debe describirse como retrospectiva.

La matriz describe adjudicaciones observadas, no preferencias ni recomendaciones; el grafo KNN representa similitud de perfiles, no coparticipación contractual. Para PageRank/HITS se podrá derivar una red bipartita entidad → proveedor de la matriz, con sus reglas y ventana explícitas.

## Particionamiento: medición y límites

Las tablas de interacciones se escriben por `award_year`; el constructor configura ocho particiones de shuffle. En Windows 11, Python 3.12.10, Spark 3.5.6, `local[4]` y AQE desactivado, el experimento reproducible en [notebook 03](../notebooks/03_particionamiento_spark.ipynb) encontró 40 archivos Parquet y particiones de 2015 a 2024. El plan del filtro 2023 mostró `PartitionFilters` por `award_year`, lectura de `entity_id` y `award_count` y `Exchange` por entidad en la agregación.

Con un calentamiento y dos mediciones por configuración, la consulta 2023 devolvió 2 510 entidades y 41 759 adjudicaciones en todos los casos. Las dos mediciones fueron 0,531 y 0,467 s con cuatro particiones, y 0,441 y 0,458 s con ocho. La imagen Docker se estaba construyendo durante el experimento; pueden influir la carga del equipo, cachés y orden. No se recogieron métricas de bytes de shuffle o spill, y estas pocas mediciones **no establecen una mejora general**. La ordenación de totales de hasta 256 buckets del diccionario tiene una etapa global; el orden de IDs dentro de cada bucket se distribuye.

## Validación y reproducción

El comando oficial de construcción, después de ejecutar las etapas anteriores de la guía, es:

~~~powershell
python -m src.features.build_part1 --overwrite
~~~

En Docker:

~~~bash
docker compose run --rm pipeline python -m src.features.build_part1 --overwrite
~~~

Comprobar en Windows:

~~~powershell
Test-Path data\processed\part1\_SUCCESS
~~~

Debe devolver `True`; el comando debe imprimir `Parte I publicada:` y terminar con código 0. Las rutas y los puntos de control completos están en la guía. Se verificaron independientemente la unicidad de pares de la matriz, la suma de conteos, los índices, la ausencia de autoaristas y cinco vecinos por entidad; cuatro nodos se contrastaron contra distancias exactas calculadas de forma independiente. Las pruebas sintéticas verifican agregación, empates, límite de pares, detección de entradas de corridas distintas y orden portable de la huella. La suite local completa aprobó 26 pruebas y Ruff no encontró errores.

La publicación escribe primero en un directorio temporal y publica el conjunto cuando todas sus tablas tienen `_SUCCESS`. Los metadatos guardan ventana, reglas, categorías, parámetros, conteos, límite y huellas SHA-256 del contenido actual de ambas tablas de interacción, además de su `run_id` común. Esto detecta cambios en esas entradas al comparar huellas, pero **no prueba la procedencia histórica completa** hasta los archivos OCDS; se debe regenerar el pipeline desde la fuente verificada para esa trazabilidad operativa.

La comparación de huellas se comprobó en Windows y Docker usando las mismas entradas. Los directorios de caché de pytest, Ruff y Python están ignorados por Git y son regenerables. Los tres notebooks se conservan porque permiten verificar calidad, identidad y particionamiento; la limpieza automática de las cachés fue bloqueada por la política de ejecución de este entorno.

## Estado para continuar

Vectores, matriz y grafo están construidos en Windows y Docker con la configuración descrita; los Parquet generados en Docker se leyeron y conciliaron desde Windows. Las interacciones y la extracción de identidad también se ejecutaron en Docker sobre tablas ya existentes, con los mismos totales de referencia. La identidad sigue sin una deduplicación canónica confirmada y el estudio de rendimiento es exploratorio. Posteriormente se completó el análisis descriptivo de clustering y anomalías: consultar [README_ParteII.md](README_ParteII.md). La ruta completa de Docker desde la descarga debe validarse antes de declararla íntegramente reproducida en esta corrida.
