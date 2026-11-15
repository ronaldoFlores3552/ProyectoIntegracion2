# Plan de la Parte II: Clustering y detección de anomalías

**Actualización:** 25 de octubre de 2026, hora de Lima.  
**Estado:** plan histórico de la Parte II, completada para el alcance descriptivo definido. Los resultados y límites vigentes están en [README_ParteII.md](README_ParteII.md).

## 1. Objetivo y relación con el enunciado

La [Parte II](Proyecto2Integrador.md) pide justificar características y estandarización, aplicar KMeans++ y un método de densidad, realizar un análisis jerárquico con dendrograma al menos en una muestra, e interpretar clústeres y valores atípicos. Spark es opcional para esta parte. La meta es responder una pregunta sobre contratación pública, no solo producir etiquetas.

**Pregunta principal:** ¿qué perfiles de entidades aparecen según el volumen de adjudicaciones observadas y la composición de categorías de compra durante 2023–2024?

**Pregunta secundaria:** ¿qué entidades tienen perfiles poco frecuentes respecto de otras del mismo conjunto y por qué podrían ser distintos? Son observaciones para investigar, no señales de fraude o culpa.

La Parte I construyó 2 756 vectores de entidad sobre 81 724 adjudicaciones elegibles, con `log1p` del volumen y proporciones de bienes, servicios y obras. El universo procede de archivos de fuente 2023 y 2024, no es necesariamente un censo completo del período. Ver [README_ParteI.md](README_ParteI.md) para fuente, fechas, identidad y calidad.

## 2. Principios de diseño

1. **Una entidad, una fila, una ventana:** la unidad es `entity_id`; conservar ID originales y la ventana de `award_year` 2023–2024. No se fusionan nombres ni se infiere identidad donde falta evidencia.
2. **Análisis descriptivo:** el primer resultado describe la ventana completa; no es una predicción histórica. La fuente puede contener releases publicados después de las adjudicaciones. Para una evaluación temporal posterior hay que verificar información disponible a la fecha de corte y ajustar todos los pasos solo con entrenamiento.
3. **Características observables y explicables:** no mezclar montos de monedas distintas y no llamar al conteo o a las proporciones una medida de corrupción, calidad o desempeño.
4. **Resultados trazables:** registrar entradas, huellas, ventana, versión de código cuando esté disponible, preparación, parámetros, semilla, versiones de bibliotecas, tamaño y métricas. Los notebooks explican e inspeccionan; el código que publique resultados oficiales debe ser reproducible.
5. **Escala proporcional:** Spark procesa y agrega el origen. pandas, NumPy, scikit-learn, HDBSCAN y SciPy se usan localmente solo si la tabla de vectores cabe con holgura en memoria. Antes de cargar, comprobar filas, dimensiones, tamaño estimado y límite configurable; si no cabe, detenerse y diseñar una alternativa distribuida o una muestra justificada. No trasladar datos crudos completos al driver.
6. **Etiqueta no es verdad:** el número de grupos, el ruido y los atípicos dependen de las variables, la escala y los parámetros; cada conclusión mostrará sensibilidad y cobertura.

## 3. Datos y construcción de variables

### Entrada principal

Leer `data/processed/part1/entity_features/` solo cuando el conjunto `part1` tenga `_SUCCESS` y metadatos coherentes. Comprobar sus huellas contra las dos tablas de interacción actuales y verificar la ventana; si no coinciden, detenerse y reconstruir, no mezclar corridas. Estas huellas solo identifican las entradas inmediatas y no prueban el origen histórico de todos los pasos anteriores.

La tabla contiene `entity_id`, `award_count`, `log_award_count`, `fraction_0`, `fraction_1`, `fraction_2` y `vector_original`. El significado y orden de las categorías procede de `_metadata.json`, no de una suposición fija. Revisar unicidad de ID, finitud, conteos positivos, proporciones entre cero y uno y suma aproximadamente uno. Reportar entidades y adjudicaciones excluidas antes del modelado. Si aparecen categorías nuevas o `<MISSING>`, no interpretar índices antiguos: leer el diccionario de la corrida, medir cobertura y revisar si es adecuado continuar.

### Diseño inicial de dos representaciones

| Versión | Variables | Propósito |
|---|---|---|
| Referencia simple | `log1p(award_count)` | Saber qué resultados aparecen solo por volumen. No se necesita convertirla en un modelo complejo para poder compararla. |
| Principal | `log1p(award_count)` y proporciones de categorías | Comparar volumen y composición de compra; excluir montos por ahora. |

Las proporciones suman uno y no son tres variables independientes; la distancia euclidiana en proporciones puede dar un peso excesivo a la composición. Por ello, comparar al menos dos tratamientos, registrando ambos: estandarización por variable y una variante en que el bloque estandarizado de proporciones se multiplica por `1/sqrt(n_categorías)` para controlar su peso conjunto frente al volumen. Es una decisión de modelado que debe justificarse y someterse a sensibilidad, no una solución universal para datos composicionales. Documentar dimensiones constantes y convertirlas a cero tras el escalado; no dividir por desviación cero.

Para este estudio descriptivo, ajustar medias y desviaciones sobre el universo elegible completo y guardar sus parámetros. No reutilizar automáticamente `vector_scaled` de la Parte I si se cambia el peso o el período; reconstruir la preparación a partir de las variables originales. Ante una evaluación posterior con entrenamiento/prueba, volver a ajustar el preprocesamiento solo con entrenamiento.

**PCA:** solo como diagnóstico opcional de correlación, redundancia o visualización. Las cuatro variables actuales no justifican asumir reducción por defecto. Si se usa, registrar ajuste, varianza explicada y cargas; comparar con las variables originales y no usar una proyección bidimensional como prueba de calidad de grupos en el espacio original.

## 4. Herramientas y motivo de elección

| Herramienta existente | Uso propuesto | Fundamento y límite |
|---|---|---|
| PySpark 3.5.6 | Preparar las tablas y vectores oficiales de entrada. | Ya se usa en Parte I. Spark ML KMeans usa otra inicialización; no lo llamaríamos KMeans++ sin verificarlo. |
| scikit-learn 1.6.1 | `KMeans` con `init='k-means++'`, escalado, silueta y comparación de etiquetas. | Cumple la variante pedida y facilita un experimento pequeño reproducible; la ejecución es local y requiere límite de memoria. |
| `hdbscan` 0.8.40 | Método de densidad principal y etiquetas de ruido. | Ya figura en `requirements.txt`; probar sensibilidad de tamaño mínimo y densidad en el conjunto manejable. |
| SciPy 1.13.1 | Clustering jerárquico y dendrograma en una muestra. | Evita calcular una matriz de distancias cuadrática para un conjunto creciente. |
| pandas, NumPy, PyArrow, Matplotlib | Lectura de Parquet agregado, inspección y gráficos. | Operan sobre la representación pequeña; no reemplazan la extracción Spark. |
| JupyterLab, pytest y Ruff | Análisis narrado, pruebas de contratos y estilo. | No crear scripts solo para guardar texto o apuntes. |

[README_HERRAMIENTAS.md](README_HERRAMIENTAS.md) es referencia histórica del curso/proyecto anterior. Su «Parte II» de Jaccard/MinHash/LSH no corresponde a la Parte II de este enunciado y no se considera requisito de clustering. Reutilizamos bibliotecas y criterios de medición que sí aportan a esta pregunta; no agregamos técnicas por semejanza de nombre.

## 5. Diseño de experimentos

### 5.1 Preparación y línea base

1. Documentar población, período, huellas y razones de exclusión. Inspeccionar distribuciones de volumen y categorías, cuantiles, extremos, ceros y posibles valores faltantes en el notebook.
2. Revisar ejemplos de entidades de bajo y alto volumen y composiciones dominantes, sin presentar su tamaño como riesgo.
3. Calcular una referencia descriptiva por volumen: mediana, cuartiles y distribución de categorías. Puede usarse una segmentación por cuantiles de volumen como línea base simple para contrastar si los modelos aportan algo más; registrar cómo se manejan empates y grupos vacíos.
4. Fijar antes de ejecutar la semilla `42`, versiones, orden de ID, variantes de escalado, rangos, métricas y límites. La semilla es un punto de partida para reproducción, no demuestra estabilidad por sí sola.

### 5.2 KMeans++: grupos de perfiles generales

Entrenar scikit-learn `KMeans(init='k-means++')` con semilla fija y `n_init` explícito, por ejemplo 20, en las dos variantes principales. Probar inicialmente `k = 2, ..., 8` cuando el tamaño de la muestra lo permita; estos valores son una búsqueda inicial, no conclusiones anticipadas.

Para elegir candidatos de k, combinar inercia/codo, silueta en el espacio usado para entrenar, tamaño del grupo más pequeño y capacidad de interpretar perfiles en unidades originales. La silueta no es válida si queda un solo grupo o cada punto forma su propio grupo. Registrar las condiciones. Examinar sensibilidad a varias semillas y remuestreos; no seleccionar automáticamente por una sola métrica. Si ningún k ofrece grupos suficientemente coherentes o estables, reportar ese resultado sin fabricar una tipología.

Publicar por entidad el grupo de la configuración elegida y la distancia a su centroide **en el espacio transformado**; describir centroides y distribuciones también en valores originales. Las etiquetas numéricas son arbitrarias y no se comparan directamente entre corridas.

### 5.3 HDBSCAN: densidad y ruido

Aplicar HDBSCAN sobre el mismo universo y preparación principal para comparar qué perfiles forman zonas densas y cuáles quedan como ruido (`-1`). Explorar una rejilla acotada inicial de `min_cluster_size` 15, 30 y 60 y `min_samples` 5 y 10, siempre que la población lo permita. Son hipótesis iniciales y se deben ajustar si cambian los datos.

Registrar número y tamaño de grupos, porcentaje de ruido, porcentaje de entidades asignadas y estabilidad que ofrezca la biblioteca. Calcular silueta solo en puntos asignados y solo cuando haya al menos dos grupos válidos; informar siempre la cobertura para que no parezca comparable con una silueta calculada sobre todos los puntos. Si todo o casi todo queda en ruido, o solo existe un grupo, documentarlo como resultado y revisar escala y parámetros, sin forzar grupos.

### 5.4 Jerárquico y dendrograma

Usar una muestra reproducible de hasta **400 entidades** porque el cálculo de distancias jerárquicas crece aproximadamente de forma cuadrática. Seleccionar entidades por muestreo aleatorio estratificado por tramos de volumen, con semilla fija, registrando límites, asignación, IDs seleccionados y cobertura por tramo. Es una muestra diseñada para comparar perfiles de diferentes tamaños, no una estimación automática de proporciones poblacionales. En caso de empates o tramos vacíos, registrar el procedimiento y reasignación de cupos.

Probar enlace Ward con distancia euclidiana sobre las características transformadas y un dendrograma legible (por ejemplo, truncado si hace falta); explicar que representa solamente la muestra y cómo se eligió el corte si se compara con otras etiquetas. No interpretar la altura como monto o probabilidad. No convertir todo el universo en una matriz de distancias sin calcular y aplicar un límite de memoria.

### 5.5 Anomalías: señales distintas

- **HDBSCAN:** entidades etiquetadas como ruido bajo cada configuración. El ruido indica baja densidad relativa, no error ni conducta irregular.
- **KMeans:** distancia al centroide asignado, observada dentro del clúster. Como regla exploratoria inicial, mostrar el 1 % de mayores distancias por clúster solo si su tamaño lo permite; indicar que el porcentaje es una elección de inspección, no una tasa de anomalías reales. Para grupos pequeños, mostrar distancias sin forzar ese porcentaje.
- Describir cada caso con variables originales, tamaño de su grupo, cobertura, fecha de corte y criterio que lo seleccionó. Comparar si las señales coinciden sin asumir que un desacuerdo es un fallo: cada método mide algo distinto.

## 6. Evaluación, estabilidad e interpretación

| Pregunta | Evidencia y decisión |
|---|---|
| ¿Los grupos están separados en el espacio modelado? | Inercia, silueta cuando sea válida y distribución de tamaños; interpretar conjuntamente. |
| ¿El resultado cambia con la escala? | Comparar las dos variantes de peso y los grupos identificados, usando etiquetas alineadas o métricas invariantes a su numeración. |
| ¿Es estable? | Repetir semillas de KMeans y remuestreos reproducibles; comparar asignaciones solo para IDs en común mediante ARI, aclarando población y tratamiento de ruido. Informar distribución, no solo el mejor caso. |
| ¿Qué ocurre con HDBSCAN? | Reportar ruido y cobertura en cada configuración; calcular métricas internas solo cuando sean válidas y sobre la población indicada. |
| ¿El modelo agrega conocimiento? | Comparar perfiles con la línea base por volumen y describir si composición agrega diferencias interpretables. |
| ¿Qué significan los grupos? | Mediana y cuantiles de adjudicaciones, proporciones de categorías, número de entidades y ejemplos; expresar límites de los datos y evitar etiquetas acusatorias. |

En remuestreos de entidades, repetir por ejemplo cinco subconjuntos de 80 % con semillas documentadas y medir ARI en las intersecciones. Para HDBSCAN especificar por separado comparaciones que incluyen ruido y las restringidas a entidades asignadas en ambas corridas; reportar cuántas quedan. No comparar ARI entre poblaciones distintas sin indicar la intersección. Si la asignación futura de entidades nuevas es necesaria, definirla y evaluarla explícitamente; HDBSCAN no ofrece automáticamente el mismo contrato de predicción que KMeans.

## 7. Arquitectura de implementación propuesta

```text
data/processed/part1/entity_features + _metadata.json
        → validación de ventana, huellas y variables
        → preparación y parámetros de escala
        → KMeans++ / HDBSCAN / jerárquico en muestra
        → asignaciones, métricas, perfiles y metadatos oficiales
        → notebook: gráficos, interpretación y conclusiones
        → artefactos ligeros para el reporte web futuro
```

| Ubicación | Responsabilidad prevista |
|---|---|
| `src/models/` | Módulo implementado para preparación, experimentos y publicación segura de KMeans++ y HDBSCAN. El jerárquico se calcula en el notebook. |
| `notebooks/04_clustering_y_anomalias.ipynb` | Inspección, gráficos, selección razonada, dendrograma y análisis en lenguaje natural. No modifica tablas de la Parte I. |
| `tests/` | Pruebas proporcionadas de preparación, trazabilidad, ruido, métricas no válidas y publicación segura; no pruebas que solo repitan el código. |
| `artifacts/clustering/` | Salida oficial regenerable implementada, ignorada por Git, con asignaciones, perfiles, métricas y metadatos versionados. No escribir TXT de resultados por cada experimento. |
| `docs/README_ParteII.md` | Reporte de metodología, resultados y límites cuando existan; este plan permanece como historial. |

Una corrida oficial debería publicar, como conjunto consistente: asignaciones por `entity_id` y método, métricas por configuración, perfiles interpretables, configuración elegida y su justificación, metadatos de fuente/huellas/ventana/semillas/escalado/versiones y `_SUCCESS`. Si se usan varias tablas, publicar con staging y versión o `run_id` común, evitando resultados a medio escribir. Dendrograma y visualizaciones pueden vivir en el notebook; exportar imágenes o JSON ligeros solo cuando sean necesarios para el informe web. Guardar objetos binarios de modelo únicamente si un consumidor posterior realmente los necesita y con versiones compatibles documentadas.

Los comandos implementados para Windows, Docker y Linux/macOS están en [ComandosEjecutarOrdenReplica.md](ComandosEjecutarOrdenReplica.md), con entradas requeridas y criterios de éxito. El notebook es accesible desde la sesión Jupyter ya documentada.

## 8. Orden de trabajo y criterios de avance

| Paso | Acción | Se considera listo cuando... |
|---|---|---|
| 1 | Auditar entrada y representar el universo. | Coinciden huellas y ventana; se conocen cobertura, exclusiones y distribuciones. |
| 2 | Preparar las dos variantes de escala y la línea base. | Se verifican valores finitos, dimensiones constantes y parámetros; los cambios se pueden explicar. |
| 3 | Ejecutar KMeans++ para k inicial y semillas. | Hay métricas válidas, perfiles y selección justificada o un resultado negativo documentado. |
| 4 | Ejecutar HDBSCAN y análisis de ruido. | Se reportan tamaños, cobertura, sensibilidad y casos sin forzar clústeres. |
| 5 | Realizar jerárquico en muestra. | Muestra y dendrograma son reproducibles y se conocen sus límites. |
| 6 | Comparar, interpretar y revisar anomalías. | Cada conclusión se conecta con variables originales, evidencia, sensibilidad y límites éticos. |
| 7 | Publicar y documentar. | Los artefactos y metadatos se regeneran; pruebas y comandos están documentados; se escribe el README de resultados. |

**Cierre:** se deben cumplir las tres familias exigidas por el enunciado, interpretar los resultados y registrar resultados fallidos si los hubiera. No dar por completada la parte simplemente porque los comandos terminaron o una métrica parece alta.

## 9. Riesgos y decisiones pendientes

- **Cobertura y versiones:** los archivos seleccionados no representan necesariamente todo el mercado y los releases pueden ser posteriores a la adjudicación; evitar afirmaciones prospectivas.
- **Identidad:** los ID no resueltos pueden fragmentar entidades o relaciones. La Parte I no demuestra una deduplicación completa.
- **Variables escasas:** solo existen volumen y tres categorías amplias; perfiles similares pueden esconder diferencias sustanciales y los outliers pueden reflejar coberturas distintas. Evaluar enriquecimiento a partir de fuentes existentes solo si una pregunta lo necesita.
- **Escalado y composición:** las tres proporciones están relacionadas; el peso elegido afecta distancias y clústeres. Reportar sensibilidad y no convertir una ponderación en verdad de negocio.
- **Disponibilidad y memoria:** antes de usar ejecución local medir el tamaño. El jerárquico en particular exige muestra y límites explícitos.
- **Interpretación ética:** una entidad lejana, grande o clasificada como ruido no es sospechosa por ese hecho.

## 10. Estado y siguiente paso

Preparación, KMeans++ y HDBSCAN se implementaron y publicaron. El notebook incorpora Ward, dendrograma, comparación por volumen y remuestreos de HDBSCAN; las conclusiones están en [README_ParteII.md](README_ParteII.md). Los límites actuales de filas y tamaño de archivo no sustituyen la estimación de memoria propuesta en este plan; esta debe incorporarse antes de aumentar la escala.
