# Guía para exponer el proyecto desde Visual Studio Code

Esta guía sirve para moverte por el proyecto, entender qué hizo cada archivo y explicar el recorrido completo desde los datos originales hasta la Parte III. La exposición muestra los resultados ya calculados y los notebooks que los interpretan. No ejecutes todo el pipeline frente al profesor: puede tardar, requiere Spark y no añade evidencia a los resultados ya verificados.

## Ruta de la exposición

```text
Datos OCDS descargados y verificados
  -> tablas limpias de adjudicaciones
  -> interacciones anuales
  -> vectores, matriz y grafo KNN
  -> clustering descriptivo
  -> cortes temporales de recomendación
  -> popularidad, vecindario, ALS y contenido
```

| Parte | Pregunta | Resultado principal |
| --- | --- | --- |
| I | ¿Cómo convertir releases OCDS en datos analíticos sin alterar el significado de las adjudicaciones? | Tablas, interacciones, vectores, matriz dispersa y grafo KNN. |
| II | ¿Qué perfiles de entidades aparecen por volumen y composición de adjudicaciones? | Cuatro grupos KMeans como síntesis descriptiva; HDBSCAN y Ward como contraste. |
| III | ¿Qué proveedores conocidos podrían aparecer como relaciones nuevas de una entidad conocida? | ALS tuvo el mejor NDCG@10 retrospectivo; vecindario cubrió más proveedores. |

## 0. Preparar Visual Studio Code

1. Abre la carpeta raíz `Proyecto2`.
2. En el explorador, deja visibles `scripts/`, `src/`, `notebooks/`, `data/` y `artifacts/`.
3. Para los notebooks usa el kernel:

   ```text
   .venv312\Scripts\python.exe
   ```

   Es el entorno correcto: Python 3.12.10, PySpark 3.5.6, JupyterLab, pandas, scikit-learn y HDBSCAN. El entorno `.venv` usa Python 3.14 y no tiene las dependencias del proyecto.

4. Abre una terminal PowerShell integrada en la raíz y actívala solo si vas a ejecutar un control:

   ```powershell
   .\.venv312\Scripts\Activate.ps1
   ```

5. Abre estas pestañas en este orden:

   ```text
   scripts/validate_environment.py
   src/processing/build_fact_award_item.py
   src/features/build_part1.py
   notebooks/01_calidad_y_eda.ipynb
   notebooks/02_diagnostico_resolucion_entidades.ipynb
   notebooks/03_particionamiento_spark.ipynb
   src/models/build_clustering.py
   notebooks/04_clustering_y_anomalias.ipynb
   src/features/build_recommendation.py
   notebooks/05_auditoria_recomendacion.ipynb
   src/models/recommendation_als.py
   notebooks/06_recomendacion.ipynb
   notebooks/07_auditoria_contenido.ipynb
   ```

Controles rápidos que puedes ejecutar si ya se probaron antes:

```powershell
python scripts/validate_environment.py
python -m pytest -q
ruff check src tests scripts
```

El primero verifica Python, Java, paquetes e importación de ALS. Las pruebas verifican reglas del código con casos sintéticos. Ruff revisa errores de estilo e imports. La última comprobación registrada aprobó 38 pruebas y Ruff.

## 1. Inicio: los datos y su trazabilidad

### `scripts/download_data.py`

Descarga los archivos JSONL comprimidos del registro OCDS de contrataciones públicas del Perú. Descarga por año, guarda una copia parcial durante el proceso y al final registra URL, fecha, tamaño y SHA-256 en `data/raw/manifest.json`.

**Finalidad:** identificar exactamente la copia de datos usada. Una URL igual no garantiza que una descarga posterior contenga la misma versión.

| Archivo usado | Tamaño | SHA-256 |
| --- | ---: | --- |
| `2023.jsonl.gz` | 53 051 307 bytes | `34a8cd64afee7b8d1cde3f44e30f9101bbd2537add96ccf6db79cca9bafab65a` |
| `2024.jsonl.gz` | 125 638 249 bytes | `9f50c84423c65605b4280d2d88b9da0853ebeb0b556d2dedf66add435cbde6e0` |

El año del archivo indica el año de fuente; no garantiza que una adjudicación ocurriera ese mismo año.

### `scripts/validate_environment.py`

Comprueba Python 3.12, Java 17, PySpark, pandas, PyArrow, scikit-learn y demás dependencias. También intenta importar ALS de PySpark. En Windows revisa los auxiliares locales de Hadoop.

**Resultado:** el entorno de trabajo quedó validado con Python 3.12.10, Java 17.0.20 y PySpark 3.5.6.

## 2. Parte I: crear la base analítica

Los releases OCDS son JSON anidados. Antes de aplicar modelos hay que definir qué significa una fila, evitar duplicar montos y conservar trazabilidad.

### 2.1 Scripts de transformación y features

| Archivo | Qué hace | Resultado publicado | Para qué sirve después |
| --- | --- | --- | --- |
| `src/processing/build_fact_award_item.py` | Lee los JSONL con Spark, aplana releases y extrae proceso, entidad, licitación, adjudicación, proveedor e ítem. | `data/processed/fact_award_item/`; una fila por proceso × adjudicación × proveedor × ítem. | Calidad, textos de ítems y proveedores. |
| `src/quality/profile_fact_award_item.py` | Cuenta nulos, duplicados, claves, categorías, monedas y cobertura. | Artefactos de perfil técnico. | Conocer problemas antes de modelar. |
| `src/processing/build_fact_award.py` | Reduce el detalle a una fila por proceso × adjudicación y rechaza atributos conflictivos. | `data/processed/fact_award/`. | Evita repetir el monto de una adjudicación por cada ítem. |
| `src/processing/build_fact_award_supplier.py` | Relaciona adjudicaciones con proveedores y calcula proveedores por adjudicación. | `data/processed/fact_award_supplier/`. | Base de relaciones entidad-proveedor y recomendación. |
| `src/features/build_interactions.py` | Agrupa por entidad-proveedor-año-moneda y entidad-categoría-año-moneda. | `entity_supplier_year` y `entity_category_year`. | Construcción de vectores, auditorías y análisis temporal. |
| `src/processing/build_identity_evidence.py` | Extrae `parties`, identificadores y referencias de los releases; busca evidencia sin fusionar IDs. | `data/processed/identity_evidence/`. | Diagnóstico de identidad. |
| `src/features/build_part1.py` | Crea diccionarios, matriz dispersa, vectores y grafo KNN desde interacciones 2023-2024. | `data/processed/part1/`. | Base directa del clustering y representación relacional. |

Todos verifican entradas con `_SUCCESS`, guardan metadatos y rechazan sobrescribir salidas sin `--overwrite`. Publican primero en una carpeta temporal para no dejar resultados incompletos.

### 2.2 Qué significa cada tabla

| Tabla | Una fila significa | Razón |
| --- | --- | --- |
| `fact_award_item` | Un ítem de una adjudicación para un proveedor. | Conserva descripción y clasificación del ítem. |
| `fact_award` | Una adjudicación dentro de un proceso. | El monto de adjudicación queda una sola vez. |
| `fact_award_supplier` | Un proveedor participante en una adjudicación. | Representa la relación entidad-proveedor sin duplicar ítems. |

Ejemplo: si una adjudicación de S/ 100 tiene dos ítems, el detalle puede tener dos filas. Sumar el monto allí produciría S/ 200 por error. La tabla de adjudicaciones evita ese doble conteo. Si existen varios proveedores, el proyecto no reparte el monto sin una regla comprobable. Tampoco suma monedas distintas.

### 2.3 Features creados por `src/features/build_part1.py`

Abre este archivo y ubica `build_features`, `build_matrix` y `build_knn`.

- **Features de entidad:** `log1p` del número de adjudicaciones y proporciones de bienes, servicios y obras. `log1p` reduce el peso de volúmenes muy altos.
- **Matriz entidad-proveedor:** cada valor observado es un conteo de adjudicaciones; los ceros no se guardan, por eso es dispersa.
- **Grafo KNN:** conecta cada entidad con cinco entidades de perfil más parecido según distancia euclidiana de los features escalados.

El KNN representa similitud de perfiles; no representa contratos entre entidades ni colusión. El límite de 10 millones de pares protege el costo cuadrático de un KNN exacto.

### 2.4 Notebooks de la Parte I

| Notebook | Qué se hizo | Qué se aprendió | Conclusión |
| --- | --- | --- | --- |
| `notebooks/01_calidad_y_eda.ipynb` | Se exploraron cobertura por archivo, categoría, modalidad, moneda, fechas e interacciones. | Hay fechas y clasificaciones faltantes; los montos requieren conservar moneda y evitar duplicación por ítem. | La base es utilizable si mantiene reglas monetarias y exclusiones explícitas. |
| `notebooks/02_diagnostico_resolucion_entidades.ipynb` | Se revisaron nombres repetidos, IDs con varios nombres, identificadores OCDS y referencias sin coincidencia. | 2 858 nombres normalizados de proveedor tienen varios IDs y 338 IDs tienen varios nombres. | No se deduplican proveedores por nombre; los IDs originales se conservan. |
| `notebooks/03_particionamiento_spark.ipynb` | Se inspeccionaron particiones, plan de Spark, poda por año y tiempos exploratorios. | El filtro por año evita leer particiones ajenas. | La ejecución tiene particionamiento controlado; las pocas mediciones de tiempo no prueban una mejora general. |

### 2.5 Resultados de la Parte I

Los siguientes resultados se obtuvieron de las tablas publicadas por los scripts y se exploraron en los notebooks 01 a 03:

- 137 292 filas de detalle, 119 762 procesos y 128 395 adjudicaciones.
- 62 919 IDs de proveedor y 2 967 IDs de entidad.
- 35 adjudicaciones sin fecha y 18 752 filas de ítem sin clasificación.
- 2 756 vectores de entidad en la ventana descriptiva 2023-2024.
- Matriz dispersa de 2 756 entidades × 39 819 proveedores, con 61 939 pares observados.
- Grafo KNN dirigido de 13 780 aristas, cinco vecinos por entidad.

## 3. Parte II: clustering y anomalías

### `src/models/build_clustering.py`

Este módulo recibe los features de la Parte I, verifica huellas y consistencia de entradas, prepara dos escalas y ejecuta experimentos de clustering. Usa cuatro variables: `log1p` del conteo y tres proporciones de categorías. Las proporciones se estandarizan; también se prueba una variante que reduce el peso conjunto de categorías con `1/sqrt(3)`.

| Técnica | Qué busca | Cómo se aplicó |
| --- | --- | --- |
| KMeans++ | Agrupar entidades alrededor de centros. | Se probaron `k=2` a `k=8`, 20 inicializaciones y semilla 42. |
| Silueta | Medir compactación interna y separación entre grupos. | Ayudó a elegir una solución provisional. |
| HDBSCAN | Encontrar zonas densas y marcar puntos como ruido. | Se variaron `min_cluster_size` y `min_samples`. |
| Ward jerárquico | Mostrar fusiones entre grupos en una muestra manejable. | Se aplicó a 400 entidades estratificadas por volumen. |
| ARI | Medir acuerdo entre dos particiones. | Se compararon escalas, remuestreos y Ward frente a KMeans. |

### `notebooks/04_clustering_y_anomalias.ipynb`

El notebook carga las asignaciones y métricas del script anterior. Sus secciones son: datos de referencia, KMeans++, HDBSCAN, contraste por volumen, Ward, sensibilidad por remuestreo y límites.

**Resultados obtenidos:**

- KMeans++ seleccionó provisionalmente `k=4`, con silueta aproximada **0,359**.
- Un grupo tiene mayor volumen y composición mixta; los otros concentran mayor proporción relativa de obras, servicios o bienes.
- HDBSCAN 15/5 produjo 46 grupos y 48,9 % de ruido en Windows; Docker tuvo 48,7 % de ruido.
- Ward, al cortar en cuatro grupos sobre 400 entidades, tuvo ARI **0,483** frente a KMeans: coincidencia parcial.
- De 29 entidades marcadas por distancia alta en KMeans, 14 también fueron ruido para HDBSCAN.

**Conclusión:** KMeans es una síntesis útil de cuatro perfiles bajo esta configuración. HDBSCAN y Ward muestran que la segmentación cambia con método, parámetros y perfiles repetidos. Los grupos y atípicos describen patrones; no diagnostican irregularidades.

## 4. Parte III: recomendación retrospectiva

En esta parte la pregunta cambia: para una entidad, ¿qué proveedores conocidos, todavía ausentes de su historial, aparecen después como relaciones nuevas?

### `src/features/build_recommendation.py`

Este script crea cortes temporales desde `fact_award_supplier`:

1. Excluye fechas o IDs vacíos para el cálculo temporal.
2. Forma el entrenamiento con adjudicaciones anteriores al corte.
3. Agrupa interacciones entidad-proveedor y calcula `log1p(interaction_count)`.
4. Crea diccionarios de entidades y proveedores solo con entrenamiento.
5. Clasifica pares del período posterior como repetidos, entidad fría, proveedor frío o positivo elegible.

Los candidatos de una entidad son los proveedores conocidos en entrenamiento menos los de su historial. No se materializa el producto cartesiano completo.

### `notebooks/05_auditoria_recomendacion.ipynb`

Este notebook se ejecutó antes de entrenar. Verificó claves, fechas, cobertura, pares nuevos, repetidos y fríos. También revisó `release_date` y `published_date` para no ocultar un problema temporal.

| Corte | Eventos de entrenamiento | Positivos elegibles | Entidades evaluables | Cobertura de pares nuevos |
| --- | ---: | ---: | ---: | ---: |
| Validación 2023 | 46 636 | 9 806 | 1 843 | 31,0 % |
| Prueba 2024 | 88 395 | 10 038 | 1 879 | 37,8 % |

**Qué se aprendió:** la evaluación cubre solo relaciones nuevas entre actores conocidos. Los pares con entidad o proveedor frío quedan fuera del experimento principal.

**Conclusión temporal:** los releases actuales no son snapshots históricos comprobados. Por eso la evaluación es retrospectiva por fecha de adjudicación, no una simulación prospectiva libre de fuga de información.

### Scripts de modelos de recomendación

| Archivo | Técnica aplicada | Qué calcula | Resultado |
| --- | --- | --- | --- |
| `src/models/recommendation_baseline.py` | Popularidad. | Ordena proveedores por número de entidades distintas en entrenamiento y elimina historial. | Baseline y métricas por entidad. |
| `src/models/recommendation_neighbors.py` | Filtrado colaborativo proveedor-proveedor. | Similitud coseno entre proveedores, reducción de poco soporte y 50 vecinos. | Rankings de vecindario calculados por bloques para limitar memoria. |
| `src/models/recommendation_als.py` | ALS implícito de Spark. | Factores latentes de entidades y proveedores con `log1p` del conteo. | Compara 16 y 32 factores en 2023 y congela el mejor por NDCG@10. |
| `src/models/recommendation_test.py` | Prueba retrospectiva. | Reentrena antes de 2024 y aplica la configuración congelada. | Comparación final sin elegir parámetros otra vez. |
| `src/models/recommendation_content.py` | TF-IDF y similitud coseno. | Perfiles textuales de entidades y proveedores a partir de ítems anteriores a 2023. | Evaluación exploratoria de contenido solo en validación 2023. |

`Recall@K` mide cuántos positivos elegibles se recuperan. `Precision@K` mide aciertos entre K posiciones. `NDCG@K` también premia que un acierto aparezca arriba. Ninguna es una probabilidad de contratar ni de idoneidad del proveedor.

### `notebooks/06_recomendacion.ipynb`

Este notebook usa los rankings y métricas publicadas por popularidad, vecindario y ALS. Compara métricas globales, distribución por entidad, segmentos de historial, bootstrap y concentración de proveedores.

| Método, prueba retrospectiva 2024 | Recall@10 | Precision@10 | NDCG@10 | Entidades con ranking | Proveedores distintos a 20 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Popularidad | 0,0303 | 0,0133 | 0,0252 | 1 879 | 29; 0,06 % del catálogo |
| Vecindario | 0,0544 | 0,0276 | 0,0554 | 1 785 | 10 402; 21,87 % |
| ALS | **0,0748** | **0,0340** | **0,0657** | 1 879 | 985; 2,07 % |

**Qué se aprendió:** ALS ordenó mejor los positivos elegibles de 2024. Vecindario cubrió muchos más proveedores, pero no generó lista para 94 entidades. Ningún modelo gana todos los criterios. La mediana de NDCG@10 fue cero para los tres; una media positiva no significa acierto para la mayoría de entidades.

### `notebooks/07_auditoria_contenido.ipynb`

Este notebook primero revisa si había texto útil y luego compara contenido contra los otros métodos en validación 2023. No usa la prueba de 2024 porque esa ventana ya había sido observada antes de formular el experimento textual.

**Técnica aplicada:** TF-IDF con unigramas y bigramas, `min_df=3`, `max_df=0,8` y hasta 30 000 términos. Los perfiles se construyeron con 50 647 descripciones anteriores a 2023. Los ítems futuros no entraron al vocabulario.

| Método, validación 2023 | Recall@10 | NDCG@10 | Cobertura de proveedores a 20 |
| --- | ---: | ---: | ---: |
| Popularidad | 0,0257 | 0,0217 | 0,12 % |
| Vecindario | 0,0232 | 0,0282 | 33,53 % |
| ALS | 0,0555 | 0,0558 | 4,36 % |
| Contenido TF-IDF | 0,0109 | 0,0098 | 44,21 % |

**Conclusión:** el contenido aumentó diversidad de proveedores, pero no superó a popularidad ni ALS en recuperación o NDCG. Textos similares tampoco prueban que dos proveedores sean sustituibles o aptos para contratar.

## 5. Cierre de la exposición

El trabajo completado hasta la Parte III logra:

1. Una base analítica reproducible con grano explícito, controles de calidad, exclusiones y trazabilidad.
2. Un análisis de clustering que describe perfiles de entidades y documenta sensibilidad.
3. Una comparación retrospectiva donde ALS mejora el ranking observado para actores conocidos y vecindario ofrece mayor diversidad.

Límites que se deben mencionar:

- La identidad de entidades y proveedores no está resuelta de manera canónica.
- La fuente no prueba qué información estaba disponible históricamente en cada corte.
- No se evaluó arranque en frío.
- Las listas no deciden contrataciones: no incorporan requisitos legales, precio, capacidad, competencia ni aptitud.
- Aún faltan enlaces, comunidades, embeddings y la web del proyecto integral.

## 6. Preguntas que pueden aparecer

| Pregunta | Respuesta breve y correcta |
| --- | --- |
| ¿Por qué no unieron proveedores por nombre? | Porque un nombre igual no prueba identidad; puede ser un consorcio o una coincidencia. Una fusión errónea alteraría todos los resultados. |
| ¿Por qué no usaron montos en clustering? | Hay monedas distintas y el monto puede repetirse por ítem. Se usó volumen y composición para evitar una comparación monetaria inválida. |
| ¿Por qué usaron Spark? | Para transformar JSONL, publicar Parquet por etapas y controlar grano, particiones y validaciones. |
| ¿KMeans demuestra cuatro tipos reales? | No. Resume la población bajo variables y parámetros definidos. HDBSCAN y Ward mostraron sensibilidad y acuerdo parcial. |
| ¿ALS recomienda a quién contratar? | No. Ordena relaciones retrospectivas entre actores conocidos; no mide elegibilidad, calidad o capacidad. |
| ¿Por qué el texto no ganó? | Logró mayor cobertura, pero recuperó menos positivos que popularidad y ALS. Se informa como hallazgo, sin forzar una mejora. |
| ¿Qué sigue? | Resolver identidad, conseguir snapshots históricos, evaluar actores fríos, confirmar híbrido/ANN y continuar con enlaces, comunidades, embeddings y web. |

## 7. Regla para no perderte en Visual Studio Code

Para cada parte sigue siempre este orden:

```text
Archivo de código -> qué transforma o calcula -> notebook que lo analiza -> resultado -> conclusión y límite
```

Los notebooks siguen esta secuencia: `01` calidad, `02` identidad, `03` Spark, `04` clustering, `05` auditoría temporal, `06` comparación de recomendadores y `07` contenido. Siguiendo esa secuencia presentas el proyecto completo hasta la Parte III sin depender de documentación privada.
