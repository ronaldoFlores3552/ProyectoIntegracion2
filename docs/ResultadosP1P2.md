# Resultados de P1, P2 y Partes II a VII

**Fecha:** 14 de noviembre de 2026
**Corrida:** Python 3.12.16, Java 17.0.18, `requirements.txt`, raw 2023 y 2024 con los
SHA-256 del reporte de reproducción, `bash scripts/run_pipeline.sh`. Ventana de
adjudicación 2023-2024. Cada cifra apunta a un artefacto de `artifacts/` o `data/processed/`.

Las preguntas están en [ReplanteamientoPreguntas.md](ReplanteamientoPreguntas.md). Todo lo
que sigue es asociativo y descriptivo: no se afirma causalidad, competencia efectiva ni
irregularidad. Los participantes son **participantes reportados** (`tender.tenderers`); el
cruce con el Listado de ofertantes de OECE no se pudo hacer y queda como límite.

Cada resultado se revisó con una auditoría independiente que reprodujo cálculos y señaló
errores; las correcciones aplicadas se listan al final.

## P1. Concentración y participación

Artefactos: `artifacts/p1/analysis/`. Unidad: comprador × departamento × segmento CUBSO ×
modalidad, sobre procesos competitivos.

| Umbral | Asociación | ρ de Spearman | IC 95 % bootstrap por comprador | Unidades |
|---|---|---:|---:|---:|
| 10 procesos | bruta | −0,228 | [−0,302; −0,158] | 821 |
| 10 procesos | centrada en el estrato | −0,050 | [−0,137; 0,063] | 535 |
| 20 procesos | bruta | −0,154 | [−0,279; −0,041] | 241 |
| 20 procesos | centrada en el estrato | 0,079 | [−0,177; 0,280] | 140 |

El estrato es departamento × segmento × modalidad × tramo de procesos (10-19, 20-49, 50+),
con al menos tres unidades. El estadístico es el Spearman de valores centrados en la mediana
del estrato, no una correlación parcial. El bruto y el ajustado no tienen la misma población
(821 frente a 535 unidades), porque los estratos pequeños se descartan.

**Lectura.** No se detecta asociación monotónica agregada después del centrado por estrato
en la población analizada. La asociación bruta existe, pero:

- La referencia nula, que sortea cada ganador entre los participantes reportados de su
  proceso, produce una asociación más negativa que la observada en todas las simulaciones
  (bruta: media −0,271, percentiles [−0,288; −0,249]). La concentración real depende menos
  del número de participantes de lo que esa mecánica produciría. Esto no aísla una causa:
  el nulo también conserva identidades y solapamientos entre listas.
- Sin adjudicaciones a consorcios (heurística por nombre), el bruto cae a −0,051. Esta
  sensibilidad recalcula el HHI pero conserva el número de procesos y las medianas de
  participantes de la unidad original; 264 de las 815 unidades quedan con menos de diez
  procesos no consorcio. Es una señal descriptiva, no un mecanismo probado.
- Con HHI por monto en soles el patrón es el mismo (ajustado −0,100, IC [−0,180; 0,015]).

## Parte II. Perfiles de comprador

Artefactos: `artifacts/buyer_clustering/`, `artifacts/buyer_outliers/`.

Variables (estandarizadas): logaritmo de procesos, de monto en soles y de proveedores
distintos; entropía de segmentos CUBSO; proporción no competitiva; reparto del monto
positivo en soles entre bienes, servicios y obras. Se excluyen HHI y participación para no
explicar P1 con sus propias variables. No se aplicó PCA previa: con ocho variables
interpretables no hacía falta; se usa PCA solo para visualizar.

KMeans++ elige k = 5 por silueta (0,343) con grupo mínimo de 126; es estable (ARI 0,96 a
0,99 en submuestras del 80 %). Ward queda por debajo en silueta para todo k (0,214 a 0,277).

| Perfil | Compradores | Procesos (med.) | Rasgo |
|---|---:|---:|---|
| 0 | 755 | 8 | predominio de obras (83 % del monto) |
| 1 | 895 | 39 | grandes y diversificados (alta entropía CUBSO) |
| 2 | 466 | 4 | predominio de servicios |
| 3 | 514 | 5 | predominio de bienes |
| 4 | 126 | 14,5 | mayormente no competitivo (mediana 67 %) |

HDBSCAN (30, 10) deja el 71,5 % como ruido: los grupos densos aparecen entre compradores
pequeños de perfil puro, y los diversificados quedan fuera. El ruido no se trata como
anomalía. Los **candidatos atípicos** son el 2 % más lejano al centroide de su propio perfil
entre los 2 011 compradores con 5 procesos o más: 41 compradores, todos también ruido de
HDBSCAN. Son de dos tipos; las explicaciones entre paréntesis son hipótesis de contexto, no
causas verificadas:

- Volumen o monto muy por encima de su perfil: OEFA, Petroperú, EsSalud (1 870 procesos),
  PromPerú, Ejército, GORE Puno y Junín, CENARES, proyectos especiales del MTC (hipótesis:
  escala nacional o compras corporativas).
- Proporción no competitiva o diversidad de rubros fuera de lo común en su perfil: unidades
  ejecutoras y programas, varios con nombre de proyecto ("Mejoramiento…", "Programa…")
  (hipótesis: financiamiento externo con reglas propias).

El rasgo de cada candidato es la variable con mayor desviación estandarizada respecto del
centroide de su perfil, la misma que usa el detector.

## Parte III. Recomendación

Artefactos: `artifacts/recommendation_*`.

| Modelo | Corte | NDCG@10 |
|---|---|---:|
| Popularidad | prueba 2024 | 0,025 |
| Vecindario item-item | prueba 2024 | 0,055 |
| ALS implícito (16 factores) | prueba 2024 | 0,066 |
| TF-IDF de ítems | validación 2023 | 0,010 |
| ALS | validación 2023 | 0,056 |
| Híbrido ALS + TF-IDF (fusión recíproca de rangos, k = 60) | validación 2023 | 0,040 |

El híbrido no mejora a ALS en validación 2023. Se reporta como intento, no como modelo
adoptado; la métrica no identifica por qué la fusión empeora.

**Sustitutos por segmento.** Para 2 784 proveedores con 3 o más adjudicaciones en 2023, los
cinco vecinos TF-IDF de sus ítems dentro del mismo segmento CUBSO. Validación con
adjudicaciones de 2024, excluidos los 126 procesos que tienen adjudicaciones en ambos años:

| Pares | Coinciden en un proceso de 2024 | Comparten comprador en 2024 |
|---|---:|---:|
| Sustituto más cercano | 46,3 % | 19,7 % |
| Cinco más cercanos | 37,0 % | 15,2 % |
| Al azar del mismo segmento | 14,1 % | 7,0 % |

El sustituto por contenido aparece en los mismos procesos 3,3 veces más que un proveedor al
azar del rubro (con la fuga original la cifra era 58,6 % frente a 13,4 %). Es evidencia de que el contenido recupera competidores plausibles, no de
que sean intercambiables.

**Afinidades inusuales.** Pares comprador-proveedor adjudicados con similitud TF-IDF en el
5 % inferior. Son más frecuentes en ropa y aseo (11 %), TI (10 %), material vivo (9 %) y
equipo médico (9 %), y raras en construcción (1,5 %). Son señales descriptivas para
revisión, no recomendaciones.

## Parte IV. Análisis de enlaces

Artefactos: `artifacts/p2/links/`, `artifacts/p2/hits_sensitivity/`.

**PageRank** en la proyección de co-participación (25 379 nodos, 1 698 528 aristas,
pesos de Newman). ρ con la fuerza ponderada: 0,960 (d = 0,75), 0,973 (0,85) y 0,989 (0,95);
con el grado solo 0,75 a 0,77. El orden casi no cambia con d (ρ ≥ 0,986). Con la
normalización de Newman cada proceso aporta una unidad de fuerza a cada participante, así
que la fuerza cuenta procesos compartidos, no vecinos. PageRank aporta poco más que esa
fuerza. La red tiene diez componentes; la mayor reúne el 99,8 % de los nodos.

**HITS** en el bipartito comprador-proveedor depende del peso:

| Peso | Masa de la primera authority | Primeros hubs |
|---|---:|---|
| conteo de adjudicaciones | 83,8 % | GORE Puno, Cusco, Arequipa, Madre de Dios, M. P. Espinar |
| log1p | 4,2 % | EsSalud, CENARES, Ejército, Sanidad PNP, INSN |
| binario | 1,2 % | EsSalud, CENARES, Sanidad PNP, Ejército, INSN |

Con conteos, un proveedor de materiales de construcción (segmento 30, 215 compradores)
concentra el vector principal y arrastra a los compradores del sur que más le adjudican.
Con log1p o binario, la cima pasa al submercado de salud. El orden completo de hubs es
estable entre pesos (ρ 0,91 a 0,99). La lectura defendible es una localización fuerte
dependiente del peso y de una authority dominante, no un ranking de importancia.
Las 200 primeras authorities tienen mediana de 4,5 compradores.

## Parte V. Comunidades

Artefactos: `artifacts/p2/communities/`, `artifacts/p2/louvain_order/`, `artifacts/p2/null/`, `artifacts/p2/partition/`,
`artifacts/p2/bigclam/`.

**Red nacional, Louvain** (proyección de 25 379 nodos). Q entre 0,59 y 0,63 según la
resolución, con ARI entre semillas de 0,81 a 0,94. En `python-louvain` la resolución no se
comporta de forma monótona en esta red (unas 390, 36 y 46 comunidades con 0,5, 1,0 y 1,5); se
reporta como sensibilidad, no como control de escala. Con la misma semilla, el orden de inserción de las
aristas también cambia el resultado: con resolución 1,5, Q va de 0,623 a 0,629 y el ARI entre
órdenes de 0,80 a 0,90 (`artifacts/p2/louvain_order/`, dos permutaciones aleatorias más
el orden del archivo y el ordenado). Spark no fija el orden de las filas, así que otra máquina puede
obtener cifras levemente distintas sin que haya un error.

**Subgrafo de Puno** (participantes con 5 o más procesos en compradores de Puno; componente
gigante de 1 904 nodos y 84 956 aristas).

| Método | Grafo | Comunidades | Q | AMI segmento | AMI provincia | Tiempo |
|---|---|---:|---:|---:|---:|---:|
| Louvain (resolución 1,5) | gigante | 17 | 0,611 | 0,524 | 0,108 | 0,6 s |
| Espectral (k = 15, elegido por Q en 2 a 30) | gigante | 15 | 0,611 | 0,515 | 0,098 | 0,5 s |
| Girvan-Newman (mejor nivel) | núcleo de 120 nodos | 5 | 0,318 | 0,444 | 0,131 | 124 s |
| Louvain (resolución 1,0) | núcleo | 6 | 0,579 | 0,512 | 0,055 | 0,02 s |
| Espectral (k = 5) | núcleo | 5 | 0,557 | 0,502 | 0,094 | 0,005 s |

El núcleo son los 120 nodos de mayor fuerza: una selección deliberada de actores centrales,
no una muestra representativa. Girvan-Newman usa distancia = 1/peso para la intermediación y
desempates deterministas; dos corridas en procesos distintos dan el mismo resultado. Su mejor
partición deja un grupo con dos tercios de los nodos: al cortar puentes aísla grupos pequeños.

**Modelo nulo.** Curveball sobre el bipartito proceso × participante ya filtrado por
recurrencia (conserva cuántos participantes tiene cada proceso y en cuántos procesos está cada
participante), 50 réplicas con 50 intercambios por participante, y Louvain de nuevo en cada
réplica. Q nulo: media 0,079, percentiles 2,5 y 97,5 [0,078; 0,080]; observado 0,612; ninguna
réplica lo alcanza (p de Monte Carlo ≤ 1/51). En `python-louvain` la ganancia local y el
criterio de parada usan la resolución en términos distintos cuando es distinta de 1; por eso se
repitió todo con resolución 1,0, donde ambos coinciden con la modularidad estándar: Q
observado 0,626 frente a los percentiles 2,5 y 97,5 del nulo, [0,087; 0,091], en 50 réplicas.

**BigCLAM** sobre las aristas binarias del gigante de Puno. K se elige con el 10 % de las
aristas reservadas más el mismo número de no-aristas, todas excluidas del objetivo; regla: el
menor K con AUC a 0,005 o menos del mejor. Con 300 iteraciones la AUC crece de 0,930 (K = 5) a
0,981 (K = 100) y se aplana; la regla elige K = 50 (AUC 0,977). El 50,3 % de los participantes
queda en dos o más comunidades y el 6,4 % en ninguna. Ningún nodo queda con factores en cero ni
hay aristas con probabilidad menor a 1e-4.

K y las pertenencias dependen del presupuesto de iteraciones: con 100 iteraciones la misma
regla elegía K = 40 (44,9 % solapados), y los ajustes con K ≥ 30 no alcanzan el criterio de
parada ni con 300. K = 50 se reporta como provisional. En los pares reservados, la AUC es
0,977 y la AP 0,975; sirven para elegir K, no como evaluación final independiente.

El solapamiento es estable entre semillas (50,2 % a 50,6 % con las semillas 7, 42 y 99),
pero depende del umbral de pertenencia: con la mitad del umbral sube a 61 % a 63 % y con el
doble baja a 30 %. Lo que se sostiene es cualitativo: una parte grande de los participantes
pertenece a más de una comunidad. Una versión anterior, con K = 8 fijo, la proyección completa
y una regla relativa al factor máximo de cada nodo, daba 33,7 %, dentro de ese rango.

**Lectura.** La red está mucho más fragmentada de lo que explican el tamaño de los procesos y
la recurrencia. Dentro de Puno las comunidades siguen el rubro (AMI 0,52) mucho más que la
provincia del comprador (0,11). Muchos participantes están en varios submercados a la vez.

## P1 y P2 juntas: cierre y concentración

Artefacto: `artifacts/p2/closure/`. Para cada unidad de P1 (comprador × departamento ×
segmento × modalidad), el cierre es la proporción de sus participaciones proceso ×
participante etiquetadas que pertenece a su comunidad más frecuente (Louvain nacional,
resolución 1,0, semilla 42). Solo los participantes recurrentes tienen comunidad; la mediana de
participaciones etiquetadas es 88 % en las unidades con 10 o más procesos.

| Umbral | Asociación | ρ cierre-HHI | IC 95 % | ρ nulo (media) | Nulo p2,5 a p97,5 |
|---|---|---:|---:|---:|---:|
| 10 | bruta | 0,184 | [0,109; 0,253] | 0,207 | [0,185; 0,228] |
| 10 | centrada | 0,165 | [0,043; 0,254] | 0,183 | [0,140; 0,224] |
| 20 | bruta | 0,188 | [0,075; 0,308] | 0,223 | [0,170; 0,275] |
| 20 | centrada | 0,201 | [−0,056; 0,398] | 0,230 | [0,146; 0,316] |

El nulo sortea el ganador entre los participantes reportados y deja el cierre fijo, porque el
cierre solo depende de la participación.

**Exceso de concentración.** Para cada unidad se calcula la esperanza exacta del HHI con
ganador uniforme entre los participantes de cada proceso. En las 810 unidades con 10 o más
procesos, el HHI observado promedia 0,113 y el esperado 0,081; el 68 % de las unidades tiene
exceso positivo. No se detecta asociación monotónica entre cierre y exceso: ρ = 0,020
[−0,063; 0,099] bruto (810 unidades) y 0,024 [−0,085; 0,129] centrado (532 unidades).

**Lectura.** La asociación observada entre cierre y concentración no supera la que genera
una adjudicación uniforme dada la participación observada. Hay concentración por encima de
esa referencia en dos tercios de las unidades, y no se detecta asociación monotónica entre ese
exceso y el cierre. La referencia uniforme es solo un punto de comparación, no un modelo de
cómo se adjudica, así que el exceso no indica irregularidad ni identifica causas.

## Parte VI. Representaciones

Artefactos: `artifacts/p2/svd/`, `artifacts/p2/svd_participation/`, `artifacts/p2/embedding/`,
`artifacts/p2/convergence/`.

- **SVD de la matriz comprador × proveedor adjudicado** (8 componentes, conteos): explica el
  35,5 % de la varianza, pero la mediana de la energía capturada por comprador es de
  apenas 6 × 10⁻⁶. Solo el 17,2 % de los 39 819 proveedores adjudica a dos o más
  compradores, así que la matriz comparte poca estructura entre filas y la mayoría de
  compradores queda casi sin representar. Se conserva como línea base.
- **SVD de la matriz comprador × participante recurrente** (64 componentes; log1p × idf; filas
  con norma 1): mediana de energía 0,14 (p10 0,04, p90 0,29). 29 compradores no tienen
  participantes recurrentes y 395 tienen energía menor a 0,05: quedan 2 332 (84,6 %). La
  retención (entre quienes tienen fila en la matriz) es desigual: 98 % de los grandes diversificados, 90 % de obras, 78 % de bienes,
  70 % de no competitivos y 65 % de servicios. Las conclusiones valen para los conservados.
- **Tarea:** t-SNE (perplejidad 30) para visualizar y KMeans de k = 2 a 10 sobre los vectores
  normalizados. La silueta es baja (0,05 a 0,13) y crece con k: no aparece un óptimo interior en
  el rango explorado, así que k = 10 es solo el máximo del barrido.

| k | Silueta | NMI departamento | NMI perfil (II) | NMI comunidad (V) |
|---:|---:|---:|---:|---:|
| 5 | 0,090 | 0,370 | 0,140 | 0,351 |
| 10 | 0,128 | 0,519 | 0,122 | 0,306 |

Con k = 10 la AMI (corregida por azar) es 0,509 con departamento, 0,118 con perfil y 0,293 con
comunidad. Con umbrales de energía 0,02 y 0,10 la AMI con departamento queda en 0,51 y 0,49:
la conclusión se mantiene entre los umbrales probados.

**Convergencia** sobre los 2 726 compradores con comunidad: NMI perfil-comunidad dominante
0,232, perfil-departamento 0,067 y comunidad-departamento 0,129. La mezcla comunitaria de
cada comprador pondera por participaciones proceso × participante, sumadas por comunidad.
La coincidencia entre embedding y comunidades es interna: ambos salen de las mismas
participaciones, así que no es una validación independiente.

**Lectura.** El embedding de participación capta territorio y comunidad; casi nada del perfil
de compra. Comunidades y embeddings convergen porque ambos salen de con quién se compite; los
perfiles miden qué se compra y van por otro lado.

## Parte VII. Discusión

- **Qué aportó más.** Los estratos, el bootstrap por comprador y los nulos de P1; Louvain con
  su nulo Curveball; el cierre comunitario y el exceso de HHI contrastados con el ganador
  uniforme. Juntos
  responden P1 y P2. Los sustitutos por contenido, validados fuera de tiempo, mostraron
  competidores plausibles.
- **Qué aportó poco.** PageRank repite la fuerza en una red no dirigida. HITS depende del peso y
  lo domina un proveedor. El SVD de adjudicaciones no representa a la mayoría de compradores. El
  híbrido no supera a ALS. HDBSCAN marca como ruido al 71,5 %.
- **Convergencia.** Parcial, como se describe en la Parte VI.
- **Escala.** Spark fue necesario para aplanar los releases y para la proyección (13,0 millones de
  pares sin tope). Louvain, el espectral disperso y BigCLAM escalan al subgrafo departamental;
  Louvain a la red nacional. Girvan-Newman exigió un núcleo de 120 nodos y más de dos minutos.
  Con todo el histórico (más de 1,9 GB) habría que pasar la proyección y Louvain a GraphFrames,
  aplicar el tope por proceso antes del *join* y reemplazar t-SNE por un método incremental.
- **Ética.** Concentración, cierre, atipicidad y afinidad inusual son señales descriptivas con
  explicaciones legítimas (proveedor único en la zona, especialidad, financiamiento externo,
  entidades pequeñas). Se nombran entidades públicas y nunca proveedores o participantes; el 20 %
  son personas naturales. Aun sin nombres, la estructura de la red permitiría reidentificar a
  algunos actores, así que no se promete anonimato. La publicación excluye contrataciones sin
  procedimiento de selección.

## Correcciones tras la auditoría

| Hallazgo | Corrección |
|---|---|
| BigCLAM dejaba nodos en cero y aristas con probabilidad cero; los pares reservados contaban como no-aristas | Paso inicial normalizado, pares reservados excluidos del objetivo, diagnósticos, regla de parsimonia y 300 iteraciones; K queda como provisional |
| La lectura del cierre afirmaba que la adjudicación no agrega concentración | Se agrega el exceso de HHI frente a su esperanza exacta con ganador uniforme |
| Las explicaciones de los atípicos usaban medianas globales | Se usa la desviación respecto del centroide del perfil, la misma del detector |
| Procesos con adjudicaciones en 2023 y 2024 entraban en la validación de sustitutos | Se excluyen esos 126 procesos |
| Las NMI del embedding mezclaban poblaciones | Se reportan sobre los compradores conservados, con NMI y AMI; la convergencia perfil-comunidad publica NMI |
| El HHI esperado deduplicaba adjudicaciones por `award_id`, que se repite entre procesos | La clave incluye `process_ocid`; prueba con identificadores repetidos |
| La comunidad dominante del comprador tomaba el participante individual más frecuente | Suma de participaciones por comunidad antes de calcular proporciones y entropía |
| El SVD de adjudicaciones dejaba vectores casi nulos | SVD de participación con energía capturada por comprador y umbral explícito |
| El nulo de P2 usaba 10 réplicas y 5 intercambios | 50 réplicas y 50 intercambios; se reportan percentiles y p de Monte Carlo |
| Afirmación de monotonía de la resolución de Louvain | Retirada |
| HITS se interpretaba como bloque denso del sur | Sensibilidad al peso y masa de la primera authority |
| El bootstrap de P1 dependía del orden de los compradores | Orden fijo y semilla efectiva publicada |
| Girvan-Newman cambiaba entre corridas por el orden de los nodos | Orden canónico y desempate explícito |
| Validación de sustitutos con fuga (mismos procesos) | Perfiles 2023 y validación en procesos 2024 |
| El ruido de HDBSCAN se leía como anomalía | Candidatos por distancia al centroide del perfil, con 5 o más procesos |
