# Parte I: reporte de avance y plan integral de cierre

**Actualización:** 25 de octubre de 2026, hora de Lima.  
**Estado:** registro histórico del plan previo a la implementación. Para resultados posteriores y estado vigente, consultar [README_ParteI.md](README_ParteI.md). Las secciones de pendientes a continuación corresponden al momento en que se escribió el plan.

## 1. Objetivo y alcance

La Parte I del [enunciado](Proyecto2Integrador.md) exige utilizar Spark para aplanar y transformar los datos, abordar la resolución de entidades, construir y exportar vectores, una matriz de interacción y un grafo de coparticipación o KNN, y explicar el particionamiento y su efecto en el plan de ejecución. Estas salidas son la base de las partes posteriores; tener agregados intermedios todavía no equivale a cumplir con todos los entregables.

El proyecto estudia contrataciones públicas peruanas publicadas en OCDS por OECE/OSCE. La fuente se debe citar con su licencia CC BY 4.0: [registro OCDS de Perú](https://data.open-contracting.org/es/publication/135) y [Contrataciones Abiertas](https://contratacionesabiertas.oece.gob.pe/). Las cifras siguientes describen una corrida concreta, no la totalidad del mercado peruano.

## 2. Estado frente al enunciado

| Requisito de Parte I | Estado | Evidencia y falta |
|---|---|---|
| Transformación y aplanado en Spark | Avanzado | `fact_award_item`, `fact_award` y `fact_award_supplier` publicados y perfilados para los archivos 2023 y 2024. Consolidar linaje y validación integral. |
| Abordar identidad de compradores y proveedores | Diagnóstico avanzado, resolución incompleta | Se extrajo evidencia OCDS y se revisaron candidatos. No hay correspondencia canónica verificada ni medición de su efecto sobre los artefactos. |
| Vectores de características | Pendiente | Publicar representación por entidad, diccionario, reglas y estadísticas de preparación. |
| Matriz de interacción | Pendiente | Exportar representación dispersa y diccionarios de entidad/proveedor. Las tablas altas actuales son entradas, no la matriz final. |
| Grafo de coparticipación o KNN | Pendiente | Construir y exportar nodos y aristas KNN de entidades en Spark, con criterio de vecindad explícito. |
| Particionamiento y plan Spark | Pendiente | Medir archivos, particiones, filtros, `explain` y métricas antes/después en una corrida controlada. |
| Reproducibilidad y cierre | Parcial | Hay Docker, entorno local, pruebas y guía; faltan validación integral de las nuevas etapas y el informe final con resultados reales. |

La Fase 3 interna corresponde al trabajo de representaciones de la Parte I; las fases internas no son las partes numeradas del enunciado. **La Parte I aún no está terminada.**

## 3. Qué se hizo y qué se descubrió

### 3.1 Datos y calidad

Los archivos de referencia son los JSONL.GZ de los años de archivo 2023 y 2024, con SHA-256, respectivamente, `34a8cd64afee7b8d1cde3f44e30f9101bbd2537add96ccf6db79cca9bafab65a` y `9f50c84423c65605b4280d2d88b9da0853ebeb0b556d2dedf66add435cbde6e0`. Sus hashes se registran en `data/raw/manifest.json` y en los metadatos de evidencia de identidad.

| Indicador | Corrida de referencia | Interpretación |
|---|---:|---|
| Filas de `fact_award_item` | 137 292 | Grano proceso × adjudicación × proveedor × ítem. |
| Procesos distintos | 119 762 | No equivale a número de adjudicaciones. |
| Adjudicaciones distintas | 128 395 | Clave compuesta `process_ocid` + `award_id`. |
| Proveedores / entidades | 62 919 / 2 967 | ID originales observados; pueden fragmentar una identidad real. |
| Fechas de adjudicación ausentes | 35 | Se conservan en las fuentes y se excluyen de las tablas anuales, con conteo. |
| Filas de ítem sin clasificación | 18 752 | Es la clasificación del ítem; no se confunde con `procurement_category`. |

En esa corrida no se encontraron duplicados exactos ni repeticiones de la clave candidata del detalle. Se observaron varias monedas y una moneda ausente en `fact_award`. El monto de adjudicación se repite entre ítems, por lo que sus agregados monetarios se hacen desde `fact_award` o mediante la regla por proveedor, siempre separados por moneda. Buyer y procuring entity coincidieron en el conjunto examinado. Las fechas observadas van de 2015 a 2024, por lo que el año del archivo **no** es necesariamente el año de adjudicación. Detalle y criterios en [PlanFase2CalidadEDA.md](PlanFase2CalidadEDA.md) y [ContratoDatos.md](ContratoDatos.md).

### 3.2 Tablas relacionales y primeras interacciones

`fact_award` tiene una fila por proceso y adjudicación; `fact_award_supplier`, una por proceso, adjudicación y proveedor. En la corrida actual ambas tienen 128 395 filas y se observó un proveedor por adjudicación. El código no presupone que eso sea universal: un monto no se reparte entre varios proveedores sin evidencia.

Las tablas anuales altas `entity_supplier_year` y `entity_category_year` se publicaron con el mismo `run_id` y reconcilian 128 360 filas elegibles cada una. Tienen 108 924 y 21 744 grupos, respectivamente; las 35 filas sin fecha quedan fuera de ambas. Su grano incluye moneda, por lo que, para construir una interacción basada en conteos, deben sumarse los conteos entre monedas después de filtrar el período, sin sumar importes de monedas diferentes. Véanse [PlanFase3Representaciones.md](PlanFase3Representaciones.md) y los metadatos de las tablas para el alcance exacto.

### 3.3 Identidad y resultados de investigación

El notebook [02_diagnostico_resolucion_entidades.ipynb](../notebooks/02_diagnostico_resolucion_entidades.ipynb) identificó 2 858 nombres normalizados de proveedor asociados a varios ID y 338 ID con varios nombres. Para compradores observó dos nombres con varios ID y ningún ID con varios nombres. Son **candidatos**, no duplicados confirmados.

La extracción de evidencia OCDS encontró 128 308 referencias de proveedor coincidentes con una sola `party` y 32 sin coincidencia; encontró una sola coincidencia para las 119 762 referencias de comprador. Estas son referencias distintas por año de archivo, proceso, release, rol e ID, no conteos de entidades únicas. Las 32 referencias no coincidentes se localizaron en adjudicaciones de 29 contextos de release, pero sin un `party.id` igual. De ellas, 23 tenían nombre; ninguna tenía un nombre exactamente igual en una `party` del mismo release.

No hubo grupos de ID de referencia compartiendo el mismo esquema y valor exacto en la evidencia vinculada. Eso no demuestra ausencia de duplicados. Los diez nombres con más ID de la muestra intencional comienzan por «consorcio», reúnen 723 ID y todos tenían evidencia vinculada con esquema `PE-RUC`. La etiqueta de esquema no valida el valor como RUC. Nombres idénticos y la falta de `party` no justifican fusiones. Por ahora se conservan los ID originales; la resolución de identidad sigue pendiente de decisiones y evidencia adicionales.

### 3.4 Qué sabemos de la ejecución

Se dispone de Python 3.12, Java 17, PySpark 3.5.6, Parquet, Docker y guía local multiplataforma. La documentación registra 22 pruebas aprobadas y Ruff sin errores en la última validación de código; el notebook 02 se ejecutó localmente para esta investigación. La ruta Docker del pipeline inicial fue validada previamente; **las etapas nuevas de interacciones e identidad no están validadas en Docker**. La verificación de hashes de archivos raw no demuestra por sí misma que las tablas ya publicadas se generaron con esos mismos bytes: falta una cadena de linaje verificable entre etapas.

## 4. Preguntas que guían las representaciones

Propuestas de trabajo para discutir y afinar con el equipo:

1. ¿Qué perfiles de compra presentan las entidades según su volumen de adjudicaciones y la distribución de sus categorías? Alimenta vectores, KNN y posteriormente clustering.
2. ¿Cómo se distribuyen las relaciones observadas entre entidades y proveedores, y cuánto varían entre períodos? Alimenta matriz, recomendación y la red bipartita posterior.
3. ¿Cómo cambia la estructura observada de los resultados cuando existen identidades no resueltas o enlaces incompletos? Alimenta diagnóstico, sensibilidad y comunicación de limitaciones.

Son preguntas analíticas sobre datos observados, no pruebas de irregularidad ni recomendaciones de contratación.

## 5. Decisiones propuestas para cerrar la Parte I

### 5.1 Universo, tiempo y datos elegibles

- Trabajar con los archivos de referencia 2023/2024 y conservar sus hashes. El año del archivo es una característica de procedencia; `award_date` define el período analítico.
- Para una primera entrega descriptiva, filtrar adjudicaciones con `award_date` en 2023–2024; las tablas anuales contienen también años anteriores y el filtro no debe sustituirse por `source_year`. Medir entradas y exclusiones por motivo, incluyendo posibles solapamientos.
- Como preparación para evaluación posterior, conservar la dimensión anual y definir una vista 2023 para entrenamiento y 2024 para evaluación. No convertir este corte por fecha de adjudicación en una afirmación de evaluación histórica real: los releases observados pueden publicarse después del evento. Para un experimento prospectivo hace falta verificar la disponibilidad efectiva y las versiones conocidas a cada fecha; si no existen, llamarlo evaluación retrospectiva con esa limitación.
- Mantener los ID originales de entidad y proveedor. No usar nombres para fusionar y no interpretar la ausencia de vínculo con `party` como una identidad nueva confirmada.
- Registrar valores faltantes y excluidos; no imputar fechas ni sumar montos entre monedas. El identificador analítico de adjudicación es `process_ocid` + `award_id`.

### 5.2 Identidad: una respuesta trazable, no una deduplicación ficticia

1. Mantener el diagnóstico existente y preparar una tabla de revisión de candidatos en el notebook con contexto, ID originales, nombres, evidencia disponible y motivo de selección. Seleccionar una muestra reproducible que incluya nombres compartidos, variantes de nombre y los casos sin `party`.
2. Documentar criterios de aceptación, rechazo y pendiente antes de revisar. La igualdad exacta de un identificador oficial del mismo esquema puede ser evidencia fuerte, pero comprobar la procedencia y que el esquema sea válido para ese caso; un nombre igual o un formato parecido no basta.
3. Si aparecen equivalencias sustentadas y revisadas, publicar un mapeo versionado con rol, ID original, ID canónico, estado, motivo, evidencia, responsable y versión de fuente. Detectar conflictos y ciclos; no fusionar candidatos sin aprobación sustentada. Si no hay evidencia suficiente, publicar y documentar la política de identidad original y los casos pendientes, sin inventar una deduplicación.
4. Comparar para el mismo universo las cantidades de nodos, interacciones y aristas con los ID originales y, si existiera, con el mapeo revisado. Informar cuánto se revisó y las limitaciones; una muestra no demuestra que el resto no tenga duplicados.

Esto aborda el requisito con honestidad metodológica, pero la aceptación académica de una resolución conservadora sin fusiones verificadas debe sustentarse ante el docente; no se debe marcar como deduplicación completa.

### 5.3 Vectores de características por entidad

**Entrada:** `entity_category_year`, fuente de conteos por entidad, categoría, año y moneda. Filtrar la ventana y agregar `award_count` entre monedas y años para cada entidad–categoría. El conteo no combina dinero. `procurement_category` es una categoría amplia de contratación, no la clasificación detallada del ítem.

**Primera representación propuesta:** una fila por entidad con volumen `log1p(total_adjudicaciones)` y proporciones de adjudicaciones por categoría, con una dimensión explícita para `<MISSING>` si aparece. El diccionario de categorías se deriva de la ventana de ajuste con orden determinista; valores futuros fuera del diccionario se contabilizan como desconocidos y no se descartan silenciosamente. El tamaño del diccionario y la política para valores desconocidos se fijan en metadatos. No se añade monto para evitar comparaciones entre monedas sin conversión.

Las proporciones y el volumen tienen escalas distintas. Para construir el grafo, ajustar la estandarización únicamente en el universo de ajuste, guardar parámetros, manejar columnas de varianza cero y registrar el orden de las dimensiones. Los vectores originales y los transformados deben conservar sus definiciones; no se debe ajustar el escalado con el conjunto de evaluación. Reportar entidades excluidas, categorías desconocidas, dimensiones, nulos y vectores sin información.

**Salida propuesta:** `data/processed/part1/entity_features/` con `entity_id`, ventana, variables interpretables y vector Spark; junto al diccionario, parámetros y metadatos versionados. El formato físico definitivo se validará con Spark y lectores posteriores; si el tipo vector de Spark no se intercambia cómodamente, publicar además componentes numéricos documentados. Esta salida debe ser construida en Spark.

### 5.4 Matriz de interacción entidad × proveedor

**Entrada:** `entity_supplier_year`. Filtrar período, agrupar por entidad y proveedor y sumar `award_count` entre años y monedas. Cada valor es el número de adjudicaciones observadas entre ambos en la ventana; no es monto, preferencia ni señal causal. Conservar en una tabla separada la granularidad anual para futuros cortes temporales.

**Salida:** coordenadas dispersas Parquet `(entity_id, supplier_id, interaction_count)`, con una única fila por par y conteo positivo; diccionarios ordenados de ID originales a índices enteros contiguos, únicos y de base cero. La matriz lógica se reconstruye a partir de las coordenadas; no crear una matriz densa ni llevarla íntegra al driver. Sus dimensiones, universo, filtros, diccionarios y reglas deben viajar juntos en una publicación coherente con `_SUCCESS` y metadatos. No reutilizar índices de otra versión del diccionario sin verificación.

**Controles:** claves únicas, no nulas, conteos positivos, índices válidos, suma de conteos igual a la de la fuente elegible y ausencia de eventos del período de evaluación en el ajuste. Un mismo par entidad–proveedor puede aparecer en ambos períodos si corresponde a eventos distintos. Registrar dimensiones, número de celdas no nulas, densidad y exclusiones.

### 5.5 Grafo KNN obligatorio y red bipartita para etapas posteriores

**Grafo de la Parte I:** KNN entre entidades según sus vectores estandarizados. Cada nodo conserva su `entity_id`; una arista dirigida `A → B` indica que B está entre los `k` vecinos de A. Usar distancia euclidiana sobre el vector con parámetros guardados; proponer `k = 5` como punto de partida, no como valor óptimo. Excluir autoaristas, ordenar empates por `entity_id` y registrar si hay menos de k vecinos elegibles. No asumir que una arista implica causalidad o relación contractual.

Publicar nodos y aristas en Parquet con ventana, `src`, `dst`, distancia y orden de vecino, junto con metadatos de k, dimensiones, ajuste, criterios y versión de entradas. Incluir nodos aislados y cuantificarlos. Construir el grafo en Spark, sin convertirlo en un grafo de Python en memoria como salida oficial. En esta primera versión no se simetriza; cualquier grafo no dirigido posterior debe definir unión o vecindad mutua y cómo combina distancias.

Con unas 2 967 entidades observadas antes del filtro, una comparación exacta por pares puede ser viable como referencia, pero cuesta O(n²): validar primero el número real de nodos, cardinalidad estimada, duración y memoria; fijar un límite documentado que detenga la ejecución antes de exceder recursos. Para crecimiento, diseñar una alternativa aproximada distribuida, por ejemplo LSH de Spark, y medir su recuperación de vecinos frente a exacto en una muestra determinista. El número de candidatos y el umbral de búsqueda deben registrarse; un método aproximado puede no devolver k vecinos. Si el exacto o aproximado resulta inviable, registrar el resultado y ajustar el diseño antes de declarar el grafo entregado.

**Red para la Parte IV:** las coordenadas de la matriz también permiten derivar aristas dirigidas comprador → proveedor con tipos de nodo explícitos y peso de conteo, apropiadas para HITS. Es una red contractual bipartita, no se presentará como grafo de coparticipación entre proveedores. Su entrega no reemplaza el KNN exigido en este plan; se construirá solo si su consumidor lo necesita y mantendrá una versión de ventana y diccionarios compatible.

## 6. Orden de ejecución y entregables

| Paso | Trabajo | Salida y puerta de avance |
|---|---|---|
| 1 | Fijar universo, ventana, preguntas, fuentes y versión de entradas. | Decisión documentada; conteos por año y exclusiones medidos en Spark. |
| 2 | Cerrar política de identidad y revisión proporcional de candidatos. | Criterios, evidencia, cobertura y pendientes; mapeo solo si está verificado. |
| 3 | Implementar vectores y diccionario de categorías. | Parquet, parámetros de ajuste, `_SUCCESS`, conciliación y notebook de interpretación. |
| 4 | Implementar matriz dispersa y diccionarios. | Coordenadas, índices y controles de suma/unicidad, para ventana global y corte anual. |
| 5 | Implementar grafo KNN. | Nodos/aristas, k y distancia documentados, control de tamaño, determinismo y cobertura. |
| 6 | Estudiar particiones y planes. | Evidencia antes/después y conclusión fundamentada, sin asumir que más particiones siempre es mejor. |
| 7 | Validar de extremo a extremo y cerrar el reporte. | Corrida reproducible, pruebas, guía actualizada y reporte con resultados reales y límites. |

Cada paso oficial debe tener una implementación Spark mantenible en `src/`, pruebas proporcionales en `tests/` y comandos reales en [ComandosEjecutarOrdenReplica.md](ComandosEjecutarOrdenReplica.md). El análisis, las visualizaciones y las explicaciones permanecen en notebooks; no crear scripts solo para generar TXT. Se podrá agrupar vectores, matriz y grafo en un módulo de publicación si las dependencias y el alcance lo hacen claro; no fijar nombres de comandos hasta que existan.

## 7. Particionamiento y escalabilidad: experimento reproducible

1. Registrar hardware, sistema, recursos asignados, versión de Spark/Java, tamaño de entrada, número de archivos y particiones, configuración de shuffle, caché, parámetros y datos de cada corrida. Las interacciones actuales se escriben por `award_year`; su constructor configura 8 particiones de shuffle. `fact_award_supplier` se escribe por `source_year`. Son configuraciones observadas, no una garantía de rendimiento.
2. Ejecutar la misma consulta de un año con selección de columnas y compararla con la consulta sin filtro: inspeccionar `explain` y los archivos leídos para comprobar si hay *partition pruning*. Documentar dónde aparecen `Exchange`, agregaciones y joins y qué operaciones implican shuffle.
3. Comparar al menos dos configuraciones justificadas de particiones con el mismo dataset y recursos. Registrar tiempo, tamaño y número de archivos, y métricas de tareas, shuffle y spill cuando estén disponibles; incluir corridas de calentamiento y repeticiones razonables. Aclarar caché, condiciones y variación; no afirmar mejoras solo por un tiempo aislado.
4. Evaluar sesgo de claves y archivos pequeños. Evitar particionar por ID de alta cardinalidad; elegir partición física según filtros reales y tamaño, no solo por comodidad. Si no hay evidencia de mejora, mantener la configuración base y reportar el resultado.
5. Para KNN registrar tamaño del universo, pares previstos, límite de seguridad y gasto observado. Para cualquier variante aproximada, medir tiempo, cobertura y recuperación de vecinos en una muestra contra el exacto. Esta comparación no demuestra escalabilidad ilimitada.

## 8. Reproducibilidad, arquitectura y validación

```text
data/raw/                         archivos OCDS y manifiesto
data/processed/fact_award_item/  detalle original aplanado
data/processed/fact_award/       adjudicaciones
data/processed/fact_award_supplier/
data/processed/entity_*_year/    interacciones anuales altas existentes
data/processed/identity_evidence/ evidencia y diagnóstico de identidad
data/processed/part1/            vectores, matriz y grafo propuestos
src/                             transformaciones Spark oficiales
notebooks/                       exploración, interpretación y conclusiones
tests/                           pruebas necesarias de reglas y contratos
docs/                            decisiones, contrato, réplica y reporte
```

Las rutas bajo `part1/` son propuestas, todavía no existen. Publicar mediante staging y comprobación de `_SUCCESS`; si un conjunto de tablas se publica por separado, usar `run_id` común y validar compatibilidad, pues la publicación individual no garantiza atomicidad del conjunto. Registrar en cada salida versión de contrato, configuración, ventanas, diccionarios, reglas, métricas, versión de código disponible, hashes raw y referencias verificables a entradas. El linaje debe detectar entradas regeneradas o incompatibles; la ruta de una tabla o el hash raw por sí solos no prueban su procedencia. No prometer hashes de artefactos hasta implementar y probar el mecanismo.

Las pruebas deben cubrir al menos: agregación sin repetir adjudicaciones, monedas y fechas, exclusiones, IDs nulos, diccionarios estables, conservación de conteos, escalado de dimensiones constantes, KNN sin autoaristas y con desempates, nodos aislados, límites de pares, y publicación ante fallos. Comparar con datos sintéticos pequeños de resultado conocido y conciliar con la corrida real. Ejecutar `pytest` y `ruff check .`; después, ejecutar la ruta documentada localmente y en Docker cuando esté disponible. Dejar constancia de cualquier plataforma o etapa no probada.

## 9. Criterios verificables de cierre de Parte I

- [ ] Enunciado y preguntas conectados con las decisiones y fuentes.
- [ ] Datos aplanados, perfilados, fuentes citadas y linaje de entradas verificable.
- [ ] Identidad abordada: criterios, muestra y cobertura; mapeo sustentado si existe, casos no resueltos y efecto o limitación cuantificada. No afirmar deduplicación total sin evidencia.
- [ ] Vectores exportados en Spark con definiciones, diccionario, ajuste y cobertura.
- [ ] Matriz dispersa exportada en Spark, con diccionarios y reconciliación de conteos.
- [ ] Grafo KNN exportado en Spark con nodos, aristas, reglas, validaciones y métricas de escala.
- [ ] Particionamiento y `explain` documentados con mediciones, condiciones y conclusión.
- [ ] Resultados interpretados y limitaciones comunicadas; no atribuir fraude ni causalidad a una relación.
- [ ] Pruebas, guía de ejecución y corrida integral reproducible registradas, con plataformas no validadas claramente identificadas.
- [ ] Reporte final completado con las cifras reales de cada artefacto y decisión; no dar por válidos valores esperados sin ejecutarlos.

## 10. Formato del reporte final de cierre

Una vez ejecutado el plan, actualizar este documento o enlazar un reporte final que incluya: pregunta y alcance; archivos y hashes; decisiones de grano y ventana; calidad y cobertura; política de identidad y resultados de su revisión; dimensiones y estadísticas de vectores, matriz y grafo; criterios de vecinos y ejemplos interpretados; particionamiento y desempeño observado; pruebas y reproducción; limitaciones y conclusiones. Conservar este avance y las decisiones previas como historial, sin sustituir resultados fallidos por afirmaciones de éxito.

## 11. Situación actual y siguiente paso

**Situación al 25 de octubre de 2026:** transformación, perfil de calidad, tablas anuales y diagnóstico de identidad disponibles para los datos de referencia. Los vectores, la matriz dispersa, el grafo KNN y el estudio del plan Spark siguen pendientes. La revisión de identidad no confirma una deduplicación completa.

**Siguiente paso concreto:** acordar y documentar el corte de adjudicación 2023–2024 y las reglas de identidad; después medir en Spark la cobertura de ese universo y construir los vectores con su diccionario y parámetros. Con esos resultados se prepara la matriz y luego el KNN, siguiendo las puertas de validación anteriores.
