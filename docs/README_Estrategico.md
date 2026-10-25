# Reporte estratégico y bitácora de desarrollo

**Última actualización:** 2026-10-25

**Estado del documento:** vivo; se actualiza, no se reemplaza ni se borra su historial.

## Propósito y regla de continuidad

Este documento es el mapa de trabajo del Proyecto Integrador 2. Explica el problema, la arquitectura, las herramientas, el orden de desarrollo y el estado real del repositorio. Debe permitir que un compañero o una IA asuma el trabajo sin reconstruir el contexto desde cero.

Para el estado vigente de la Parte I, consultar [README_ParteI.md](README_ParteI.md). El [plan anterior](ReporteYPlanCierreParte1.md) se conserva como historial.

El diseño propuesto para clustering, detección de anomalías y su reproducción
está en [PlanParteIIClustering.md](PlanParteIIClustering.md); los resultados y
pendientes actuales están en [README_ParteII.md](README_ParteII.md).

La Parte III se diseñó en [PlanParteIIIRecomendacion.md](PlanParteIIIRecomendacion.md); la evaluación retrospectiva local y sus límites están en [README_ParteIII.md](README_ParteIII.md).

Reglas de actualización:

1. Actualizar la fecha superior y la sección **Situación actual** al cerrar una etapa o tomar una decisión relevante.
2. No eliminar decisiones, hipótesis descartadas, errores ni experimentos fallidos. Se conservan en la bitácora con su resultado y aprendizaje.
3. Distinguir siempre entre **implementado**, **validado** y **planificado**.
4. Registrar parámetros, semilla, años, versión de datos, ruta de salida y métrica cuando se ejecuta un experimento.
5. Agregar una entrada a **Decisiones y bitácora** si cambia el modelo de datos, la metodología, la reproducibilidad o la interpretación.

## Fuentes de verdad y orden de lectura

Para relevar el proyecto, consultar primero el código y la configuración vigente; después, los documentos de contrato y reproducción. El enunciado inicial y el plan de herramientas del curso se conservan como contexto, pero no sustituyen el estado del repositorio.

1. Código, requirements.txt, pyproject.toml, Dockerfile y docker-compose.yml.
2. ContratoDatos.md y ComandosEjecutarOrdenReplica.md.
3. Este reporte estratégico y la bitácora de decisiones.
4. Proyecto2Integrador.md y README_HERRAMIENTAS.md, como antecedentes del alcance académico y la estrategia inicial.
5. ReporteSolucionHadoopWindows.md, como registro técnico histórico de los errores y su resolución.

## 1. Contexto y objetivo académico

El proyecto analiza contrataciones públicas del Perú publicadas por OECE/OSCE en estándar OCDS. Cada proceso relaciona entidades compradoras, proveedores, ítems, montos, fechas, modalidades y, cuando existan, participantes. La relación entidad–proveedor–ítem permite construir tablas, matrices de interacción y grafos.

El objetivo no es ejecutar algoritmos por cumplir una lista. Cada técnica debe responder una pregunta útil, compararse con una referencia razonable e interpretarse con prudencia en el contexto peruano. Las señales encontradas priorizan revisión analítica; no constituyen prueba de irregularidad.

## 2. Preguntas guía y resultados esperados

| Línea | Pregunta de trabajo | Producto esperado |
|---|---|---|
| Mercado y concentración | ¿Qué entidades, categorías o proveedores concentran contratación y cómo cambia por año? | Indicadores descriptivos, concentración y visualizaciones. |
| Tipologías | ¿Qué perfiles de entidades o proveedores aparecen al agrupar compras, montos y categorías? | Vectores, clustering comparado e interpretación. |
| Recomendación | ¿Qué proveedores o categorías son similares o relevantes para una entidad bajo criterios explícitos? | Matriz de interacción, baselines y evaluación offline. |
| Red contractual | ¿Qué actores son centrales y qué comunidades o submercados se observan? | Grafos, centralidades, comunidades y validaciones. |
| Representaciones | ¿Un embedding mejora una tarea analítica concreta? | SVD, Node2Vec u otro método comparado con baseline. |
| Comunicación | ¿Cómo se presentan hallazgos y límites sin sobrerreclamar? | Artefactos trazables y reporte web o interactivo. |

## 3. Arquitectura objetivo

La capa analítica no requiere una base de datos operacional: usará Parquet particionado y artefactos precalculados. Es la solución adecuada para análisis por lotes reproducibles con Spark.

~~~text
OCDS OECE/OSCE (JSONL.GZ)
        │ descarga con manifiesto y SHA-256
        ▼
data/raw/
        │ PySpark: validación, aplanado y trazabilidad
        ▼
data/processed/fact_award_item/ (Parquet)
        │ proyección validada a nivel adjudicación
        ▼
data/processed/fact_award/ (Parquet)
        │
        ├── tablas derivadas y EDA
        ├── matrices entidad×proveedor / entidad×categoría
        ├── grafos y comunidades
        ├── modelos, embeddings y evaluación
        ▼
artifacts/ (Parquet, CSV, JSON y metadatos de corrida)
        │
        ├── reporte reproducible
        └── API FastAPI y/o interfaz web React (futuro)
~~~

Principios:

- data/raw es inmutable después de verificarse contra el manifiesto.
- Cada transformación tiene entrada, salida, parámetros y contrato explícitos.
- Spark procesa la fuente completa; pandas/NumPy se reservan para agregados, muestras o artefactos que caben en memoria.
- La API y la interfaz solo consumen resultados publicados en artifacts; no entrenan modelos ni recalculan resultados oficiales.
- Cada artefacto debe registrar fecha, años, semilla, parámetros y métricas.

## 4. Herramientas y criterio de uso

| Herramienta | Estado | Uso y límite |
|---|---|---|
| Python 3.12.x | Implementado | Intérprete objetivo local y de Docker; no usar 3.13/3.14. |
| Java 17 + PySpark 3.5.6 | Implementado | Lectura OCDS, transformación y agregaciones distribuidas. |
| Parquet + PyArrow | Implementado | Capa analítica tipada y particionada. |
| pandas, NumPy, SciPy | Disponibles | Análisis local sobre datos reducidos, validaciones y exportaciones. |
| scikit-learn | Disponible | Baselines, escalado, clustering, reducción dimensional y evaluación. |
| HDBSCAN | Disponible | Clustering por densidad si los datos lo justifican. |
| NetworkX + python-louvain | Disponibles | Grafos cuyo tamaño cabe en memoria. |
| Node2Vec + Gensim | Disponibles | Embeddings de nodos y su evaluación. |
| FastAPI + Uvicorn | Disponible, no integrado | Servir artefactos de solo lectura. |
| Docker + Docker Compose | Implementado para pipeline | Ruta principal de reproducción. |
| pytest + Ruff | Implementados | Pruebas de regresión y estilo. |
| JupyterLab + Matplotlib | Implementados | Exploración, gráficos y conclusiones anotadas; no publica tablas oficiales. |
| React/Vite/Nginx | Planificado | Interfaz final cuando existan artefactos y contrato API estables. |

Una dependencia nueva requiere justificar qué problema resuelve, alternativa considerada, versión fijada y prueba mínima.

## 5. Estructura de carpetas

La estructura se crea gradualmente. No se deben crear directorios vacíos para simular etapas terminadas.

~~~text
Proyecto2/
├── data/                         # Ignorado: datos y productos regenerables
│   ├── raw/                      # JSONL.GZ originales + manifest.json
│   ├── interim/                  # Transformaciones temporales auditables
│   └── processed/                # Tablas Parquet publicadas
├── artifacts/                    # Ignorado: modelos, métricas y JSON de salida
├── docs/
│   ├── README_Estrategico.md     # Este mapa, decisiones y estado
│   ├── README_ParteI.md          # Resultados, metodología y relevo de la Parte I
│   ├── README_ParteII.md         # Resultados y pendientes de clustering
│   ├── PlanParteIIClustering.md  # Diseño y secuencia de la Parte II
│   ├── PlanParteIIIRecomendacion.md # Pregunta, cortes y evaluación propuesta
│   ├── ComandosEjecutarOrdenReplica.md
│   ├── ContratoDatos.md
│   ├── PlanFase2CalidadEDA.md
│   ├── PlanFase3Representaciones.md
│   └── ReporteSolucionHadoopWindows.md
├── scripts/
│   ├── download_data.py          # Ingesta reproducible y manifiesto
│   ├── setup_windows_hadoop.py   # Preparación preventiva de Windows
│   └── validate_environment.py   # Validación de requisitos
├── src/
│   ├── processing/               # Transformación Spark; fact_award_item y fact_award existen
│   ├── quality/                  # Perfil técnico y reglas de calidad publicadas
│   ├── features/                 # Interacciones, vectores, matriz y KNN en Spark
│   ├── graphs/                   # Planificado: grafos y métricas
│   ├── models/                   # Clustering descriptivo y artefactos reproducibles
│   ├── evaluation/               # Planificado: métricas y baselines
│   └── serving/                  # Planificado: carga para API
├── tests/                        # Pruebas unitarias e integración acotada
├── notebooks/                    # Exploración narrada y gráficos reproducibles
│   ├── 01_calidad_y_eda.ipynb
│   ├── 02_diagnostico_resolucion_entidades.ipynb
│   ├── 03_particionamiento_spark.ipynb
│   └── 04_clustering_y_anomalias.ipynb
├── api/                          # Planificado: FastAPI
├── frontend/                     # Planificado: React
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── README.md
~~~

Las rutas marcadas como planificadas no existen todavía y no deben asumirse como funcionalidad entregada hasta que tengan código y pruebas.

## 6. Contratos de datos y objetos analíticos

La fuente es OCDS de OECE/OSCE, bajo licencia CC BY 4.0. Su procedencia se conserva en data/raw/manifest.json con URL, fecha, tamaño y SHA-256.

La primera tabla publicada es fact_award_item, documentada en [ContratoDatos.md](ContratoDatos.md), con el grano:

> proceso (process_ocid) × adjudicación (award_id) × proveedor (supplier_id) × ítem adjudicado (item_id).

Objetos derivados previstos, en orden:

1. Tablas de calidad, cobertura temporal y agregados por entidad, proveedor, categoría y año.
2. Vectores de entidad y proveedor con variables documentadas y escaladas.
3. Matrices entidad×proveedor y entidad×categoría para recomendación.
4. Grafo bipartito entidad–proveedor y, si la calidad de la fuente lo permite, grafo de co-participación de postores.
5. Grafos proyectados o KNN con ponderación, umbral y pérdida de información documentados.
6. Artefactos de modelos y resultados con metadatos de corrida.

## 7. Plan de trabajo completo

Cada fase termina con una salida, criterios de aceptación y una actualización de este documento. Si una hipótesis no se valida, se registra y se ajusta el plan; no se fuerza un resultado.

| Fase | Meta | Entregables | Criterio de cierre | Estado |
|---|---|---|---|---|
| 0. Gobierno y reproducción | Ejecutar en otra máquina. | Docker, versiones fijadas, guía, validación y pruebas. | Tabla reproducida con _SUCCESS. | Validada en Windows y Docker. |
| 1. Ingesta y modelo base | Tener una tabla trazable. | Descarga con manifiesto y fact_award_item. | Contrato respetado, salida atómica y resumen. | Implementada y validada. |
| 2. Calidad y EDA | Conocer cobertura, nulos, duplicados y sesgos. | Perfil de datos, reglas, tablas y gráficos base. | Hallazgos registrados antes de modelar. | En curso: perfil y fact_award validados; falta cerrar hallazgos en el notebook. |
| 3. Representaciones | Crear objetos para algoritmos. | Features, matrices y grafos con diccionario. | Grano, filtros, semilla y validaciones definidos. | Publicados y validados localmente; identidad canónica y linaje histórico completo siguen como límites. |
| 4. Clustering | Descubrir tipologías. | KMeans++, jerárquico y HDBSCAN comparados. | Métricas, estabilidad e interpretación. | Completada para la ventana descriptiva; límites y sensibilidad documentados. |
| 5. Recomendación | Modelar interacción. | Vecindario, contenido y factores latentes. | Evaluación temporal/offline y límites explícitos. | Evaluación retrospectiva local y contenido exploratorio completados para actores conocidos; arranque en frío pendiente. |
| 6. Enlaces y comunidades | Caracterizar la red. | PageRank, HITS y comunidades seleccionadas. | Grafo justificado y análisis de sensibilidad. | Pendiente. |
| 7. Representaciones de nodos | Probar embeddings útiles. | SVD, Node2Vec o alternativa justificada. | Comparación honesta con baseline. | Pendiente. |
| 8. Síntesis y ética | Convertir resultados en evidencia. | Hallazgos, limitaciones y anexos. | Sin causalidad ni acusaciones sin sustento. | Pendiente. |
| 9. Servicio y visualización | Exponer resultados precalculados. | API y web si aportan valor. | Contrato estable, pruebas y trazabilidad. | Pendiente. |
| 10. Entrega final | Ejecutar y defender el proyecto. | Reproducción limpia, informe, presentación y demo. | Un tercero reproduce y el equipo explica decisiones. | Pendiente. |

### Orden operativo inmediato

1. Reproducir el clustering publicado y revisar el notebook 04 junto con sus limitaciones.
2. Revisar resultados y límites de la Parte III, incluido el prototipo exploratorio por contenido y la independencia de la prueba.
3. Diseñar y validar la preparación de entrenamiento, candidatos y positivos antes de implementar modelos.
4. Integrar después los resultados de la Parte II en el reporte web exigido por el enunciado.
5. Mantener como límites abiertos la identidad canónica y la trazabilidad histórica completa; evaluar su resolución antes de usos que la requieran.

## 8. Estrategia de evaluación y rigor

- **Baselines primero:** un método complejo debe mejorar o aportar una lectura más clara que un método simple.
- **Separación temporal:** no evaluar una recomendación con datos posteriores a la fecha simulada de consulta.
- **Muestras reproducibles:** registrar semilla y criterios de inclusión.
- **Estabilidad:** variar parámetros razonables en clustering y comunidades.
- **Cobertura y sesgo:** reportar exclusiones, nulos y cambios de la fuente.
- **Trazabilidad:** cada cifra debe apuntar a artefacto, comando y parámetros.
- **Ética:** describir patrones y señales, no afirmar fraude o responsabilidad.

## 9. Decisiones y bitácora permanente

Esta sección es acumulativa. Una decisión reemplazada se marca como **superada** y se enlaza a la nueva; no se elimina.

| ID | Fecha | Decisión o experimento | Estado | Motivo y consecuencia |
|---|---|---|---|---|
| D-001 | 2026-10-19 | Usar datos OECE/OSCE en OCDS. | Vigente | Fuente abierta, relacional y trazable; CC BY 4.0. |
| D-002 | 2026-10-19 | Usar Parquet como capa analítica, no BD operacional. | Vigente | Spark y análisis por lotes cubren el alcance actual. |
| D-003 | 2026-10-19 | Usar grano proceso×adjudicación×proveedor×ítem. | Vigente | Preserva detalle para agregados, matrices y grafos. |
| D-004 | 2026-10-19 | Conservar monto de adjudicación e ítem por separado. | Vigente | No asumir que los ítems suman la adjudicación. |
| D-005 | 2026-10-23 | Establecer Python 3.12.x y Java 17. | Vigente | Entorno validado con dependencias fijadas. |
| D-006 | 2026-10-23 | Priorizar Docker; conservar ejecución local. | Vigente | Docker reduce diferencias de sistema y local ayuda al desarrollo. |
| D-007 | 2026-10-23 | En Windows usar helpers locales verificados. | Vigente | Evita conflictos de HADOOP_HOME y DLLs externas. |
| D-008 | 2026-10-23 | Identificar adjudicaciones por process_ocid + award_id. | Vigente | award_id aislado subcuenta adjudicaciones entre procesos. |
| D-009 | 2026-10-23 | Usar award_date para análisis temporal. | Vigente | source_year identifica el archivo, no el año de la adjudicación. |
| D-010 | 2026-10-23 | Usar entity_id como entidad analítica inicial. | Vigente | buyer y procuring_entity son completos y coincidentes en la corrida actual. |
| D-011 | 2026-10-23 | No sumar montos de distintas monedas ni montos repetidos por ítem. | Vigente | Primero se construirá el grano monetario correcto y una regla de conversión. |
| D-012 | 2026-10-24 | Separar el control técnico reproducible del análisis narrado. | Vigente | El perfil queda en `src/quality/` y publica artefactos; el EDA, gráficos e hipótesis se mantienen en `notebooks/`. |
| D-013 | 2026-10-24 | Crear `fact_award` antes de calcular métricas monetarias. | Vigente | Una adjudicación se identifica por `process_ocid` + `award_id`; la transformación rechaza atributos conflictivos y evita repetir `award_amount` por ítem. |
| D-014 | 2026-10-24 | Formular Fase 3 con tablas altas antes de matrices o grafos serializados. | Vigente | Las tablas Parquet normalizadas son auditables y reutilizables; matrices dispersas, índices y grafos se crearán solo para un experimento o modelo que los necesite. |
| D-015 | 2026-10-24 | No asignar monto por proveedor cuando una adjudicación tenga varios proveedores. | Vigente | `award_amount_single_supplier` solo existe cuando hay un proveedor; evita sobrecontar o repartir dinero sin sustento. |
| D-016 | 2026-10-25 | Excluir fechas ausentes de interacciones anuales y cuantificarlas; no sumar montos con moneda desconocida. | Vigente | Se preservan las filas en las tablas fuente, se informa cobertura y no se atribuye una unidad monetaria desconocida. |
| D-017 | 2026-10-25 | Tratar nombres iguales con identificadores distintos como candidatos, no como fusiones automáticas. | Vigente | Se necesita evidencia verificable, revisión de contradicciones y trazabilidad antes de publicar una correspondencia canónica. |
| D-018 | 2026-10-25 | Comparar identificadores OCDS por esquema y valor exactos, conservando el contexto del release. | Vigente | Las coincidencias y variantes son evidencia para investigar; no producen un mapeo de entidades automático. |
| D-019 | 2026-10-25 | Mantener los ID originales mientras no exista evidencia suficiente para una correspondencia. | Vigente | Los nombres compartidos y las referencias sin `party` no permiten inferir equivalencias; los análisis deben declarar la limitación. |
| D-020 | 2026-10-25 | Publicar matriz dispersa, vectores por entidad y KNN exacto con límite de pares. | Vigente | Se usan conteos sin mezclar montos y se registran ventana, escalado, diccionarios y huellas de entradas. |
| E-001 | 2026-10-19 | Python 3.14 produjo incompatibilidad pandas/Meson. | Fallido, documentado | Usar .venv312 o Docker. |
| E-002 | 2026-10-19 | pytest no encontraba scripts. | Resuelto | pyproject.toml incorpora la raíz al pythonpath. |
| E-003 | 2026-10-23 | Spark Windows falló sin winutils.exe. | Resuelto | Script descarga y verifica helpers antes de Spark. |
| E-004 | 2026-10-23 | Spark Windows falló con NativeIO Windows access0. | Resuelto | Se verifica hadoop.dll, su carga y MSVCR100.dll. |
| E-005 | 2026-10-23 | Ruta Docker completa para 2023–2024. | Validada | Descarga, Parquet y _SUCCESS correctos. |
| E-006 | 2026-10-25 | Diagnóstico exploratorio de identificadores y nombres sobre `fact_award_supplier`. | Validado localmente | Se observaron 2 858 nombres de proveedor con varios ID y 338 ID con varios nombres; son alertas, no duplicados confirmados. |
| E-007 | 2026-10-25 | Extracción Spark de identificadores OCDS de 2023 y 2024. | Validada localmente | 32 de 128 340 referencias de proveedor no cruzaron con una `party`; no se hallaron grupos candidatos por esquema y valor exactos. Esto no descarta duplicados ni sustituye la revisión de nombres. |
| E-008 | 2026-10-25 | Revisión de referencias sin cruce y de los diez nombres de proveedor con más ID. | Validada localmente | Las 32 referencias aparecen en adjudicaciones sin un `party.id` igual en su release; los diez nombres de la muestra empiezan por «consorcio» y reúnen 723 ID. No se infieren equivalencias. |
| E-009 | 2026-10-25 | Lectura Spark de interacciones con metadatos JSON. | Resuelto | Spark intentó leer `_metadata.json` como Parquet; la lectura ahora filtra `*.parquet` conservando las particiones. |
| E-010 | 2026-10-25 | Primera publicación de representaciones para adjudicaciones 2023–2024. | Validada localmente | 2 756 vectores, 61 939 pares de matriz y 13 780 aristas KNN; detalles y límites en README_ParteI.md. |
| E-011 | 2026-10-25 | Huellas de entradas distintas entre Windows y Docker por orden de rutas. | Resuelto | Se ordenan explícitamente las rutas relativas como texto POSIX; ambas plataformas obtienen la misma huella para los mismos archivos. |
| E-012 | 2026-10-25 | Interacciones, evidencia y representaciones en Docker sobre tablas existentes. | Validado | Totales de referencia conservados; la salida final coincide con el `run_id` y huellas de las interacciones regeneradas. La ruta completa desde descarga no se ejecutó en esta corrida. |
| E-013 | 2026-10-25 | Primera evaluación descriptiva KMeans++ y HDBSCAN en entidades 2023–2024. | Validada en Windows y Docker; provisional | k=4 y silueta 0,359; HDBSCAN 15/5 produjo 46 grupos y 48,9 % de ruido en Windows, 48,7 % en Docker. Los vectores repetidos y el peso de categorías exigen cautela. |
| E-014 | 2026-10-25 | Cierre descriptivo de la Parte II con Ward en muestra y sensibilidad de HDBSCAN. | Completada con límites | ARI Ward/KMeans 0,483 en 400 entidades; HDBSCAN varía con remuestreos y no se adopta como tipología definitiva. |
| E-015 | 2026-10-25 | Formulación de la Parte III: pares nuevos con proveedores conocidos, validación 2023 y prueba 2024, popularidad, vecindario y ALS implícito. | Planificado | Evaluación retrospectiva, no disponibilidad histórica probada; auditoría temporal, cobertura y modelos pendientes. |

El detalle técnico de E-003 y E-004 permanece en [ReporteSolucionHadoopWindows.md](ReporteSolucionHadoopWindows.md). Es un registro histórico; E-005 actualiza su pendiente de validación Docker.

## 10. Protocolo de relevo para una IA o nuevo integrante

1. Leer este documento, [ContratoDatos.md](ContratoDatos.md) y [ComandosEjecutarOrdenReplica.md](ComandosEjecutarOrdenReplica.md).
2. Revisar git status; preservar cambios ajenos y no borrar datos o artefactos sin instrucción explícita.
3. Confirmar el punto de partida con pytest, ruff check . y, si la tarea toca Spark, verificar _SUCCESS siguiendo la guía.
4. Revisar el contrato de entrada/salida antes de modificar una transformación. Si cambia el grano o un campo, actualizar ContratoDatos.md.
5. Implementar la unidad mínima, añadir una prueba proporcional y documentar parámetros y resultados.
6. Actualizar fases, bitácora y situación actual. No borrar entradas previas: marcarlas como superadas o fallidas.
7. No hacer commits, push, cambios externos ni operaciones destructivas sin autorización expresa del responsable del proyecto.

## 11. Situación actual

**Actualizada el 2026-10-25.**

El proyecto tiene una base de reproducción y una primera tabla analítica funcionales. Los archivos OCDS de 2023 y 2024 fueron verificados y el pipeline publicó data/processed/fact_award_item/_SUCCESS en Windows local y Docker. La corrida de referencia produjo:

| Métrica | Resultado |
|---|---:|
| Filas | 137 292 |
| Procesos | 119 762 |
| Adjudicaciones | 128 395 |
| Proveedores | 62 919 |
| Entidades | 2 967 |

La guía de réplica cubre Docker, Windows y Linux/macOS, con controles previos para los errores de Hadoop en Windows. La última validación local tuvo 30 pruebas aprobadas y Ruff sin errores. La primera ejecución de clustering se comprobó en Windows y Docker; los resultados y su variación están en README_ParteII.md.

La Fase 2 ya cuenta con un perfil inicial publicado para fact_award_item: 137 292 filas, 128 395 adjudicaciones con llave compuesta, cero duplicados exactos y cero repeticiones de la llave candidata. También se identificaron 35 fechas de adjudicación ausentes, 18 752 clasificaciones de ítem ausentes y múltiples monedas. `fact_award` se publicó con 128 395 filas y cero claves repetidas, por lo que es la base monetaria segura por moneda. El notebook 01_calidad_y_eda.ipynb es el espacio para interpretar y anotar estos hallazgos; los detalles técnicos permanecen en PlanFase2CalidadEDA.md.

La Fase 3 tiene un diseño documentado en PlanFase3Representaciones.md. `fact_award_supplier` contiene 128 395 filas y cero claves repetidas en la corrida 2023–2024. Se publicaron `entity_supplier_year` (108 924 grupos) y `entity_category_year` (21 744 grupos), con 128 360 interacciones elegibles cada una; 35 filas por fuente carecían de fecha. Las claves y sumas por moneda se reconciliaron localmente. Para adjudicaciones de 2023–2024 se publicaron 2 756 vectores, una matriz de 61 939 pares y un KNN de 13 780 aristas. La identidad canónica sigue sin confirmar.

El notebook `02_diagnostico_resolucion_entidades.ipynb` identifica candidatos
de revisión por nombre e identificador sin aplicar fusiones. La extracción
`build_identity_evidence` publicó evidencia y cobertura para los archivos
completos. La revisión encontró las 32 referencias sin cruce en adjudicaciones,
sin un `party.id` igual en el mismo release. Los diez grupos por nombre más
grandes de la muestra son consorcios y reúnen 723 ID con evidencia vinculada;
esto no prueba equivalencias. Cero candidatos por identificador exacto no
demuestra ausencia de duplicados. Los hashes originales se verifican, pero no
se comprueba por hash el origen histórico de `fact_award_supplier`. Continuar
declarando los límites de identidad y definir criterios y fuentes antes de
proponer un mapeo canónico.

KMeans++, HDBSCAN y el jerárquico con dendrograma están analizados en
[README_ParteII.md](README_ParteII.md). La Parte II está completa para el
alcance descriptivo, con limitaciones documentadas. La recomendación retrospectiva está evaluada localmente;
comunidades, embeddings, API y frontend siguen pendientes; el reporte web
interactivo es obligatorio según el enunciado.

La Parte III tiene un [plan](PlanParteIIIRecomendacion.md) y resultados retrospectivos en [README_ParteIII.md](README_ParteIII.md). La disponibilidad histórica y los casos fríos siguen abiertos.


### Avance Parte III — auditoría temporal (25 de octubre de 2026)

Se ejecutó [notebook 05](../notebooks/05_auditoria_recomendacion.ipynb) sobre las tablas locales y se registró la evidencia en [README_ParteIII.md](README_ParteIII.md). Las claves y las interacciones anuales concilian y se reprodujeron los conteos preliminares. Las fechas de ambos campos para todo el entrenamiento del corte 2023 son posteriores o iguales al corte; en 2024 ocurre en 51 473 de 88 395 filas. Las fechas por sí solas no reconstruyen la disponibilidad histórica. Se mantienen las ventanas exclusivamente para un análisis retrospectivo, sujeto a cobertura e identidad; no se ha entrenado ningún modelo. Siguiente fase: preparar y verificar candidatos y positivos con entrenamiento separado por corte.


### Avance Parte III — evaluación retrospectiva (25 de octubre de 2026)

Tras comprobar la auditoría, se prepararon cortes con Spark y se contrastaron sus conteos. Se ejecutaron popularidad, vecindario por bloques y ALS, seleccionando ALS en 2023 y comparando una prueba retrospectiva en 2024. ALS logró NDCG@10 0,0657 frente a 0,0554 de vecindario y 0,0252 de popularidad en 1 879 entidades evaluables; véanse cobertura, segmentos y límites en [README_ParteIII.md](README_ParteIII.md). No se ha verificado disponibilidad histórica, ni se han evaluado arranque en frío o recomendaciones basadas en contenido.


### Avance Parte III — contenido exploratorio (25 de octubre de 2026)

Se auditó la cobertura y se revisaron casos en [notebook 07](../notebooks/07_auditoria_contenido.ipynb). TF-IDF de descripciones de ítems, construido solo con eventos anteriores al corte, obtuvo NDCG@10 0,0098 y cobertura de proveedores 44,21 % en validación 2023; popularidad obtuvo 0,0217 y ALS 0,0558. La configuración no se adopta como modelo principal. La prueba de 2024 ya fue observada antes de formular el experimento y no sería independiente; los resultados y límites están en [README_ParteIII.md](README_ParteIII.md). La reproducción integral Docker sigue pendiente por daemon no disponible.


### Verificación tras error de arranque de Docker (25 de octubre de 2026)

Docker Desktop presentó un error relacionado con `sailor-ingest.sock` después de intentar iniciarlo; posteriormente el motor volvió a responder sin modificar ese archivo. Se conciliaron huellas y métricas de los cinco experimentos de recomendación y pasaron 38 pruebas locales. El módulo de contenido se ejecutó en Docker con las entradas existentes y una salida separada; sus 36 836 recomendaciones y métricas coincidieron con Windows. La reproducción completa desde la fuente y de todos los modelos en Docker sigue pendiente.
