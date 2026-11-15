# Competencia en las compras públicas del Perú

**Proyecto Integrador 2 · Minería de Datos · UTEC 2026-2**

Grafos, clustering, recomendación y aprendizaje de representaciones sobre las adjudicaciones
públicas de 2023 y 2024 que OECE publica en el estándar OCDS.

**Equipo:** Ronaldo Dylan Flores Soto, Rodo Vilcarromero e Isaac Vera Romero. Los aportes de
cada integrante están en [Equipo y contribuciones](#equipo-y-contribuciones).

## Preguntas

**P1. Concentración y participación.** Dentro de un mismo rubro y modalidad, ¿los compradores
que concentran sus adjudicaciones en pocos proveedores reciben menos participantes? ¿La
asociación se mantiene al comparar compradores del mismo departamento y tamaño?

**P2. Mercados cerrados.** ¿La red de co-participación se separa por rubro o territorio más de
lo que explican el tamaño de los procesos y la recurrencia de los participantes? ¿Los
compradores cuyos procesos atraen a una sola comunidad son los más concentrados?

El planteamiento y la medición previa de la fuente están en
[docs/ReplanteamientoPreguntas.md](docs/ReplanteamientoPreguntas.md).

## Resultados

Todo es asociativo y descriptivo: ningún resultado prueba competencia efectiva ni
irregularidad. El detalle, con sus límites, está en el reporte interactivo y en los notebooks
08 y 09.

| Tema | Resultado |
|---|---|
| P1 | La asociación bruta entre concentración (HHI) y participantes es −0,228. Después de centrar en el estrato (departamento, rubro, modalidad y tamaño) no se detecta asociación monotónica: Spearman −0,050, IC 95 % [−0,137; 0,063]. |
| P2 | En Puno, Louvain alcanza Q = 0,612 frente a [0,078; 0,080] en un nulo Curveball que conserva tamaños de proceso y recurrencia. Las comunidades siguen al rubro (AMI 0,52) más que a la provincia (0,11). |
| P1 y P2 | La asociación entre cierre de mercado y concentración también aparece cuando el ganador se sortea entre los mismos participantes. El 68 % de los mercados concentra por encima de esa referencia, y ese exceso no se asocia con el cierre. |
| Perfiles (II) | KMeans++ con k = 5 (silueta 0,343) separa perfiles de compra; los atípicos son el 2 % más alejado del centroide de su perfil. |
| Recomendación (III) | En validación 2023, ALS logra NDCG@10 de 0,056 y el híbrido ALS + TF-IDF 0,040. Los sustitutos por segmento aparecen en un mismo proceso futuro el 46 % de las veces, frente al 14 % al azar. |
| Enlaces (IV) | PageRank casi repite la fuerza de los nodos. HITS depende del peso: con conteos, un solo proveedor concentra el 83,8 % de la autoridad; con log1p, el 4,2 %. |
| Comunidades (V) | Louvain, espectral y Girvan-Newman sobre Puno. Con BigCLAM, el 50,3 % de los participantes queda en dos o más comunidades, según el umbral de pertenencia. |
| Representación (VI) | El SVD de participación con t-SNE ordena a los compradores por territorio (AMI 0,51 con el departamento) y en parte por comunidad (0,29). Perfiles y comunidades coinciden poco (NMI 0,232). |
| Validación OECE | En los 74 052 procesos cruzados con el Listado de ofertantes, el 29,7 % de las participaciones reportadas en OCDS (proceso × participante) corresponde a una oferta, y el 99,6 % de las ofertas está en la lista OCDS: la lista OCDS es mucho más amplia que la de ofertantes. Repetidos con ofertantes, P1 centrado da 0,030 [−0,084; 0,122] y Puno Q = 0,716 frente a [0,136; 0,142] en su nulo. |

Las cifras de referencia están congeladas en [scripts/cifras_entrega.json](scripts/cifras_entrega.json)
y se comprueban con `python scripts/verify_delivery_consistency.py`.

## Datos

| Fuente | Uso | Licencia |
|---|---|---|
| [Registro OCDS de Perú](https://data.open-contracting.org/es/publication/135) (OECE/OSCE), archivos 2023 y 2024 | Procesos, compradores, participantes, adjudicaciones e ítems | CC BY 4.0 |
| [Listado de ofertantes](https://www.datosabiertos.gob.pe/dataset/listado-de-ofertantes-%E2%80%93-organismo-especializado-para-las-contrataciones-p%C3%BAblicas-eficientes) (OECE, CONOSCE), convocatorias 2021 a 2024 | Validación de los participantes reportados | ODC-By |

Se analizan las adjudicaciones con fecha en 2023 y 2024. Los datos no se versionan: los
descargadores guardan URL, fecha y SHA-256 de cada archivo en un manifiesto dentro de
`data/raw/`.

## Cómo reproducir

Requisitos: Python 3.12, Java 17 y las dependencias de `requirements.txt`.

```bash
conda create -n py312-spark35 python=3.12 openjdk=17 -c conda-forge
conda activate py312-spark35
pip install -r requirements.txt

python scripts/download_data.py --years 2023 2024
python -m scripts.download_oece
bash scripts/run_pipeline.sh
```

`run_pipeline.sh` ejecuta todas las etapas en orden; también acepta etapas sueltas, por ejemplo
`bash scripts/run_pipeline.sh p1 p2`. Las tablas quedan en `data/processed/` y los resultados en
`artifacts/`, ninguno versionado.

| Etapa | Produce |
|---|---|
| `base` | Tablas de adjudicación por ítem, adjudicación y proveedor; perfil de calidad; interacciones anuales |
| `parte1` | Vectores, matriz dispersa y grafo KNN de la Parte I |
| `clustering` | Clustering inicial de entidades |
| `participacion` | Procesos, participantes reportados y dimensión de compradores |
| `recomendacion` | Cortes temporales, popularidad, vecindario, ALS, TF-IDF, híbrido y sustitutos |
| `p1` | Unidad comprador × segmento × modalidad y análisis de P1 |
| `p2` | Grafos de P2, HITS, PageRank, Louvain, sensibilidad al orden y nulo Curveball |
| `perfiles` | Perfiles de comprador, clustering y atípicos |
| `comunidades` | Particiones en Puno, BigCLAM y cierre comunitario frente a concentración |
| `representacion` | SVD, convergencia y t-SNE |
| `oece` | Validación con el Listado de ofertantes y P1 y P2 repetidos con ofertantes |
| `web` | JSON del reporte interactivo en `artifacts/web_data/` |

Para comprobar el resultado:

```bash
pytest -q
python scripts/verify_delivery_consistency.py
```

Las rutas para Docker y Windows están en
[docs/ComandosEjecutarOrdenReplica.md](docs/ComandosEjecutarOrdenReplica.md).

## Dónde corre cada etapa

Spark se usa donde se leen los raw o se generan pares a escala nacional. El resto corre en local
porque trabaja sobre tablas agregadas o subgrafos que caben en memoria, o porque el algoritmo no
existe en Spark. Cada módulo lo indica en su cabecera.

| Etapa | Módulos | Motor | Motivo |
|---|---|---|---|
| Tablas base | `src/processing/*`, `profile_fact_award_item`, `build_interactions` | Spark | Leen los raw OCDS (171 MB comprimidos, 928 mil participaciones) |
| Diagnóstico de P2 | `profile_market_p2` | Spark y local | Spark mide escala y grados; los componentes salen de un Union-Find local por lotes |
| Parte I y cortes | `build_part1`, `build_recommendation` | Spark | Matriz, KNN y cortes sobre todas las adjudicaciones |
| Mercados P1 y P2 | `build_market_p1`, `build_market_p2`, `build_buyer_profiles` | Spark | La co-participación nacional genera 3,6 millones de pares |
| Análisis P1 y cierre | `analyze_market_p1`, `link_closure_p1` | Local | Tabla agregada de unas 20 mil filas; bootstrap y nulo en memoria |
| Enlaces P2 | `analyze_links_p2`, `hits_sensitivity_p2` | Local (scipy) | Grafos como matrices dispersas que caben en memoria |
| Comunidades P2 | `detect_communities_p2`, `louvain_order_p2`, `null_communities_p2`, `partition_subgraph_p2`, `bigclam_p2` | Local (networkx, numpy) | Louvain no existe en Spark; Girvan-Newman y espectral exacto solo son viables en Puno |
| Perfiles y atípicos | `build_clustering`, `cluster_buyer_profiles`, `profile_outliers` | Local (scikit-learn, hdbscan) | HDBSCAN y Ward no existen en Spark ML; 2 756 compradores |
| Representación | `build_svd_p2`, `build_convergence_p2`, `embed_visualization_p2` | Local (scikit-learn) | Matriz de 2 756 filas; t-SNE no existe en Spark ML |
| Recomendación ALS | `recommendation_als`, `recommendation_test` | Spark | ALS implícito de Spark ML |
| Otras recomendaciones | `recommendation_baseline`, `recommendation_neighbors`, `recommendation_content`, `recommendation_hybrid`, `recommendation_substitutes` | Local | Unas 40 mil relaciones de entrenamiento |
| Validación OECE | `validate_tenderers_oece` | Local (pandas) | Cruce por proceso de unas 850 mil filas de ofertantes |
| Exportación web | `src/web/export_web_data` | Local | Lee artefactos pequeños |

## Estructura

```text
scripts/            descargas, pipeline, verificación de la entrega y exploración inicial
src/processing/     tablas base desde los raw OCDS (Spark)
src/quality/        perfiles de calidad y validación con OECE
src/features/       tablas analíticas de las Partes I a III, P1 y P2 (Spark)
src/models/         análisis, clustering, recomendación, enlaces, comunidades y representación
src/web/            exportación de datos para el reporte interactivo
notebooks/          lectura e interpretación de los resultados, del 01 al 09
tests/              pruebas unitarias (pytest)
docs/               planteamiento, contrato de datos, bitácora y guía de réplica
web/                reporte interactivo
```

## Notebooks

Los notebooks leen artefactos ya publicados; no recalculan el pipeline.

| Notebook | Contenido |
|---|---|
| `01_calidad_y_eda` | Calidad de `fact_award_item` y análisis exploratorio |
| `02_diagnostico_resolucion_entidades` | Identificadores repetidos o ambiguos; candidatos, no fusiones |
| `03_particionamiento_spark` | Particionamiento y plan de ejecución en Spark |
| `04_clustering_y_anomalias` | Perfiles de comprador y atípicos |
| `05_auditoria_recomendacion` | Cortes temporales y cobertura de la recomendación |
| `06_recomendacion` | Evaluación e interpretación de los recomendadores |
| `07_auditoria_contenido` | Recomendación por contenido y revisión de ejemplos |
| `08_p1_p2_redes_y_comunidades` | P1, enlaces, comunidades y nulo de Puno |
| `09_sintesis_entrega_y_reporte` | Síntesis de cifras y mensajes para el informe |

## Documentación

| Documento | Contenido |
|---|---|
| [ReplanteamientoPreguntas.md](docs/ReplanteamientoPreguntas.md) | Preguntas, medición de la fuente y decisiones previas al análisis |
| [ContratoDatos.md](docs/ContratoDatos.md) | Grano, llaves y reglas de cada tabla |
| [README_Estrategico.md](docs/README_Estrategico.md) | Arquitectura, decisiones y bitácora |
| [PlanFase2CalidadEDA.md](docs/PlanFase2CalidadEDA.md), [PlanFase3Representaciones.md](docs/PlanFase3Representaciones.md) | Diseño de la calidad, el EDA y las representaciones |
| [ComandosEjecutarOrdenReplica.md](docs/ComandosEjecutarOrdenReplica.md) | Réplica en Linux, macOS, Windows y Docker |
| [ReporteReproduccionReplanteamiento20261114.md](docs/ReporteReproduccionReplanteamiento20261114.md) | Reproducción independiente de las mediciones del replanteamiento |

## Equipo y contribuciones

| Integrante | Usuario en git | Aporte principal | Commits de referencia |
|---|---|---|---|
| Ronaldo Dylan Flores Soto | `ronaldoFlores3552` | Entorno reproducible (Docker, versiones, validación), ingesta con manifiesto, tablas de adjudicación, interacciones anuales, evidencia de identidad, representaciones de la Parte I, clustering inicial de la Parte II, cadena de recomendación de la Parte III y notebooks 01 a 07 | `c7cec37` a `fa65ac4` |
| Isaac Vera Romero | `IsaacVera10`, `Isaac Vera Romero` | Replanteamiento de P1 y P2 con medición de participantes; tablas de participación; análisis de P1 con bootstrap y nulo; grafos, HITS, PageRank y Louvain de P2; perfiles renovados; SVD y convergencia; híbrido ALS + TF-IDF; particiones, BigCLAM, t-SNE y sustitutos; validación con OECE; reporte interactivo | `8ef6a14`, `916b29e`, `e29c486`, `8a03dd5`, `5f3fbf5`, `146443c`, `1ef6410` y siguientes |
| Rodo Vilcarromero | `NotRtro` | Reproducción del replanteamiento con corrección de lectura UTF-8, diagnóstico de la proyección de P2, modelo nulo Curveball, actualización de notebooks y contratos, generador del informe PDF y verificador de la entrega | `7b4e71e`, `4db2be2`, `1bf6727`, `939fbe1`, `fcb14da` |

El commit `8974503` (notebooks 08 y 09, BigCLAM inicial de Puno) figura con la cuenta
`IsaacVera10`. La traza completa sale de:

```bash
git log --no-merges --format='%h %an %ad %s' --date=short
```

## Alcance y ética

Concentración, cierre de mercado, atipicidad y afinidad inusual son señales descriptivas con
explicaciones legítimas: proveedor único en la zona, especialidad técnica o entidades pequeñas.
Se nombran entidades públicas, nunca proveedores ni participantes, porque cerca del 20 % de los
proveedores son personas naturales. La fuente excluye las contrataciones sin procedimiento de
selección.
