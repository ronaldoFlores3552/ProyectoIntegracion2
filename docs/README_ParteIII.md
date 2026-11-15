# Parte III: Recomendación: estado y auditoría

**Actualización:** 25 de octubre de 2026, hora de Lima.  
**Estado:** análisis retrospectivo, modelos, conclusiones y réplica de la cadena de recomendación completados para relaciones nuevas entre actores conocidos. Persisten limitaciones de arranque en frío, identidad y disponibilidad histórica; la obligatoriedad de una opción híbrida o ANN en la rúbrica requiere confirmación.

## Pregunta y criterio de evaluación

El experimento pretende ordenar proveedores conocidos en el entrenamiento que todavía no tienen una relación observada con una entidad, y comparar ese ranking con relaciones nuevas observadas después. Las adjudicaciones no son preferencias y el resultado no constituye una recomendación de contratación. El diseño completo está en [PlanParteIIIRecomendacion.md](PlanParteIIIRecomendacion.md).

La evaluación es **retrospectiva por fecha de adjudicación**: los archivos disponibles contienen releases compilados actuales, no snapshots verificados del conocimiento disponible al corte. Por ello no se afirma una simulación prospectiva ni ausencia de fuga por disponibilidad. La identidad canónica permanece sin resolver y la cobertura de la fuente no implica un censo.

## Auditoría ejecutada

El [notebook 05](../notebooks/05_auditoria_recomendacion.ipynb) leyó columnas acotadas de `fact_award`, `fact_award_supplier` y `entity_supplier_year` con PyArrow y pandas, verificó `_SUCCESS` y límites de filas y tamaño, y registró huellas de los archivos Parquet actuales. Las fechas se interpretaron como instantes UTC y se convirtieron a America/Lima; el año calculado coincidió con `award_year`.

En las tablas locales se verificó la unicidad de la clave de adjudicación y de adjudicación-proveedor, la correspondencia de cada fila proveedor con una adjudicación, y la igualdad de entidad, fecha, release y año de fuente. Los **108 924 grupos anuales** conciliaron por entidad, proveedor, año y moneda con los eventos elegibles. Entre 128 395 filas hay 35 sin fecha y ninguna con entidad o proveedor vacío; la unión de exclusiones es 35. Estos resultados no verifican la cadena histórica completa hasta el raw.

| Corte | Eventos entrenamiento | Eventos período | Pares nuevos | Pares nuevos evaluables | Entidades evaluables | Cobertura de pares nuevos |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | 46 636 | 41 759 | 31 616 | 9 806 | 1 843 | 31,0 % |
| 2024 | 88 395 | 39 965 | 26 570 | 10 038 | 1 879 | 37,8 % |

Se observaron además 2 682 y 6 522 pares repetidos en los períodos de 2023 y 2024. Entre pares nuevos, respectivamente, 603 y 180 incluyen entidad fría; 21 670 y 16 472 incluyen proveedor frío. Ambas categorías se solapan en 463 y 120 pares; no se suman. Estos conteos reproducen el diagnóstico preliminar del plan, pero no son resultados de un modelo.

### Disponibilidad: hallazgo que condiciona la interpretación

Para ambos campos `release_date` y `published_date`, en el corte de 2023 **las 46 636 filas de entrenamiento** registran fechas desde el corte en adelante. En el corte de 2024, **51 473 de 88 395** filas están desde el corte en adelante y 36 922 antes. No hay fechas nulas de esos campos en esos conjuntos. Los campos se cuentan por separado; no deben sumarse.

Es evidencia de que los releases actuales no representan directamente información demostrada disponible en el momento del corte. Incluso una fecha anterior al corte no demuestra qué versión era conocida entonces. Sin snapshots históricos verificables no se puede convertir este experimento en una prueba histórica real.

## Revisión de hipótesis y decisión

- **Hay datos para evaluar relaciones nuevas entre actores conocidos:** respaldado por 1 843 y 1 879 entidades evaluables en las ventanas propuestas. La evaluación, sin embargo, solo cubre el 31,0 % y 37,8 % de pares nuevos observados.
- **El año de adjudicación permite separar eventos:** respaldado por la conciliación y el control de fechas, para el conjunto actual.
- **El corte reproduce lo disponible históricamente:** no respaldado. Se mantiene únicamente el análisis retrospectivo, sin afirmar ausencia de fuga por disponibilidad.
- **El costo de los modelos es viable:** al momento de la auditoría aún no estaba validado. Posteriormente se ejecutó vecindario por bloques, ALS y el prototipo textual con las cotas y límites indicados más abajo; estas estimaciones no miden el pico completo del proceso.

Se puede avanzar a la preparación de entrenamiento y evaluación bajo estas restricciones. Debe repetirse esta revisión antes de pasar al baseline; si cambian entradas, exclusiones o ventanas, hay que ejecutar nuevamente la auditoría y revisar la decisión.

## Preparación y validación de 2023

La preparación con Spark publica `data/processed/recommendation/`, con una matriz dispersa por corte, diccionarios creados solo del entrenamiento y pares futuros clasificados como repetidos, fríos o positivos elegibles. El universo candidato es el catálogo de entrenamiento menos el historial de cada entidad; no se materializa su producto cartesiano. Las sumas reproducen los conteos de la auditoría: 9 806 positivos y 1 843 entidades en 2023; 10 038 y 1 879 en 2024. Se mantienen los 35 registros sin fecha como exclusiones y la disponibilidad histórica sigue sin verificarse.

En validación, todos los métodos usan los mismos positivos y candidatos y evalúan únicamente las 1 843 entidades con positivos elegibles. Los resultados son medias por entidad, no porcentajes de relevancia real:

| Método | Recall@10 | NDCG@10 | Recall@20 | NDCG@20 | Entidades con ranking | Cobertura del catálogo a 20 |
|---|---:|---:|---:|---:|---:|---:|
| Popularidad | 0,0257 | 0,0217 | 0,0342 | 0,0238 | 1 843 | 0,12 % |
| Vecindario, 50 vecinos y reducción 20 | 0,0232 | 0,0282 | 0,0335 | 0,0297 | 1 607 | 33,53 % |
| ALS, 16 factores | 0,0555 | 0,0558 | 0,0760 | 0,0607 | 1 843 | 4,36 % |
| ALS, 32 factores | 0,0536 | 0,0550 | 0,0809 | 0,0624 | 1 843 | Ver metadatos |

ALS se seleccionó por NDCG@10 de validación, con desempate por menor rango: 16 factores, regularización 0,1, alpha 10, 10 iteraciones y semilla 42. Vecindario usa la configuración inicial fija; no se optimizó una rejilla. Un ranking vacío aporta métricas cero; la popularidad se concentra en 34 proveedores distintos. La mejora de ALS es una comparación en validación y no corrige sesgos de disponibilidad o de identidad.

La primera implementación de vecindario estimaba más memoria de la permitida para el corte de 2024. Se cambió a bloques de proveedores, limitando el tamaño estimado por bloque; al repetir 2023 se obtuvieron las mismas métricas. El cálculo de 2024 terminó con 4 848 311 pares de coocurrencias antes de agrupar y una cota estimada máxima por bloque de 12 433 056 bytes. La estimación no mide el pico completo del proceso.

## Prueba retrospectiva de 2024 y revisión de hipótesis

Se reentrenó ALS con la configuración elegida en 2023 y se compararon las tres salidas sin volver a seleccionar parámetros sobre 2024. La población son 1 879 entidades con al menos un positivo elegible, de un catálogo de entrenamiento de 47 563 proveedores.

| Método | Recall@10 | Precision@10 | NDCG@10 | Recall@20 | NDCG@20 | Entidades con ranking | Proveedores distintos a 20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Popularidad | 0,0303 | 0,0133 | 0,0252 | 0,0424 | 0,0282 | 1 879 | 29 (0,06 %) |
| Vecindario | 0,0544 | 0,0276 | 0,0554 | 0,0762 | 0,0606 | 1 785 | 10 402 (21,87 %) |
| ALS | 0,0748 | 0,0340 | 0,0657 | 0,1087 | 0,0754 | 1 879 | 985 (2,07 %) |

ALS supera las referencias en estas métricas de ranking, pero sus listas son más concentradas que las de vecindario. Vecindario no devuelve ningún resultado para 94 entidades evaluables; no se rellenaron sus listas con popularidad. La mediana de NDCG@10 es cero para los tres métodos, lo que muestra que el resultado medio no representa un acierto para la mayoría de entidades.

El [notebook 06](../notebooks/06_recomendacion.ipynb) contiene segmentos por historial e intervalos bootstrap con 1 000 remuestreos, semilla 42. La diferencia pareada de NDCG@10 de ALS frente a popularidad fue 0,0405, con intervalo aproximado [0,0347; 0,0462]; frente a vecindario fue 0,0103 [0,0035; 0,0172]. Estos intervalos no corrigen dependencia entre entidades, cobertura, identidad ni disponibilidad histórica.

**Revisión al cierre:** la preparación reproducía los conteos de auditoría; los tres métodos se evaluaron sobre los mismos positivos y candidatos; vecindario pudo ejecutarse por bloques; y ALS mejoró el ranking en la prueba retrospectiva. La hipótesis de disponibilidad histórica sigue sin respaldo. No se evaluó arranque en frío ni sustitución por categoría, y dos métodos colaborativos no aclaran la ambigüedad de la rúbrica sobre una posible opción híbrida o de contenido. No convertir esta comparación en una recomendación operativa.

## Revisión de contenido y propuesta exploratoria

El [notebook 07](../notebooks/07_auditoria_contenido.ipynb) revisa únicamente el entrenamiento anterior a 2023 y ejemplos de validación. Los 46 636 eventos tienen categoría y descripción de licitación no vacías, pero solo hay tres categorías amplias. Las 50 647 filas de ítem-proveedor tienen descripción no vacía, aunque 861 tienen menos de diez caracteres; 46 357 (91,5 %) tienen un identificador de clasificación no vacío. Presencia no significa calidad ni demuestra sustitución. Los ejemplos muestran recomendaciones acertadas y fallidas, incluida una entidad para la que vecindario no produjo ranking.

La evidencia justifica probar contenido textual en validación, sin prometer que mejorará al colaborativo: TF-IDF de descripciones de ítems con `min_df=3`, `max_df=0,8`, máximo 30 000 términos, unigramas y bigramas, perfiles de entidad y proveedor construidos solo con ítems anteriores al corte y similitud coseno. La evaluación conservará el catálogo, exclusiones, positivos y métricas de validación 2023. No se añade fallback ni se afirmará equivalencia de productos.

**Independencia de la prueba:** la ventana de 2024 ya fue consultada para comparar otros modelos antes de formular este experimento. La selección y el diseño del nuevo método se limitarán a 2023; una eventual comparación en 2024 será exploratoria y no una nueva prueba final independiente. Para una prueba independiente habría que disponer de otra ventana y datos con cobertura apropiada.

### Resultado y revisión de hipótesis

Se construyeron perfiles con 50 647 descripciones de entrenamiento, 30 000 términos y la configuración anterior. La matriz de eventos se reconcilió con `train`; los ítems futuros no entraron al vocabulario ni a los perfiles. Quedaron con perfil textual 2 687 de 2 691 entidades y 28 818 de 28 878 proveedores de entrenamiento. El tamaño disperso estimado fue 100,5 MB, sin medir todo el pico de memoria del proceso. Las huellas de ambas entradas y de los cortes se registraron en los metadatos.

| Método en validación 2023 | Recall@10 | NDCG@10 | Recall@20 | NDCG@20 | Entidades con ranking | Cobertura de proveedores a 20 |
|---|---:|---:|---:|---:|---:|---:|
| Popularidad | 0,0257 | 0,0217 | 0,0342 | 0,0238 | 1 843 | 0,12 % |
| Vecindario | 0,0232 | 0,0282 | 0,0335 | 0,0297 | 1 607 | 33,53 % |
| ALS seleccionado | 0,0555 | 0,0558 | 0,0760 | 0,0607 | 1 843 | 4,36 % |
| Contenido TF-IDF | 0,0109 | 0,0098 | 0,0210 | 0,0126 | 1 842 | 44,21 % |

**Decisión:** el contenido es factible y amplía la diversidad de proveedores, pero esta configuración no supera el baseline de popularidad en recuperación o NDCG de validación; no se adopta como método principal ni se declara que sustituya a ALS. En el bootstrap pareado por entidad, contenido menos popularidad tuvo una diferencia de NDCG@10 de −0,0119, intervalo aproximado [−0,0152; −0,0082]. Es un resultado exploratorio y no demuestra que todos los enfoques por contenido sean inferiores.

Los casos del notebook muestran una entidad con acierto de ALS, otra sin acierto y sin ranking de vecindario, y ejemplos de las descripciones del historial en las que se basa contenido. En uno de los casos, las descripciones del proveedor y la entidad mencionan trabajos de infraestructura de la misma zona; esto ilustra una posible coincidencia textual, no prueba que los productos o servicios sean sustituibles ni que el proveedor sea apto para contratar.

La prueba de la hipótesis se limita a actores conocidos y a la validación de 2023. Para proveedores nuevos no hay perfil construido en este experimento; sería necesario definir qué textos se conocen antes del corte y un protocolo separado.

## Síntesis para sustentar la Parte III

La pregunta fue si, para una entidad y un catálogo de proveedores observados en entrenamiento, es posible ordenar relaciones todavía no observadas y recuperar algunas que aparecieron después. La señal son conteos de adjudicaciones transformados con `log1p`; no son calificaciones ni preferencias. Se compararon popularidad, vecindario colaborativo y ALS implícito con positivos y candidatos comunes. El vocabulario y los perfiles del prototipo de contenido se construyeron por separado usando ítems de entrenamiento.

En la prueba retrospectiva de 2024, ALS obtuvo NDCG@10 de 0,0657 frente a 0,0554 de vecindario y 0,0252 de popularidad para 1 879 entidades evaluables. Vecindario recomendó una variedad mayor de proveedores, pero no devolvió ninguna opción a 94 entidades. Las medianas de NDCG fueron cero: la media no implica que la mayoría de entidades obtuviera un acierto. El contenido obtuvo NDCG@10 de 0,0098 en validación 2023, inferior a popularidad, aunque alcanzó mayor cobertura de catálogo. No es una comparación de contenido en la prueba 2024.

Los datos no observados en la ventana no son negativos confirmados. La evaluación de relaciones nuevas solo cubre 31,0 % y 37,8 % de esos pares observados en los períodos de 2023 y 2024, respectivamente; no representa actores fríos. Hay identificadores sin resolver y la disponibilidad histórica de los releases no se ha reconstruido. En consecuencia, los resultados describen patrones retrospectivos de una fuente parcial: no demuestran idoneidad, capacidad, equivalencia de proveedores ni justifican decisiones de contratación. La comparación de contenido en una prueba verdaderamente independiente requiere otro período apropiado y una revisión explícita de la disponibilidad de sus datos.

La descripción del enunciado exige dos enfoques, cubiertos por vecindario y factores latentes; el prototipo por contenido añade un tercero. La rúbrica menciona una opción híbrida o ANN, cuya obligatoriedad no queda clara. No se ha implementado un híbrido ni una búsqueda aproximada; si el docente los exige específicamente, ese requisito permanece abierto.

### Conclusiones y alcance de la decisión

1. **La hipótesis principal tiene apoyo limitado:** para relaciones nuevas entre actores ya conocidos y dentro de esta fuente, ALS ordenó mejor las relaciones observadas que las dos referencias en la prueba retrospectiva de 2024. Su ventaja sobre vecindario fue de 0,0103 puntos de NDCG@10; no equivale a una probabilidad de éxito ni demuestra capacidad predictiva prospectiva.
2. **Exactitud y cobertura no cuentan la misma historia:** ALS recuperó en promedio 7,48 % de los positivos elegibles a 10, pero recomendó 985 proveedores distintos a 20, frente a 10 402 de vecindario. Vecindario produjo listas vacías para 94 entidades. Ningún método domina todos los criterios; la mediana de NDCG@10 fue cero para los tres.
3. **El contenido aporta una hipótesis de diversidad, no una mejora validada:** el TF-IDF probado cubrió 44,21 % de proveedores en validación 2023, pero quedó por debajo de popularidad en NDCG@10. No se trasladan esas cifras a 2024 ni se infiere que textos parecidos identifiquen proveedores sustituibles o aptos.
4. **Los resultados tienen población y tiempo acotados:** la evaluación excluye pares con actores fríos y cubre 37,8 % de los pares nuevos observados en 2024; la fuente es parcial y los IDs pueden estar fragmentados. Las fechas de adjudicación separan eventos, pero los releases actuales no prueban la información disponible en cada corte. Por ello no se descarta fuga por disponibilidad y no se justifica desplegar estas listas para contratar.
5. **Para mejorar la evidencia** habría que resolver identidades con validación, reconstruir snapshots anteriores a cada corte, evaluar por separado el arranque en frío y revisar compatibilidad por categoría con información disponible en ese momento. Una ventana posterior independiente permitiría contrastar el contenido; un híbrido o ANN requeriría su propio protocolo y no está implementado. La rúbrica menciona híbrido o ANN de modo más estricto que el texto principal: confirmar ese requisito antes de dar por satisfecho el criterio académico completo.

Fuente de los archivos analizados: OCDS de contrataciones públicas de Perú, OECE/OSCE, licencia CC BY 4.0; las versiones descargadas y sus huellas están en `data/raw/manifest.json`. Los hallazgos no deben interpretarse como acusaciones, preferencias de compra ni evaluación legal de proveedores.

### Comprobación posterior al error de Docker

Tras un error de arranque de Docker Desktop relacionado con `sailor-ingest.sock`, el motor volvió a responder. Se verificaron los marcadores `_SUCCESS`, las huellas de las entradas inmediatas y las métricas almacenadas de los cinco experimentos de recomendación; las 38 pruebas locales pasaron. Se ejecutó el módulo de contenido en Docker, usando las tablas actuales y una salida separada en `artifacts/docker_check_content_20261025`: las huellas, métricas, diagnóstico y 36 836 recomendaciones coincidieron con Windows. No se modificó el socket para esta comprobación. **Esto valida el módulo de contenido con las entradas existentes, no una reproducción integral desde los archivos originales ni todos los modelos en Docker.**

Posteriormente se verificaron tamaño y SHA-256 de los raw de 2023 y 2024 frente al manifiesto y se regeneró de forma aislada la cadena necesaria para recomendación con la imagen Docker corregida `sha256:0542dac85c022db56e157d67a3c5ed909d6bf0fde902600b21e2c0201140c22b`: ítems, adjudicaciones, adjudicación-proveedor, cortes, popularidad, vecindario, ALS, prueba 2024 y contenido. Una primera llamada a adjudicación-proveedor usó un argumento incorrecto; se corrigió y se retomó desde las tablas ya generadas, con la misma imagen, en otro contenedor. Las salidas se guardaron en `artifacts/docker_final_part3_20261025`, sin sobrescribir la referencia.

Se compararon todas las columnas de las tres tablas, matrices, diccionarios y pares futuros de ambos cortes con la réplica aislada anterior, ya contrastada con la referencia de Windows. Coincidieron los rankings y métricas por entidad de todos los métodos, incluidas 110 620 filas de rankings de la prueba y 36 836 del contenido; las métricas y diagnósticos publicados también coincidieron. La comparación ordena las filas y admite tolerancia numérica de 1e-12: no exige Parquet ni huellas de archivos idénticos byte a byte. Esta réplica cubre la cadena directa de la Parte III, no todas las etapas de las Partes I y II ni una ejecución en otra máquina.

Durante la reproducción previa ALS había fallado porque la imagen no tenía `setuptools`, necesario para importar `distutils` en PySpark ML con Python 3.12. Se fijó la dependencia y se incorporó al validador una importación real de ALS; la ejecución posterior utilizó la imagen reconstruida. Al terminar se volvieron a verificar el tamaño y SHA-256 de los raw; las 38 pruebas locales y Ruff pasaron. Los comandos de reproducción están en [ComandosEjecutarOrdenReplica.md](ComandosEjecutarOrdenReplica.md).

## Reproducción local

Con las tablas publicadas y el entorno Python 3.12 del proyecto, ejecutar en este orden:

```powershell
python -m src.features.build_recommendation
python -m src.models.recommendation_baseline
python -m src.models.recommendation_neighbors
python -m src.models.recommendation_als
python -m src.models.recommendation_test
python -m src.models.recommendation_content
```

Cada comando rechaza salidas existentes salvo `--overwrite`. `recommendation_test` aplica la configuración elegida en validación a la prueba; no usar sus resultados para ajustar el modelo y seguir llamándola prueba final. El módulo de contenido se formuló después de observar esa prueba y solo publica validación 2023. Abrir los notebooks [05](../notebooks/05_auditoria_recomendacion.ipynb), [06](../notebooks/06_recomendacion.ipynb) y [07](../notebooks/07_auditoria_contenido.ipynb) para auditoría e interpretación. Los notebooks no publican modelos ni alteran datos fuente. Los resultados dependen de las entradas y del entorno; ALS no garantiza igualdad bit a bit entre plataformas.
