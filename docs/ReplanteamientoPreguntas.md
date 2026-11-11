# Replanteamiento de las preguntas de interés y de los objetos analíticos

**Fecha:** 2026-11-10
**Estado:** propuesta para discusión del equipo (versión 5: medición de participantes, P1 reescrita y tres rondas de revisión con Codex). No modifica código ni artefactos publicados.

## 1. Qué pide el enunciado

El enunciado (Proyecto Integrador 2, Prof. Heider Sanchez) pide:

- "formular **dos o tres preguntas de interés propias, no meramente descriptivas**, y explicar su relevancia (concentración de mercado, segmentos de proveedores, actores centrales, patrones regionales, u otras)";
- "para cada técnica, proponer **qué patrón o pregunta busca responder** y por qué es relevante";
- un reporte web donde cada hallazgo sea un módulo **pregunta, visualización, controles, interpretación**, con al menos **tres hallazgos ajustables en vivo**;
- en la Parte VII, decir qué técnicas aportaron a esas preguntas y si clústeres, comunidades y embeddings **convergen**.

Las preguntas son el hilo de todo el proyecto, del criterio de análisis (3 pts) y del bono por originalidad.

## 2. Diagnóstico de lo existente

Lo hecho en Partes I a III es cuidadoso: controles de calidad, política monetaria por moneda (`fact_award`), estabilidad del clustering, comparación con baselines y límites declarados. El problema no es la rigurosidad, sino **qué preguntas se responden y con qué variables**.

### 2.1 Las preguntas guía están organizadas por técnica

`README_Estrategico.md`, sección 2, tiene seis líneas que replican los bloques del enunciado (concentración, tipologías, recomendación, red, representaciones, comunicación). Varias son descriptivas ("¿qué entidades concentran contratación?", "¿qué perfiles aparecen?") o metodológicas ("¿un embedding mejora una tarea?"). Hay que convertirlas en dos o tres preguntas integradoras, de modo que cada técnica aporte una pieza a la misma respuesta y la Parte VII tenga qué contrastar.

### 2.2 Las representaciones tienen poco alcance informativo

| Objeto | Estado | Limitación |
|---|---|---|
| Vector de entidad | 4 dimensiones: `log1p(n_adjudicaciones)` y proporción de bienes/servicios/obras por conteo (`src/features/build_part1.py:113`). | 1 421 vectores distintos para 2 756 entidades; 21 de 46 grupos HDBSCAN son un único vector (README_ParteII). El propio análisis lo reconoce y no adopta HDBSCAN. Con estas variables solo se puede describir volumen y categoría amplia. |
| Vector descriptivo de proveedor | No existe para clustering. Sí existen factores de proveedor de ALS (`recommendation_als.py:147`) y perfiles TF-IDF (`recommendation_content.py:92`). | Falta un perfil interpretable de los 39 819 proveedores de la ventana 2023-2024. |
| Grafo | KNN dirigido k=5 sobre los 4 números (`build_part1.py:158`). Permitido por el enunciado. | Une entidades parecidas, no actores relacionados. PageRank, HITS o comunidades sobre él medirían parecido en 4 variables. README_ParteI:52 ya anticipa derivar el bipartito; falta construirlo. |
| Matriz entidad × proveedor | 61 939 pares de conteos. | Reutilizable como bipartito. El vecindario ya calcula coocurrencias proveedor-proveedor por compradores compartidos (`recommendation_neighbors.py:66`). |

Variables extraídas y no usadas por ningún modelo: monto (ya agregado por moneda en `build_interactions.py:63`), `item_classification_id`, `number_of_tenderers` y `procurement_method` (`build_fact_award_item.py:112-122`). Son las variables con que se mide concentración y competencia en compras públicas.

### 2.3 La recomendación no conecta con una pregunta de mercado

La Parte III está bien encuadrada (retrospectiva, no prescriptiva) y ALS supera a popularidad y vecindario (NDCG@10 0,066 frente a 0,025 y 0,055). Pero lo que evalúa, recuperar relaciones nuevas, no responde ninguna pregunta sobre el mercado. El enunciado sugiere interpretar "proveedores sustitutos por categoría" y "afinidades inusuales"; eso falta. La rúbrica dice "al menos dos enfoques (**incluida opción híbrida o ANN** para contenido)": no hay ninguno de los dos.

### 2.4 Identidad: diagnóstico sin efecto medido

Se extrajeron identificadores y se revisaron candidatos (2 858 nombres con varios ID), sin fusionar, lo cual es prudente: los consorcios homónimos no son necesariamente el mismo actor. Lo que falta es **medir cuánto cambia la red** si se aplican fusiones conservadoras (por identificador legal exacto), para declarar el efecto de la fragmentación en centralidad y comunidades.

### 2.5 La fuente trae más de lo que se extrajo (medido el 2026-11-10)

Medición sobre los mismos archivos que usó la Parte I (SHA-256 idénticos a README_ParteI), ventana de adjudicación 2023-2024, con `scripts/exploracion/medir_participantes.py` y `medir_participantes_extra.py`; Codex re-ejecutó y reprodujo las cifras principales. Coinciden los 2 756 compradores y 39 819 proveedores de la Parte I. Hay 83 648 adjudicaciones frente a 81 724: las 1 924 adicionales no tienen proveedor y `build_fact_award_item.py:160` las descarta.

| Dato en el OCDS | ¿Se extrae hoy? | Cobertura medida |
|---|---|---|
| `tender.tenderers[]` (lista de participantes con RUC) | No, solo el conteo `numberOfTenderers` | 99,6 % de procesos; 114 147 actores distintos, 26 055 en 5 o más procesos; el ganador está en la lista salvo en 2 procesos |
| `parties[].address` del comprador (departamento, región, distrito) | No | 100 % de compradores, 25 departamentos |
| RUC del comprador (`additionalIdentifiers`) | No | Presente; permite cruzar con MEF/INEI |
| `procurementMethodDetails` (modalidad peruana) | Sí (`build_fact_award_item.py:111`), pero no se usa | 100 %; 15+ modalidades |

**Semántica de `tenderers` sin resolver.** El estándar OCDS los define como quienes presentan oferta, pero los valores sugieren otra cosa: Adjudicaciones Simplificadas con hasta 191, Licitaciones con hasta 205, y solo 1-2 % de procesos competitivos con un participante. Además, en 1 551 procesos `numberOfTenderers` es **menor** que la longitud de la lista (hasta 59 de diferencia). El raw no trae `bids`, `tender.status` ni `award.status` para distinguirlos. Hasta validarlo se habla de **participantes reportados**, se conservan ambas medidas y se reporta su discrepancia. Validación propuesta: cruzar una muestra con el [Listado de ofertantes de OECE](https://www.datosabiertos.gob.pe/dataset/listado-de-ofertantes-%E2%80%93-organismo-especializado-para-las-contrataciones-p%C3%BAblicas-eficientes).

### 2.6 Decisión: priorizar a los compradores como unidad de análisis

| Evidencia (ventana 2023-2024) | Compradores | Proveedores adjudicados |
|---|---|---|
| Cantidad | 2 756 | 39 819 |
| Identidad | Limpia: código CONSUCODE + RUC; 2 nombres con dos ID | 31,8 % son consorcios con ID propio; el 99,4 % gana una sola vez; integrantes no publicados (solo 2 de 12 792 los nombran) |
| Actividad | Mediana 11 adjudicaciones, p75 29; 54,6 % con 10 o más | Mediana 1; 73,8 % gana una sola vez; 82,8 % tiene un solo comprador; 3,8 % tiene 5 o más compradores |
| Atributos | Departamento 100 %; tipo por nombre (53,6 % municipalidades distritales, 18,7 % gobiernos regionales) | Tipo por formato de RUC: 42,1 % empresas (RUC 20), 19,9 % personas naturales (RUC 10), 31,8 % consorcios |
| Decisiones | Eligen modalidad: un solo participante en 87,7 % de Contrataciones Directas, 84,3 % de Régimen Especial, 98,2 % de Contratación Internacional | Reciben la adjudicación |

Por eso **las preguntas se formulan sobre compradores**, y proveedores y participantes son el otro lado de la red. No se prioriza el clustering de **proveedores adjudicados**: la mayoría tiene una sola observación, y en obras (73,3 % de adjudicaciones a consorcios) el actor real queda detrás de un consorcio de un solo uso. Además, el 19,9 % son personas naturales, lo que desaconseja rankings nominativos.

Los proveedores no se descartan. Los 26 055 **participantes recurrentes** permiten estudiar alcance (a cuántos compradores llegan), especialización y conversión de participación en adjudicación, y forman la red de co-participación de P2.

**Concentración por comprador:** medida por conteo de adjudicaciones en los 677 compradores con 30 o más, la cuota del principal proveedor es baja (mediana 6 %, p90 13 %, máximo 31 %). Esto no describe la concentración monetaria. Dentro de rubros es mayor (sección 3), lo que respalda la unidad comprador × rubro.

## 3. Propuesta: dos preguntas principales y una extensión

Eje común: **concentración y estructura del mercado de compras públicas**. Son preguntas asociativas: no se afirma causalidad ni irregularidad.

### P1. ¿La concentración va junto con baja participación, aun entre compradores vecinos?

> Dentro de un mismo rubro y modalidad, ¿los compradores que concentran sus adjudicaciones en pocos proveedores reciben menos participantes en sus procesos? ¿Esa asociación persiste al comparar compradores del mismo departamento y tamaño?

**Relevancia:** si la asociación desaparece al comparar dentro del departamento, es coherente con mercados locales con poca oferta. Si persiste entre compradores vecinos y comparables, señala compradores cuyo patrón merece revisión contextual. Es una **asociación que persiste o no tras ajustes**, no una atribución causal a la geografía ni al comprador: dentro de un departamento siguen variando importe, especialidad y accesibilidad.

**Unidad:** comprador × segmento CUBSO (dos primeros dígitos del UNSPSC contenido en el CUBSO de 16 dígitos) × modalidad, en la ventana 2023-2024. Se compara Adjudicación Simplificada con Adjudicación Simplificada y Licitación con Licitación.

**Variables (sobre el mismo conjunto de procesos competitivos):**
- *Concentración:* cuota del principal proveedor y HHI de las adjudicaciones de esos procesos.
- *Participación:* mediana de participantes reportados en esos mismos procesos, con `numberOfTenderers` como medida alternativa.
- *Modalidad no competitiva:* proporción de procesos en Contratación Directa, Régimen Especial, Contratación Internacional, Convenio y Adjudicación Abreviada, como dimensión aparte. Suelen tener un participante, aunque hay excepciones.
- *Contexto, no resultado:* departamento y provincia, tipo de entidad, tamaño.

**Piloto (`scripts/exploracion/piloto_p1.py`), exploratorio:**
- 1 091 unidades comprador × segmento con 10 o más procesos y 5 o más competitivos con participantes, de 601 compradores; 392 si se exigen 20. Segmentos principales: 72 (construcción), 81 (ingeniería), 30 (materiales de construcción).
- Cuota del principal proveedor: mediana 0,14, p90 0,32, máximo 0,82.
- Spearman concentración vs participantes: -0,26 (≥10 procesos) y -0,14 (≥20), confirmado por Codex con la mediana convencional. El piloto mezcla adjudicaciones de todas las modalidades con participación solo competitiva; el análisis final usa el mismo conjunto.
- El 17 % de los procesos no tiene clasificación CUBSO: exclusión declarada.

**Protocolo fijado ahora** (como el piloto ya miró la asociación, el resultado se presenta como exploratorio y no como confirmación independiente):
1. Modalidades: Adjudicación Simplificada y Licitación/Concurso por separado; no competitivas aparte.
2. Umbrales: 10 y 20 procesos competitivos por unidad.
3. Ajustes: segmento, modalidad, tramo de tamaño; luego dentro de departamento.
4. Incertidumbre: bootstrap **por comprador** (las unidades repiten compradores).
5. Referencia nula de concentración: se mantienen procesos, participantes y número de adjudicaciones, y se **simula el ganador entre los participantes reales de cada proceso** (uniforme). Es una referencia explícita, no un modelo realista de adjudicación. Se reporta el exceso de concentración sobre esa referencia.
6. Robustez: con y sin consorcios; con lista de participantes y con `numberOfTenderers`.

**Técnicas:**
- **Parte I:** extracción Spark de `tenderers`, `address` del comprador y modalidad; tabla comprador × segmento × modalidad.
- **Parte II:** KMeans++ (silueta y codo), HDBSCAN y Ward en muestra para **describir perfiles de comprador** con variables que no son las de P1 (qué compran por monto, tipo, tamaño, modalidad); luego se muestra cómo se distribuye el exceso de concentración en cada perfil. Los outliers de HDBSCAN son casos para revisión contextual.

### P2. ¿La red de participación está más fragmentada de lo esperable, y ese cierre se relaciona con la concentración?

> ¿La red de co-participación se separa por rubro o territorio más de lo que explican el tamaño de los procesos y la recurrencia de los participantes? Los compradores cuyos procesos atraen solo a una comunidad, ¿son los que muestran más concentración en P1?

**Técnicas:**
- **Grafos:**
  - *Bipartito de adjudicación* comprador-proveedor (desde la matriz; peso por conteo o monto, atribuible porque ninguna adjudicación tiene más de un proveedor).
  - *Bipartito de participación* comprador-participante (1,35 M participaciones de 114 147 actores, incluidos los que no ganan).
  - *Co-participación* participante-participante: dos actores se unen si aparecen en los mismos procesos. Es la **red de co-participación reportada**; leerla como "mercado de competencia potencial" es una interpretación provisional, porque compartir proceso no prueba competir por el mismo ítem ni ser sustituibles. Se restringe a participantes recurrentes (5 o más procesos) y se normaliza por tamaño del proceso. Los 13,0 M son expansiones de pares, no aristas únicas: antes de interpretar, se reportan participantes, procesos y compradores retenidos tras el filtro.
  - El KNN queda como contraste.
- **Parte IV:** HITS sobre el bipartito (hubs = entidades, authorities = proveedores); una authority alta puede venir de pocos compradores con mucho peso, por lo que se reporta junto con el número de compradores. PageRank en la proyección con sensibilidad al amortiguamiento, comparado con grado y fuerza para mostrar qué añade.
- **Parte V:** Louvain como exploración en el grafo completo; Girvan-Newman o espectral en un subgrafo (un rubro o un departamento) con modularidad Q. BigCLAM sobre una proyección acotada (no modela la restricción bipartita; se documenta la pérdida de pesos). Asociación con rubro y territorio por NMI/ARI, entendida como asociación con atributos, no como verdad de las comunidades.
- **Modelo nulo del cierre:** se aleatoriza el bipartito **proceso × participante**, preservando el tamaño de cada proceso y la recurrencia de cada participante (aleatorizar comprador × participante perdería justo los tamaños de proceso que generan las camarillas). En cada réplica se reconstruye la proyección con el mismo filtro y normalización y se **vuelven a detectar comunidades**; comparar comunidades optimizadas reales contra particiones fijas del nulo mantendría el sesgo de selección.
- **Enlace con P1:** las comunidades de co-participación contienen proveedores; cada comprador se atribuye a comunidades por la **proporción de los participantes** de sus procesos que pertenecen a cada una. Un comprador cuyos procesos atraen solo a una comunidad local pequeña es el caso "mercado cerrado" que conecta P1 y P2. La asociación cierre-concentración también se calcula en las réplicas nulas, porque ambas medidas salen de las mismas relaciones y pueden compartir dependencia mecánica.
- **Parte VI:** entrega principal **SVD sobre la matriz de interacción** (no sobre factores ALS ni TF-IDF), usado para visualización UMAP/t-SNE y clustering de nodos, coloreado por rubro, departamento, comunidad (P2) y perfil (P1): es la pregunta de convergencia de la Parte VII. El enunciado admite una técnica y esa tarea. Node2Vec solo como ampliación, sobre el bipartito **no dirigido**; en node2vec la exploración tipo BFS tiende a capturar equivalencia estructural y la tipo DFS homofilia, y en un bipartito el sesgo depende sobre todo de p/q. Si se hiciera predicción de enlaces, los baselines serían popularidad, ALS y caminos de longitud 3: vecinos comunes y Adamic-Adar dan cero para todo par entidad-proveedor en un bipartito.

### Parte III: híbrido (independiente de P3)

La rúbrica dice "al menos dos enfoques (incluida opción híbrida o ANN para contenido)". Para cubrirla se añade un **híbrido ALS + TF-IDF por mezcla de puntajes**. No es trivial: hoy ALS y contenido publican solo rankings truncados sin puntaje (`recommendation_als.py:181`, `recommendation_content.py:174`), así que hay que exponer puntajes sobre candidatos comunes, resolver perfiles ausentes y normalizar escalas. El peso se elige en validación 2023; la comparación en 2024 es exploratoria para este diseño (README_ParteIII:79). ANN (HNSW) es opcional.

### P3 (extensión). Relaciones inusuales y sustitutos dentro de los submercados

Solo si P1 y P2 avanzan a tiempo. Usa los recomendadores como modelo de "afinidad esperada":

- **Sustitutos por rubro:** vecinos de un proveedor por contenido dentro del mismo segmento CUBSO.
- **Puntaje de sorpresa**, con estas reglas: puntuaciones fuera de entrenamiento; percentil dentro del universo candidato, no rango del top 20 (estar fuera del top 20 solo dice "rango > 20"); calibración por historial de la entidad y popularidad del proveedor; actores fríos marcados como **no evaluables**, no como máximamente sorprendentes; comparación con popularidad y contenido. No se llama probabilidad de anomalía. Hereda los límites de disponibilidad histórica y cobertura (37,8 % de pares nuevos de 2024) ya documentados.

### Encuadre ético común

Postor único, concentración, cierre o sorpresa son **señales descriptivas para posible revisión** con explicaciones legítimas (proveedor único en la zona, especialidad, entidades pequeñas). El reporte muestra el contexto de cada señal y no publica rankings nominativos de "sospechosos".

## 4. Cambios concretos a la Parte I

| Artefacto | Propuesta |
|---|---|
| Unidades | Participantes **por proceso** (`tenderers` y `numberOfTenderers` son de la licitación y se repiten al aplanar adjudicaciones e ítems). Montos desde `fact_award`, nunca sumados desde `fact_award_item`; moneda homogénea (PEN, o conversión con el tipo de cambio que documenta la publicación OCP); nulos, ceros y negativos tratados explícitamente. |
| Tabla comprador × segmento CUBSO | Unidad de P1: n.º procesos, monto (PEN), HHI y cuota del principal proveedor, mediana de participantes en procesos competitivos, % no competitivo, departamento, provincia, tipo de entidad. |
| Vector de entidad (Parte II) | log n.º procesos, log monto (PEN), proporciones por categoría **en monto**, n.º proveedores distintos, % procedimiento no competitivo, entropía de segmentos CUBSO. **Sin** concentración ni participación, que son las variables de P1. |
| Vector de proveedor | n.º entidades, n.º adjudicaciones, log monto, HHI de compradores (dependencia), n.º familias CUBSO. Solo si hay tiempo; no es requisito de P1/P2. |
| Grafo | Bipartito de adjudicación, bipartito de participación y co-participación normalizada (sección 3, P2), exportados como nodos/aristas para GraphFrames y NetworkX. |
| Atributos de nodo | Departamento, región y distrito del comprador: están en `parties[].address` al 100 % pero hoy no se extraen (`build_identity_evidence.py:27`). El departamento del comprador no siempre es el lugar de ejecución. Segmento CUBSO: esquema `CUBSO` de 16 dígitos confirmado en el 83 % de procesos. |
| Identidad | Condicional. La auditoría existente no halló identificadores exactos compartidos dentro de un mismo esquema (PlanFase3Representaciones:145). Verificar ese resultado (incluido el cruce entre esquemas) y hacer análisis de sensibilidad en grado, HITS y comunidades solo si aparecen equivalencias justificadas. No hallarlas no prueba que la fragmentación sea irrelevante: se declara como límite. Integrantes de consorcios desde CONOSCE solo si la vinculación se valida. |

Ajuste de código: `build_clustering.py` está atado a las tres categorías y a cuatro columnas fijas (líneas 46 y 329); hay que adaptar lectura, validaciones, escalado y perfiles.

## 5. Alcance y orden de trabajo

Supuesto: entrega en la semana 15 del cronograma del enunciado (unas tres a cuatro semanas desde hoy); **confirmar fecha y disponibilidad del equipo**.

1. **Contrato de datos (hecho en parte, sección 2.5):** falta confirmar si `tenderers` son participantes u oferentes (documentación de OECE o comparación con actas de buena pro en una muestra), revisar monedas y extender la extracción Spark a `tenderers`, `address` y `procurementMethodDetails`.
2. **Cadena completa pequeña:** un resultado de P1 (estratos) y uno de P2 (bipartito, proyección, comunidades con su nulo), ya integrados en la web. Recién después se amplían métodos.
3. Partes II (rehacer con nuevas variables), IV (HITS, PageRank) y V completas.
4. Parte VI con SVD. Híbrido de la Parte III.
5. **Web desde el inicio**, sumando módulos a medida que salen artefactos. Tres hallazgos interactivos candidatos: k de KMeans (perfiles), amortiguamiento de PageRank y umbral de proyección (P2), resolución de comunidades.
6. **Orden de recorte** si falta tiempo: primero P3 (sorpresa), luego Node2Vec, vector de proveedor y CONOSCE. No se recorta interpretación, validación del nulo ni reporte.

## 6. Qué se reutiliza

- Ingesta, `fact_award_item`, `fact_award`, `fact_award_supplier`, tablas de interacción anuales.
- Matriz entidad × proveedor (pasa a bipartito) y coocurrencias del vecindario (base de la proyección).
- Factores ALS y perfiles TF-IDF (entrada para el híbrido y los sustitutos). SVD se calcula sobre la matriz.
- Metodología de clustering y de evaluación de la Parte III.

## 7. Fuente

OCDS Perú, OECE/OSCE, publicación 135 de Open Contracting Partnership, licencia CC BY 4.0. La publicación excluye contrataciones sin procedimiento de selección: los resultados no se generalizan a todo el gasto público.
