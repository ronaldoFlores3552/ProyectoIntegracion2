# Reporte estratégico y bitácora de desarrollo

**Última actualización:** 2026-10-24  
**Estado del documento:** vivo; se actualiza, no se reemplaza ni se borra su historial.

## Propósito y regla de continuidad

Este documento es el mapa de trabajo del Proyecto Integrador 2. Explica el problema, la arquitectura, las herramientas, el orden de desarrollo y el estado real del repositorio. Debe permitir que un compañero o una IA asuma el trabajo sin reconstruir el contexto desde cero.

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
│   ├── features/                 # Planificado: vectores y matrices
│   ├── graphs/                   # Planificado: grafos y métricas
│   ├── models/                   # Planificado: modelos y embeddings
│   ├── evaluation/               # Planificado: métricas y baselines
│   └── serving/                  # Planificado: carga para API
├── tests/                        # Pruebas unitarias e integración acotada
├── notebooks/                    # Exploración narrada y gráficos reproducibles
│   └── 01_calidad_y_eda.ipynb
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
| 3. Representaciones | Crear objetos para algoritmos. | Features, matrices y grafos con diccionario. | Grano, filtros, semilla y validaciones definidos. | En curso: `fact_award_supplier` validada; faltan las interacciones altas. |
| 4. Clustering | Descubrir tipologías. | KMeans++, jerárquico y/o HDBSCAN comparados. | Métricas, estabilidad e interpretación. | Pendiente. |
| 5. Recomendación | Modelar interacción. | Vecindario, contenido y factores latentes. | Evaluación temporal/offline y límites explícitos. | Pendiente. |
| 6. Enlaces y comunidades | Caracterizar la red. | PageRank, HITS y comunidades seleccionadas. | Grafo justificado y análisis de sensibilidad. | Pendiente. |
| 7. Representaciones de nodos | Probar embeddings útiles. | SVD, Node2Vec o alternativa justificada. | Comparación honesta con baseline. | Pendiente. |
| 8. Síntesis y ética | Convertir resultados en evidencia. | Hallazgos, limitaciones y anexos. | Sin causalidad ni acusaciones sin sustento. | Pendiente. |
| 9. Servicio y visualización | Exponer resultados precalculados. | API y web si aportan valor. | Contrato estable, pruebas y trazabilidad. | Pendiente. |
| 10. Entrega final | Ejecutar y defender el proyecto. | Reproducción limpia, informe, presentación y demo. | Un tercero reproduce y el equipo explica decisiones. | Pendiente. |

### Orden operativo inmediato

1. Ejecutar y completar 01_calidad_y_eda.ipynb usando los artefactos publicados.
2. Publicar interacciones altas `entity_supplier_year` y `entity_category_year`, conservando moneda y exclusiones temporales.
3. Definir una pregunta medible y un baseline por familia técnica antes de entrenar un modelo.
4. Construir la representación mínima que responda cada pregunta.
5. Evaluar, interpretar y solo entonces decidir si se agrega API o frontend.

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
| E-001 | 2026-10-19 | Python 3.14 produjo incompatibilidad pandas/Meson. | Fallido, documentado | Usar .venv312 o Docker. |
| E-002 | 2026-10-19 | pytest no encontraba scripts. | Resuelto | pyproject.toml incorpora la raíz al pythonpath. |
| E-003 | 2026-10-23 | Spark Windows falló sin winutils.exe. | Resuelto | Script descarga y verifica helpers antes de Spark. |
| E-004 | 2026-10-23 | Spark Windows falló con NativeIO Windows access0. | Resuelto | Se verifica hadoop.dll, su carga y MSVCR100.dll. |
| E-005 | 2026-10-23 | Ruta Docker completa para 2023–2024. | Validada | Descarga, Parquet y _SUCCESS correctos. |

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

**Actualizada el 2026-10-24.**

El proyecto tiene una base de reproducción y una primera tabla analítica funcionales. Los archivos OCDS de 2023 y 2024 fueron verificados y el pipeline publicó data/processed/fact_award_item/_SUCCESS en Windows local y Docker. La corrida de referencia produjo:

| Métrica | Resultado |
|---|---:|
| Filas | 137 292 |
| Procesos | 119 762 |
| Adjudicaciones | 128 395 |
| Proveedores | 62 919 |
| Entidades | 2 967 |

Las pruebas actuales son 9 y pasan; ruff check . no reporta errores. La guía de réplica cubre Docker, Windows y Linux/macOS, con controles previos para los errores de Hadoop en Windows.

La Fase 2 ya cuenta con un perfil inicial publicado para fact_award_item: 137 292 filas, 128 395 adjudicaciones con llave compuesta, cero duplicados exactos y cero repeticiones de la llave candidata. También se identificaron 35 fechas de adjudicación ausentes, 18 752 clasificaciones de ítem ausentes y múltiples monedas. `fact_award` se publicó con 128 395 filas y cero claves repetidas, por lo que es la base monetaria segura por moneda. El notebook 01_calidad_y_eda.ipynb es el espacio para interpretar y anotar estos hallazgos; los detalles técnicos permanecen en PlanFase2CalidadEDA.md.

La Fase 3 tiene un diseño documentado en PlanFase3Representaciones.md. Su primera entrega, `fact_award_supplier`, fue publicada con 128 395 filas, cero claves repetidas y un proveedor por adjudicación en la corrida 2023–2024. Después se construirán tablas altas de interacción por entidad, proveedor, categoría, año analítico y moneda. No se crearán matrices densas, grafos ni modelos hasta validar estas bases. Falta cerrar las conclusiones narrativas del EDA y construir esas representaciones antes de modelar.

No existen todavía módulos de features, grafos, clustering, recomendación, comunidades, embeddings, API o frontend; se documentan como trabajo futuro, no como funcionalidad entregada.
