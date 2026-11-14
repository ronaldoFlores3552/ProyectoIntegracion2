# Parte II — Clustering y anomalías

**Actualización:** 25 de octubre de 2026, hora de Lima.  
**Estado:** análisis de la Parte II completo para la ventana y los datos definidos: preparación, KMeans++, HDBSCAN, jerárquico con dendrograma e interpretación. Los resultados son descriptivos y sus límites permanecen vigentes.

## Pregunta y alcance

¿Qué perfiles de entidades aparecen en el volumen y composición de sus adjudicaciones observadas de 2023–2024? Se utilizan 2 756 entidades y 81 724 adjudicaciones de los archivos OCDS de fuente 2023 y 2024. Las categorías son bienes, servicios y obras. No se utilizan importes ni se comparan monedas.

Los archivos no constituyen necesariamente un censo y algunos releases fueron publicados después de las adjudicaciones. Las identidades no están completamente resueltas. La escala se ajustó con toda la ventana: **no sirve para evaluar predicción temporal sin volver a ajustar solo sobre entrenamiento**. Fuente y contexto en [README_ParteI.md](README_ParteI.md); el diseño y las etapas pendientes están en [PlanParteIIClustering.md](PlanParteIIClustering.md).

## Cómo se prepararon y procesaron los datos

El módulo [build_clustering.py](../src/models/build_clustering.py) valida `_SUCCESS`, ventana, huellas y `run_id` de las interacciones que alimentaron Parte I; comprueba el diccionario de categorías, el número y tamaño de entradas, unicidad de entidad, proporciones, conteos y finitud. La huella de las entradas inmediatas no prueba la procedencia histórica completa hasta la fuente original.

La ejecución limita por defecto a 10 000 filas y 256 MiB de archivos Parquet; `--max-rows` permite cambiar el límite de filas. Estos controles no estiman el pico real de memoria de los algoritmos: antes de aumentar la escala se debe incorporar y validar una estimación de memoria o diseñar una alternativa adecuada.

Se utiliza `log1p` del conteo y tres proporciones. Se comparan: escala estándar y escala estándar con el bloque de proporciones multiplicado por `1/sqrt(3)`. La segunda se usa para la selección provisional; es una decisión metodológica, no una garantía de equivalencia entre dimensiones. Las proporciones suman uno y son dependientes. Semilla 42, `n_init=20`, silueta sobre hasta 1 500 entidades y un hilo para las bibliotecas numéricas. La población se ajusta completa por tratarse de un análisis descriptivo.

## Resultados locales de referencia

Las cifras siguientes corresponden a la ejecución local en Windows con los datos registrados en el manifiesto. El módulo también se ejecutó en Docker: conservó la misma selección de KMeans y HDBSCAN, pero en HDBSCAN registró 1 343 entidades de ruido (48,7 %), frente a 1 348 en Windows. No se ha determinado la causa de esta diferencia. Consulta el `_metadata.json` de cada ejecución; la semilla y las versiones no garantizan resultados numéricos idénticos entre plataformas.

- La mediana es de **11 adjudicaciones por entidad**, con cuartiles de 4 y 29. Se observaron **1 421 vectores distintos entre 2 756 entidades**: hay muchos perfiles idénticos.
- La regla provisional de KMeans++ evalúa `k=2..8`, elige la mayor silueta de la variante ponderada y exige que cada grupo tenga al menos el 1 % de las entidades y 15 filas. Seleccionó **k=4**, con silueta aproximada **0,359** y grupos de 395 a 968 entidades. No equivale a afirmar que existan exactamente cuatro tipos reales.
- Los cuatro perfiles tienen medianas de 41, 5, 6 y 6 adjudicaciones. Uno muestra mayor volumen y composición mixta; los otros presentan mayor peso mediano de obras, servicios y bienes, respectivamente. Las etiquetas numéricas son arbitrarias.
- Para HDBSCAN se exploraron `min_cluster_size` 15, 30 y 60 y `min_samples` 5 y 10 en ambas escalas. La regla provisional exige al menos dos grupos y cobertura ≥ 50 %; por silueta sobre asignados eligió **15/5**, con **46 grupos** y **1 348 entidades de ruido (48,9 %)**. La silueta aproximada de 0,660 excluye ruido y no es comparable directamente con la de KMeans.
- De esos 46 grupos HDBSCAN, **21 contienen un solo vector distinto**, que reúne 641 entidades. La similitud exacta de las pocas variables puede crear densidades artificialmente marcadas. Además, con escala ponderada y parámetros 60/5 se observaron 4 grupos y 8,7 % de ruido. Por ello **no recomendamos tratar la selección provisional como segmentación definitiva**.
- Al comparar las dos escalas para k=4, el ARI fue aproximadamente 0,756; para HDBSCAN 15/5 fue 0,630 incluyendo ruido y 0,569 en las 1 313 entidades asignadas por ambas versiones. Los resultados dependen de la ponderación.
- Cinco remuestreos del 80 % de entidades dieron ARI de KMeans entre aproximadamente 0,936 y 0,992 frente a la corrida completa, calculado solo sobre los IDs comunes. La escala se mantuvo ajustada con el conjunto completo: es estabilidad **condicional al preprocesamiento**, no una validación temporal ni una prueba de estabilidad de todo el pipeline.

En KMeans se marcan para inspección las mayores distancias del 1 % por grupo cuando contiene al menos 100 entidades; en HDBSCAN se marcan las entidades de ruido de la configuración provisional. Estas marcas dependen de la configuración y **no son acusaciones, pruebas de fraude ni un porcentaje de irregularidades**. La variación entre grupos y parámetros hace necesario profundizar antes de comunicar casos individuales.

## Análisis jerárquico y contraste de métodos

El notebook calcula un árbol **Ward con distancia euclidiana** sobre la misma escala ponderada, usando una muestra reproducible de 400 entidades: 100 de cada tramo de volumen, con semilla 42. Los límites observados son 1–4, 5–11, 12–29 y 30–2 105 adjudicaciones; los empates permanecen juntos. Se registran los ID y los tamaños de población y muestra en el notebook. El muestreo equilibrado facilita comparar volúmenes, pero **no estima proporciones poblacionales**. El dendrograma muestra las últimas 25 fusiones, no cada entidad por separado; su altura es una medida del criterio Ward, no dinero ni probabilidad.

Se cortó el árbol en cuatro grupos para compararlo con el `k=4` de KMeans, no porque Ward pruebe que existan cuatro tipos. El ARI entre ambas asignaciones para los 400 ID comunes fue **0,483**: existe coincidencia parcial, pero el método y la muestra afectan la segmentación.

La referencia por volumen ayuda a interpretar qué agrega la composición. En la corrida Windows, el grupo de mayor volumen de KMeans reunió 672 de sus 968 entidades en el tramo superior; en cambio, los otros tres grupos tienen medianas de 5, 6 y 6 adjudicaciones, pero medianas de proporción de obras, servicios y bienes de 0,50, 0,91 y 0,72, respectivamente. Es decir, el volumen distingue una parte de los perfiles y las categorías separan perfiles de volumen similar. Son proporciones por número de adjudicaciones, no de gasto; no permiten concluir una especialización económica completa.

## Sensibilidad y señales atípicas

Se repitió HDBSCAN cinco veces sobre el 80 % de las entidades, comparando cada muestra con la ejecución completa solo en los ID comunes. En Windows, el ARI incluyendo ruido varió entre **0,420 y 0,669**; restringido a las entidades asignadas en ambas ejecuciones varió entre **0,358 y 0,838**, sobre intersecciones de 922 a 1 032 entidades. Estas cifras usan el escalado ajustado sobre toda la ventana y no validan estabilidad temporal. Junto con los vectores idénticos y la diferencia entre parámetros 15/5 y 60/5, apoyan la decisión de **no adoptar HDBSCAN como tipología definitiva**.

Las dos señales seleccionadas se cruzaron por entidad: de las 29 marcadas por distancia de KMeans, 14 también son ruido en HDBSCAN y 15 no lo son. La señal HDBSCAN incluye 1 348 entidades. Por ejemplo, una de las distancias más altas corresponde a una entidad con 2 105 adjudicaciones y proporciones aproximadas de 60 % bienes y 40 % servicios; otra tiene 1 235 y cerca de 99 % servicios. Son perfiles extremos en volumen o composición frente a su centroide, no evidencias de conducta irregular. El notebook muestra sus identificadores y variables originales para revisión contextual.

## Conclusiones y decisiones

1. Los datos permiten describir perfiles de volumen y composición de compra observados; no describen por sí solos gasto, riesgo ni desempeño.
2. KMeans ofrece una síntesis interpretable de cuatro grupos bajo esta parametrización. Su estabilidad por remuestreo es alta con el escalado fijo, aunque cambia al ponderar las categorías.
3. Ward aporta una lectura jerárquica sobre una muestra acotada y muestra que la partición depende del método; no extrapolamos su muestra equilibrada al universo.
4. HDBSCAN revela sensibilidad importante a la densidad y a los perfiles idénticos. Se conserva como análisis exploratorio, sin declarar sus 46 grupos una segmentación validada.
5. La fuente no es necesariamente un censo, la identidad puede estar fragmentada y las publicaciones pueden ser posteriores a la adjudicación. Toda comparación futura debe mantener esos límites y, si es temporal, reajustar el preprocesamiento solo con entrenamiento.

## Artefactos y réplica

`artifacts/clustering/` es regenerable y se publica como unidad con `_SUCCESS`, `_metadata.json` y Parquet para características, asignaciones de cada configuración, métricas y perfiles. El módulo no modifica tablas de la Parte I y rechaza entradas cambiadas o salidas existentes sin `--overwrite`. No se guardan modelos serializados ni archivos TXT por experimento.

Tras completar las etapas previas de la [guía](ComandosEjecutarOrdenReplica.md), ejecutar desde la raíz:

~~~powershell
python -m src.models.build_clustering --overwrite
~~~

El comando debe imprimir `Clustering publicado:` y terminar con código 0. Comprobar:

~~~powershell
Test-Path artifacts\clustering\_SUCCESS
~~~

Abrir [notebooks/04_clustering_y_anomalias.ipynb](../notebooks/04_clustering_y_anomalias.ipynb) en Jupyter para explorar la referencia de volumen, las métricas, perfiles, sensibilidad y candidatos. Los datos de ruido y distancia son señales descriptivas. El resultado oficial es regenerable; no se sube `artifacts/` a Git.

El notebook comprueba la huella de la Parte I antes de mostrar resultados: si se vuelve a construir la entrada, hay que regenerar el clustering. La ejecución con las versiones actuales puede emitir advertencias `FutureWarning` de una dependencia de HDBSCAN; estas no invalidaron las ejecuciones observadas.

## Continuidad

La Parte II queda cerrada para el alcance descriptivo definido. El reporte web interactivo pertenece a la entrega integral y aún debe integrar estos resultados. Antes de ampliar el volumen de datos, incorporar una estimación y límite explícito de memoria o diseñar una alternativa adecuada. Si se cambian la fuente, variables o población, repetir los análisis y revisar las conclusiones; no reutilizar automáticamente las etiquetas.
