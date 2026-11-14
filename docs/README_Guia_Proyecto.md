# Guía para comprender y sustentar el proyecto: de cero a la Parte III

**Proyecto Integrador 2 · Contrataciones públicas del Perú · Estado: 25 de octubre de 2026**

Esta guía explica qué hicimos, por qué lo hicimos, qué archivos intervienen y qué podemos concluir. Está pensada para estudiar y exponer el trabajo; los contratos detallados y los comandos completos siguen siendo la referencia operativa. Cubre el entorno, la Parte I, la Parte II y la Parte III. Las Partes IV–VII, la web y la entrega integral todavía requieren trabajo.

Para presentar el proyecto directamente en Visual Studio Code, seguir la
[guía de exposición](GUIA_EXPOSICION_VSCODE.md), que transforma este recorrido
en una secuencia de archivos, resultados y explicaciones breves.

## 1. La idea completa en una página

Partimos de datos públicos de contrataciones en el estándar OCDS. Una entidad compradora realiza procesos; en esos procesos hay adjudicaciones, proveedores e ítems. El objetivo es transformar esos registros en una base confiable y responder preguntas sobre perfiles y relaciones observadas.

1. **Preparar y verificar:** fijar versiones, comprobar el entorno, descargar archivos e identificar cada copia con una huella.
2. **Parte I:** convertir JSON anidados en tablas, revisar calidad e identidad y construir vectores, matriz y grafo con Spark.
3. **Parte II:** agrupar entidades por volumen y composición de adjudicaciones, estudiar sensibilidad y perfiles atípicos.
4. **Parte III:** ordenar proveedores conocidos con los que una entidad aún no se relacionó y comprobar retrospectivamente si algunos aparecen después.

El proyecto separa responsabilidades: los módulos de `src/` producen artefactos; `notebooks/` audita, visualiza e interpreta; `tests/` comprueba reglas; `docs/` registra decisiones y reproducción. Los datos y resultados regenerables viven en `data/` y `artifacts/` y no se guardan normalmente en Git.

**Resultado central:** obtuvimos una base analítica, perfiles descriptivos y una comparación de recomendadores. Las cifras describen el conjunto disponible, no un censo ni una prueba de fraude, calidad del proveedor o capacidad de anticipar decisiones reales.

## 2. Conceptos básicos antes de empezar

- **OCDS y release:** OCDS es un estándar para publicar datos de contratación. Un release describe información de un proceso en una versión publicada; una fecha de adjudicación y la fecha de publicación son conceptos distintos.
- **Grano:** qué representa exactamente una fila. Por ejemplo, una adjudicación con dos ítems puede producir dos filas de detalle, aunque solo exista una adjudicación.
- **Clave:** campos que identifican una observación. Para una adjudicación usamos `process_ocid + award_id`; un `award_id` aislado no se asume único entre procesos.
- **JSONL.GZ:** JSON Lines, un registro JSON por línea, comprimido. **Parquet** almacena datos en columnas y permite leer únicamente los campos necesarios.
- **Spark / PySpark:** motor de procesamiento distribuido y su interfaz de Python. En este proyecto también puede ejecutarse localmente con varios hilos; usar Spark no implica que existiera un clúster remoto.
- **Matriz dispersa:** representación que guarda las relaciones observadas sin almacenar todos los ceros posibles. **Grafo:** nodos y aristas; su interpretación depende de cómo se definan las aristas.
- **Huellas SHA-256:** resúmenes criptográficos para reconocer cambios en archivos. Comparar con el manifiesto verifica la copia respecto a ese manifiesto; no demuestra por sí solo cuándo fue publicada cada versión.
- **`_SUCCESS`:** marcador de una publicación terminada. **`_metadata.json`:** registra parámetros, conteos, huellas y linaje inmediato según el artefacto. Ninguno sustituye una auditoría completa.

### Un ejemplo de por qué importa el grano

Supongamos una adjudicación de S/ 100 con dos ítems. Si cada fila de ítem repite S/ 100 y sumamos ambas, obtenemos S/ 200, un doble conteo. Por eso construimos `fact_award` con una fila por adjudicación antes de resumir montos. Si una adjudicación tiene varios proveedores, tampoco repartimos el monto sin una regla respaldada. Las sumas se hacen por moneda; no suponemos un tipo de cambio.

## 3. Fuente, alcance y reproducibilidad

La fuente es [OCDS - Contrataciones públicas del Perú, OECE/OSCE](https://data.open-contracting.org/es/publication/135), señalada en el proyecto con licencia CC BY 4.0. Usamos los archivos de **fuente 2023 y 2024**. El año del archivo indica de qué archivo procede un registro; no garantiza que la adjudicación haya ocurrido ese mismo año.

Las copias usadas se identifican en `data/raw/manifest.json`:

| Archivo | Tamaño en bytes | SHA-256 |
| --- | ---: | --- |
| 2023.jsonl.gz | 53 051 307 | `34a8cd64afee7b8d1cde3f44e30f9101bbd2537add96ccf6db79cca9bafab65a` |
| 2024.jsonl.gz | 125 638 249 | `9f50c84423c65605b4280d2d88b9da0853ebeb0b556d2dedf66add435cbde6e0` |

Una descarga futura de la misma URL puede no entregar la misma versión. Para repetir exactamente el experimento se necesitan las mismas copias verificadas, además del código y entorno. El manifiesto generado al descargar identifica lo descargado; debe compararse con las huellas de referencia, no basta con comprobar que el nuevo manifiesto coincide consigo mismo.

### Entorno y decisiones

- `Dockerfile` fija Python 3.12.10, Java 17 e instala las versiones de `requirements.txt`; `docker-compose.yml` monta la carpeta del proyecto en `/workspace`. Esto facilita repetir la ejecución en un entorno controlado.
- `scripts/validate_environment.py` comprueba Python, Java, paquetes y la importación real de ALS de PySpark. `setuptools` se fijó después de detectar que faltaba `distutils` en la imagen con Python 3.12.
- `scripts/setup_windows_hadoop.py` prepara y verifica los auxiliares de Hadoop para ejecución local en Windows. Docker es la ruta recomendada; no necesita esos auxiliares del host.
- `scripts/download_data.py --years 2023 2024` descarga, registra URL, fecha, tamaño y SHA-256 y usa un archivo parcial durante la descarga.
- `pyproject.toml` configura Python, pruebas y Ruff. `tests/` contiene comprobaciones sintéticas de reglas importantes. En la última revisión registrada pasaron **38 pruebas** y Ruff.

La [guía de comandos](ComandosEjecutarOrdenReplica.md) explica Docker, Windows, Linux/macOS, recuperación y controles. Evita ejecutar `--overwrite` sin revisar la salida que reemplazará. Al cambiar una entrada hay que regenerar también sus productos dependientes.

### Qué comprobamos con Docker y qué no

Tras un error de arranque de Docker Desktop, el motor volvió a responder y se corrigió una dependencia de ALS. Con la misma imagen corregida se reconstruyó en una carpeta aislada la **cadena directa de recomendación**: raw → ítems → adjudicaciones → proveedores → cortes → modelos. La etapa de proveedores se retomó en otro contenedor tras corregir un argumento; se conservó la misma imagen. Se compararon tablas, cortes, métricas y rankings con la referencia, con tolerancia numérica `1e-12`.

La prueba incluyó 110 620 filas de rankings de 2024 y 36 836 del modelo de contenido. Los raw se verificaron antes y después. No se exige identidad binaria de los Parquet. Esta comprobación **no** demuestra que todas las etapas de las Partes I y II se hayan repetido desde descarga en la misma corrida ni que otra computadora haya reproducido todo el proyecto.

## 4. Parte I: de registros anidados a una base analítica

**Pregunta:** ¿cómo representar procesos, adjudicaciones, proveedores e ítems sin perder el grano ni duplicar montos, y cómo construir los objetos necesarios para los modelos?

```text
raw JSONL.GZ + manifiesto
    -> fact_award_item -> fact_award -> fact_award_supplier
    -> interacciones anuales -> vectores + matriz + grafo KNN
    -> clustering descriptivo
fact_award_supplier -> cortes propios de entrenamiento y prueba -> recomendación
raw + fact_award_supplier -> evidencia de identidad
```

### 4.1 Tablas oficiales y por qué existen

| Módulo | Resultado y grano | Razón de la decisión |
| --- | --- | --- |
| `src.processing.build_fact_award_item` | `fact_award_item`: proceso × adjudicación × proveedor × ítem. | Conserva el detalle que permite estudiar categorías y texto. |
| `src.quality.profile_fact_award_item` | Perfil técnico de calidad. | Cuantifica cobertura, claves, nulos y monedas antes de modelar. |
| `src.processing.build_fact_award` | `fact_award`: proceso × adjudicación. | Evita multiplicar el monto por los ítems; rechaza conflictos de nivel adjudicación. |
| `src.processing.build_fact_award_supplier` | `fact_award_supplier`: proceso × adjudicación × proveedor. | Representa relaciones y separa el monto total del monto asignable a proveedor único. |
| `src.features.build_interactions` | `entity_supplier_year` y `entity_category_year`, con año y moneda. | Resume interacciones de manera auditable sin mezclar monedas. |
| `src.processing.build_identity_evidence` | Evidencia de identificadores y referencias OCDS. | Investiga posibles problemas de identidad sin fusionar automáticamente IDs. |
| `src.features.build_part1` | Vectores, diccionarios, matriz y grafo KNN. | Publica las representaciones compartidas por los análisis posteriores. |

Los nombres completos son módulos invocados con `python -m`, no comandos que deban ejecutarse en cualquier orden. Cada uno tiene entradas, reglas y salidas definidas en el [contrato de datos](ContratoDatos.md). En general rechazan una salida existente salvo que se solicite `--overwrite`; revisar sus opciones particulares con `--help`.

### 4.2 Calidad y decisiones concretas

La referencia tiene **137 292 filas de detalle**, **119 762 procesos**, **128 395 adjudicaciones**, **62 919 IDs de proveedor** y **2 967 IDs de entidad**. Hay **35 fechas de adjudicación ausentes** y **18 752 filas de ítem sin clasificación**. Las filas sin fecha permanecen en las tablas base, pero se excluyen de interacciones anuales y se cuantifican.

Las tablas anuales agrupan por entidad, proveedor o categoría, año de adjudicación y moneda; tienen 128 360 registros elegibles agregados como conteo en cada fuente. La ventana descriptiva por fecha de adjudicación **2023–2024** contiene 81 724 adjudicaciones elegibles; otras 46 636 elegibles de los archivos tienen fechas fuera de esa ventana. Por eso no debe confundirse el año de fuente con el año del evento.

### 4.3 Identidad: qué sí y qué no resolvimos

Detectamos **2 858 nombres normalizados de proveedor con varios IDs** y **338 IDs con varios nombres**. En 128 340 referencias contextuales de proveedores, 32 no tuvieron `party.id` coincidente en el mismo release. Una revisión intencional de diez nombres frecuentes reunió 723 IDs de consorcios. Un mismo nombre no demuestra que dos registros sean la misma organización: puede ser un consorcio o una coincidencia. Decidimos conservar los IDs originales y documentar la posible fragmentación; **no existe un mapeo canónico validado**.

### 4.4 Vectores, matriz y grafo

- **Vectores:** 2 756 entidades; cada vector usa `log1p` del conteo de adjudicaciones y proporciones de bienes, servicios y obras. `log1p(x) = log(1+x)` reduce el dominio de valores grandes sin borrar el orden del conteo.
- **Matriz:** 2 756 entidades × 39 819 proveedores, con 61 939 pares observados y 81 724 adjudicaciones sumadas; densidad aproximada 0,0564 %. Es una matriz de interacciones, no de calificaciones.
- **Diccionarios:** convierten IDs a índices reproducibles dentro de una misma publicación; se guardan junto a la matriz.
- **Grafo KNN:** 2 756 entidades y 13 780 aristas dirigidas, cinco vecinos por entidad, según distancia euclidiana de los cuatro atributos escalados. Sus aristas representan **similitud de perfiles**, no contratos entre entidades. Se excluyen autoaristas y se desempata por ID. El límite de 10 millones de pares protege frente a su costo cuadrático; el conjunto consideró 7 592 780 pares dirigidos posibles.

Los vectores de esta Parte I usan toda la ventana descriptiva; para una evaluación temporal hay que volver a construir y ajustar solo con entrenamiento. En el notebook 03 se compararon cuatro y ocho particiones de shuffle y se verificó la poda de particiones por año. Con solo dos mediciones y carga concurrente, las diferencias de tiempo no prueban una mejora general.

## 5. Los notebooks: qué aporta cada uno

Un notebook mezcla texto, código, tablas y gráficos para investigar y explicar. No es el lugar donde se publican las tablas oficiales de este proyecto. Deben abrirse después de generar sus entradas; si cambian las huellas, algunos exigen regenerar los artefactos.

| Notebook | Pregunta y tarea |
| --- | --- |
| `01_calidad_y_eda.ipynb` | ¿Qué cobertura, nulos, categorías, monedas y reglas monetarias muestran los datos? |
| `02_diagnostico_resolucion_entidades.ipynb` | ¿Dónde hay candidatos de identidad y evidencia insuficiente para fusionar IDs? |
| `03_particionamiento_spark.ipynb` | ¿Cómo filtra y distribuye Spark los datos por año? Inspecciona planes y tiempos exploratorios. |
| `04_clustering_y_anomalias.ipynb` | ¿Qué perfiles aparecen? Interpreta KMeans, HDBSCAN, Ward, sensibilidad y casos atípicos. |
| `05_auditoria_recomendacion.ipynb` | ¿Son consistentes las claves, fechas y cortes? Cuantifica pares nuevos, fríos y disponibilidad. |
| `06_recomendacion.ipynb` | ¿Cómo se comparan ranking y cobertura? Examina segmentos, distribución y bootstrap. |
| `07_auditoria_contenido.ipynb` | ¿Hay texto útil? Revisa casos y compara el prototipo textual en validación. |

Desde el entorno instalado se puede iniciar `python -m jupyter lab` y abrir la carpeta `notebooks/`. El nombre y alcance de cada salida, así como la interpretación, están en los README de cada parte.

## 6. Parte II: agrupación de entidades y anomalías

**Pregunta:** ¿qué perfiles de entidades aparecen según el volumen y la composición de adjudicaciones observadas de 2023–2024? Son **2 756 entidades** y **81 724 adjudicaciones**. No usamos montos ni concluimos desempeño, gasto real o riesgo.

`src.models.build_clustering` verifica huellas y consistencia de entradas. Construye cuatro variables: `log1p` del conteo y tres proporciones de categorías. Se estandarizan y se comparan dos escalas; en la variante elegida provisionalmente las proporciones reciben el factor `1/sqrt(3)` para moderar el peso conjunto del bloque. La elección afecta el resultado. Se fijó semilla 42; se imponen límites de lectura que no equivalen al pico de memoria del algoritmo.

### 6.1 KMeans++

KMeans busca centros de grupos y asigna cada entidad al centro cercano; KMeans++ es una estrategia de inicialización. Se probaron `k=2..8`, `n_init=20` y una regla de tamaño mínimo de grupo. Se eligió **k=4** por la mayor silueta de la variante ponderada bajo esa regla; silueta aproximada **0,359**. La silueta compara cercanía al propio grupo y separación de otros: valores más altos indican mejor separación según la distancia elegida, no verdad del grupo.

Los grupos tienen medianas de 41, 5, 6 y 6 adjudicaciones: uno combina mayor volumen y categorías; los demás muestran más peso de obras, servicios o bienes. Los números de las etiquetas son arbitrarios. Con cinco remuestreos del 80 %, el ARI frente a la corrida completa fue aproximadamente 0,936–0,992 en IDs compartidos, **con el escalado fijado sobre todos los datos**. Es estabilidad condicional, no una validación temporal.

### 6.2 HDBSCAN y jerárquico

HDBSCAN busca concentraciones de puntos y puede dejar algunos como ruido. Se probaron tamaños mínimos 15, 30, 60 y `min_samples` 5 o 10, en ambas escalas. La regla provisional seleccionó **15/5**, con **46 grupos y 48,9 % de ruido** en Windows; Docker produjo 48,7 % de ruido. Su silueta aproximada 0,660 excluye ruido y **no es directamente comparable** con la de KMeans sobre toda la población.

Hay 1 421 vectores distintos para 2 756 entidades. Veintiún grupos HDBSCAN contienen un único vector distinto y reúnen 641 entidades; los perfiles repetidos pueden crear densidades artificiales. Con otra configuración, 60/5, hubo cuatro grupos y 8,7 % de ruido. La sensibilidad respalda mantener HDBSCAN como exploratorio y no adoptar sus 46 grupos como tipología definitiva.

Ward construye jerárquicamente grupos minimizando incrementos de variación. El notebook lo aplicó con distancia euclidiana a una muestra equilibrada de **400 entidades** y comparó un corte en cuatro grupos con KMeans: **ARI 0,483**, coincidencia parcial. El ARI mide acuerdo entre particiones, no calidad de la segmentación. La muestra equilibrada sirve para comparar volúmenes, no para estimar proporciones poblacionales.

### 6.3 Atípicos y conclusión

Se marcaron para inspección las mayores distancias del 1 % en grupos KMeans grandes y el ruido de HDBSCAN. De 29 señales KMeans, 14 coincidieron con ruido HDBSCAN. Son perfiles atípicos bajo esas variables y parámetros, **no indicios demostrados de fraude**. La conclusión útil es que volumen y composición describen perfiles, pero la partición depende del método, las variables, la escala y la fuente.

## 7. Parte III: recomendación de relaciones nuevas

**Pregunta:** entre proveedores ya observados en entrenamiento con los que una entidad aún no tiene relación, ¿podemos ordenar candidatos y recuperar algunos que aparecen en adjudicaciones posteriores del conjunto disponible?

La relación observada es una señal implícita: contamos adjudicaciones por par entidad–proveedor y usamos `log1p(conteo)`. No es una opinión, un rating ni una decisión de compra recomendada. Los no observados durante la ventana no son negativos confirmados.

### 7.1 Cortes y candidatos

`src.features.build_recommendation` separa entrenamiento por fecha de adjudicación, crea diccionarios propios de cada corte, matriz dispersa y pares futuros clasificados. En cada caso los candidatos son proveedores conocidos en entrenamiento, excluidos los que ya figuran en el historial de la entidad. Un positivo elegible es un par nuevo observado después con entidad y proveedor conocidos. Pares repetidos y actores fríos se reportan aparte.

| Ventana | Entrenamiento | Positivos observados | Pares nuevos evaluables | Entidades evaluables | Cobertura de pares nuevos |
| --- | --- | --- | ---: | ---: | ---: |
| Validación | Antes de 2023 | Durante 2023 | 9 806 | 1 843 | 31,0 % |
| Prueba retrospectiva | Antes de 2024 | Durante 2024 | 10 038 | 1 879 | 37,8 % |

Los archivos de fuente son solo los de 2023 y 2024; el entrenamiento anterior a 2023 se reconstruyó a partir de ellos, no de todo el histórico. La mayoría de pares nuevos queda fuera por actores no conocidos en entrenamiento. Por ejemplo, en 2024 hubo 16 472 pares nuevos con proveedor frío; los indicadores de proveedor y entidad fríos se solapan y no deben sumarse.

### 7.2 La advertencia temporal esencial

El corte usa fecha de adjudicación, pero los releases actuales no son snapshots verificados de lo que se sabía al corte. En el entrenamiento de 2023, las 46 636 filas registran `release_date` y `published_date` desde el corte en adelante; en 2024 sucede para 51 473 de 88 395. Cada campo se cuenta por separado. Una fecha anterior tampoco prueba qué versión se conocía entonces. Por eso llamamos al análisis **retrospectivo** y no afirmamos ausencia de fuga por disponibilidad.

### 7.3 Técnicas y módulos

| Módulo | Idea y decisión |
| --- | --- |
| `src.models.recommendation_baseline` | Popularidad de proveedores según número de entidades distintas de entrenamiento. Es una referencia simple con la que deben compararse los modelos. |
| `src.models.recommendation_neighbors` | Similitud coseno proveedor–proveedor sobre interacciones: proveedores vinculados con entidades parecidas reciben puntuación. Usa 50 vecinos y reducción de similitud con factor de soporte `n/(n+20)`; se calcula por bloques para limitar memoria. Similitud no demuestra que los productos sean sustitutos. |
| `src.models.recommendation_als` | Factorización latente con ALS implícito de Spark: aprende vectores de entidades y proveedores a partir de interacciones. En validación se compararon 16 y 32 factores; se seleccionaron 16 por NDCG@10. Parámetros: regularización 0,1, alpha 10, 10 iteraciones y semilla 42. |
| `src.models.recommendation_test` | Reentrena con datos anteriores a 2024 y aplica la configuración congelada; compara modelos en la misma población y candidatos. |
| `src.models.recommendation_content` | TF-IDF de descripciones de ítems y similitud coseno; vocabulario y perfiles se ajustan solo con entrenamiento anterior a 2023. Explora contenido en validación, sin atribuir aptitud ni equivalencia. |

TF-IDF pondera términos según su frecuencia y lo extendidos que estén entre documentos. Se usaron unigramas y bigramas, `min_df=3`, `max_df=0,8` y hasta 30 000 términos. El contenido se planteó después de observar la prueba de 2024: esa ventana no sería una nueva prueba independiente para este método.

### 7.4 Cómo entender las métricas

Para una entidad con cuatro proveedores positivos elegibles, si dos aparecen en el top 10, **Recall@10 = 2/4 = 0,5**. Si hay al menos diez candidatos, **Precision@10 = 2/10 = 0,2**. Las posiciones no entregadas cuentan como cero. **NDCG@10** también valora el orden: premia más un positivo en una posición temprana que en una tardía y divide por el orden ideal. Estas métricas se calculan por entidad y luego se promedian; no son probabilidades de que un proveedor sea adecuado.

Además se informa cobertura: entidades con ranking y proporción de proveedores distintos recomendados respecto al catálogo entrenado. Una buena media de ranking puede coexistir con concentración en pocos proveedores o listas vacías.

### 7.5 Resultado congelado para 2024

| Método | Recall@10 | Precision@10 | NDCG@10 | Entidades con ranking | Proveedores distintos en top 20 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Popularidad | 0,0303 | 0,0133 | 0,0252 | 1 879 | 29; 0,06 % del catálogo |
| Vecindario | 0,0544 | 0,0276 | 0,0554 | 1 785 | 10 402; 21,87 % |
| ALS | 0,0748 | 0,0340 | 0,0657 | 1 879 | 985; 2,07 % |

ALS fue mejor en las métricas de ranking observadas, pero vecindario cubrió más proveedores y dejó sin ranking a 94 entidades. La mediana de NDCG@10 fue cero en los tres métodos. Un bootstrap pareado de 1 000 remuestreos por entidad estimó la diferencia ALS–vecindario en 0,0103, intervalo aproximado [0,0035; 0,0172]; no corrige dependencia entre entidades ni los sesgos de identidad, fuente o disponibilidad.

### 7.6 Resultado del contenido y decisiones

En validación 2023, el contenido obtuvo NDCG@10 **0,0098** y cobertura de proveedores **44,21 %**; popularidad logró **0,0217** y ALS **0,0558**. La variante textual da mayor cobertura, pero no superó el baseline de popularidad y no se adoptó como principal. No comparar esas cifras de 2023 directamente con resultados de 2024 como si fueran la misma prueba. Una evaluación independiente del contenido requiere otra ventana adecuada y disponibilidad histórica verificable.

La Parte III cumple el análisis planteado para actores conocidos, con sus límites. El enunciado principal pide al menos dos enfoques y presenta híbrido/ANN como posibilidades; la rúbrica los menciona de forma más estricta. No se implementó híbrido ni ANN: conviene confirmar su obligatoriedad antes de afirmar cumplimiento integral de ese criterio.

## 8. Orden práctico de réplica y verificación

La lista siguiente muestra la **dependencia lógica**, no sustituye las opciones completas de la guía. Desde la raíz, todos los módulos se ejecutan con el Python del entorno apropiado o dentro del servicio `pipeline` de Docker:

```text
scripts/validate_environment.py
scripts/download_data.py --years 2023 2024
src.processing.build_fact_award_item --years 2023 2024
src.quality.profile_fact_award_item
src.processing.build_fact_award
src.processing.build_fact_award_supplier
src.features.build_interactions
src.processing.build_identity_evidence --years 2023 2024
src.features.build_part1
src.models.build_clustering
src.features.build_recommendation
src.models.recommendation_baseline
src.models.recommendation_neighbors
src.models.recommendation_als
src.models.recommendation_test
src.models.recommendation_content
```

En Docker, por ejemplo, `docker compose run --rm pipeline python -m src.processing.build_fact_award --help` muestra las opciones del módulo. Para un procedimiento con rutas aisladas de la Parte III, validación del manifiesto y comandos completos, usar [ComandosEjecutarOrdenReplica.md](ComandosEjecutarOrdenReplica.md). Antes de cada etapa revisar que su entrada tenga `_SUCCESS`; después revisar código de salida, marcador, metadatos y conteos. No cambiar parámetros a partir de la prueba de 2024 y presentarla después como prueba independiente.

Las pruebas se ejecutan con `python -m pytest -q` y el control de estilo con `ruff check src tests scripts`. Una prueba sintética valida un comportamiento concreto; no verifica por sí sola la calidad de toda la fuente ni el significado causal de los resultados.

## 9. Cómo defender las decisiones en una exposición

1. **¿Por qué estos datos?** Son abiertos y relacionales: permiten construir perfiles de entidades y relaciones con proveedores. Se cita OECE/OSCE y CC BY 4.0; no se afirma cobertura censal.
2. **¿Por qué separar tablas?** El grano de ítem es útil para texto, pero repite montos y adjudicaciones. Cada tabla representa una unidad adecuada y evita sumar cantidades duplicadas.
3. **¿Por qué no fusionar IDs por nombre?** La coincidencia es solo evidencia preliminar; fusionar consorcios o entidades diferentes alteraría todos los análisis posteriores.
4. **¿Por qué KMeans y HDBSCAN?** Son perspectivas distintas: centros frente a densidad y ruido. La sensibilidad y los vectores idénticos muestran que no hay una única segmentación garantizada.
5. **¿Por qué un baseline?** Permite saber si un método más elaborado aporta sobre recomendar proveedores populares de entrenamiento.
6. **¿Por qué ALS ganó, pero no es una recomendación de compra?** Mejoró NDCG y recall en actores conocidos de una evaluación retrospectiva; no evaluamos aptitud, historial disponible realmente al corte ni actores fríos.
7. **¿Por qué el contenido no es el ganador?** Dio cobertura más amplia en 2023, pero un NDCG menor al baseline. Es información útil incluso cuando una hipótesis no mejora el indicador.
8. **¿Qué falta?** Validar identidad y disponibilidad histórica, estudiar arranque en frío y confirmar la rúbrica. Después quedan enlaces, comunidades, embeddings, síntesis, web y entrega integral.

## 10. Fuentes internas y lectura recomendada

- [Contrato de datos](ContratoDatos.md): granos, campos, exclusiones y publicación.
- [Guía de comandos y solución de problemas](ComandosEjecutarOrdenReplica.md): instrucciones operativas por plataforma.
- [Parte I](README_ParteI.md): transformación, identidad, representaciones y particionamiento.
- [Parte II](README_ParteII.md): metodología, sensibilidad e interpretación del clustering.
- [Plan de recomendación](PlanParteIIIRecomendacion.md) y [resultados de la Parte III](README_ParteIII.md): protocolo, auditoría, métricas y límites.
- [Bitácora estratégica](README_Estrategico.md): decisiones históricas; sus entradas previas describen el estado al momento de redactarlas y deben leerse junto con las actualizaciones posteriores.
- [Enunciado](Proyecto2Integrador.md): objetivos y rúbrica de la asignatura.

Los resultados aquí descritos corresponden a la referencia registrada hasta el 25 de octubre de 2026. Si cambian datos, código, parámetros o población, hay que volver a ejecutar los controles y actualizar las conclusiones.
