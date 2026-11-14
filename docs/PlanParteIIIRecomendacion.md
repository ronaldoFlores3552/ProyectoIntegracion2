# Parte III — Plan de recomendación entidad–proveedor

**Actualización:** 25 de octubre de 2026, hora de Lima.  
**Estado:** diseño histórico implementado y evaluado localmente para los cortes retrospectivos; los resultados y límites vigentes están en [README_ParteIII.md](README_ParteIII.md). Las cifras exploratorias de este plan son diagnósticos de los archivos locales, no resultados de modelos.

## 1. Pregunta y alcance

**Pregunta principal:** entre proveedores ya observados en los datos disponibles para entrenamiento, ¿qué relaciones entidad–proveedor aún no observadas se pueden ordenar de forma que algunas coincidan con adjudicaciones posteriores del conjunto de datos?

**Pregunta complementaria:** ¿qué proveedores comparten vínculos con entidades similares y cómo cambia esa relación entre categorías y períodos observados? La similitud es una señal histórica, no demuestra que los proveedores sean intercambiables en una contratación concreta.

La unidad de consulta es una **entidad compradora** y la unidad recomendada es un **ID de proveedor**. Se predice una relación observada, no una preferencia, elegibilidad legal, calidad o conveniencia de contratación. El ranking es analítico, no una instrucción para adjudicar. Los identificadores originales pueden estar fragmentados y la fuente no necesariamente cubre todo el mercado.

El [enunciado](Proyecto2Integrador.md) exige señal implícita, al menos dos enfoques de familias diferentes, evaluación e interpretación. La [Parte I](README_ParteI.md) ya construyó tablas de interacción; la [Parte II](README_ParteII.md) usó la ventana completa para una descripción retrospectiva. Sus matrices, diccionarios, clusters y escalas **no se pueden reutilizar como entrenamiento del corte temporal**.

## 2. Señal y construcción de la matriz

- Entrada candidata: `data/processed/fact_award_supplier/`, con `_SUCCESS`; una fila por `process_ocid × award_id × supplier_id`, con entidad y `award_date`. Verificar claves, fechas y huellas antes de usarla. La tabla anual `entity_supplier_year` es una alternativa para los cortes de año propuestos; se deben conciliar ambas antes de confiar en el resultado.
- Para cada corte, agrupar solo eventos anteriores al corte por `entity_id × supplier_id`. La señal `count` es el número de filas proveedor-adjudicación elegibles; para amortiguar relaciones muy frecuentes, usar `r = log1p(count)`. Es una interacción implícita positiva, no un rating. Una adjudicación con varios proveedores contribuye una vez a cada par, por lo que la suma de interacciones no es necesariamente el número de adjudicaciones únicas.
- Conservar por separado las fechas y las claves de evento necesarias para auditoría y para reconstruir los conjuntos. Excluir fecha o ID ausente y cuantificar cada motivo y la unión de exclusiones. No sumar montos ni mezclar monedas. El conteo mide adjudicaciones registradas, no contratos únicos ni valor monetario.
- Crear diccionarios entidad/proveedor **a partir del entrenamiento de cada corte**. Mantener ID originales para auditoría, guardar índices y parámetros junto con esa matriz, y comprobar que ALS pueda representar sus índices enteros. Los diccionarios de la Parte I no se comparten entre cortes.
- La matriz almacenada es dispersa: una fila por par con `count`, `r` e índices, sin materializar una tabla densa de entidad × proveedor. Spark procesa las tablas; una representación dispersa local solo se usa si sus dimensiones y memoria estimada caben, con límites explícitos y verificados antes de cargar. Detener y rediseñar si no caben.

## 3. Cortes temporales y límites de disponibilidad

Se proponen ventanas **por fecha de adjudicación**. Los años de archivo son los de fuente 2023 y 2024, no el año de adjudicación.

| Etapa | Entrenamiento por `award_date` | Positivos posteriores | Uso |
|---|---|---|---|
| Validación | Antes del 01-01-2023 | 01-01-2023 a 31-12-2023 | Elegir parámetros y protocolo. |
| Prueba final | Antes del 01-01-2024 | 01-01-2024 a 31-12-2024 | Reentrenar con la configuración congelada y medir una sola vez. |

La población histórica anterior a 2023 está reconstruida **solo a partir de los archivos de fuente 2023 y 2024 disponibles**; no se asume que represente todas las adjudicaciones anteriores. No usar la prueba para seleccionar modelo, pesos ni umbrales. La selección se basa en la validación; después se reconstruyen matriz, diccionarios y modelos con el entrenamiento de prueba. Una fecha de publicación igual o anterior al corte no basta por sí sola para demostrar qué versión del registro estaba realmente disponible entonces.

**Limitación esencial:** esto es un *hold-out retrospectivo por fecha de adjudicación*, no una reconstrucción validada de la información disponible en 2023 o 2024. `fact_award_supplier` no contiene `release_date` ni `published_date`; para diagnosticar disponibilidad se debe cruzar con `fact_award` por la clave de adjudicación, verificar cardinalidad 1:1 y revisar ambas fechas, nulos y releases posteriores al corte. También verificar qué significan esos campos en la fuente y si hay snapshots históricos íntegros. Sin evidencia de versiones históricas no afirmar ausencia de fuga por disponibilidad, aunque el filtro de adjudicación sea correcto. Si se dispone de snapshots verificables, diseñar por separado una evaluación *as-of* que use exclusivamente versiones disponibles al corte.

### Diagnóstico preliminar local

Inspección de las tablas existentes: tras excluir IDs o años nulos, se compararon pares distintos de cada período con los anteriores. Las cifras dependen de los archivos y no son un resultado del recomendador.

| Corte | Filas de entrenamiento | Filas del período | Pares nuevos en período | Pares nuevos con entidad y proveedor presentes en entrenamiento | Entidades con al menos un par nuevo evaluable |
|---|---:|---:|---:|---:|---:|
| Validación 2023 | 46 636 | 41 759 | 31 616 | 9 806 | 1 843 |
| Prueba 2024 | 88 395 | 39 965 | 26 570 | 10 038 | 1 879 |

En ese diagnóstico hay 21 670 pares nuevos de 2023 y 16 472 de 2024 cuyo proveedor no aparece en el entrenamiento respectivo. Los indicadores de entidad y proveedor fríos pueden solaparse: **no se suman**. Su magnitud hace indispensable reportar cobertura y no presentar la evaluación de proveedores conocidos como una evaluación de todo el mercado. Son conteos preliminares a verificar con el futuro notebook y las reglas definitivas.

## 4. Qué se recomienda y cómo se evalúa

El experimento principal es **descubrimiento de relaciones nuevas**. Para cada entidad conocida al corte:

1. El universo candidato común contiene todos los proveedores conocidos en el entrenamiento, excluidos los proveedores con los que esa entidad ya tuvo al menos una adjudicación de entrenamiento. No se usa una muestra de negativos ni filtros de categoría calculados con el futuro.
2. Un positivo es un par entidad–proveedor que aparece en el período posterior, **no aparecía para esa entidad en entrenamiento** y cuyo proveedor está en el universo candidato. Se agrupa por par, aunque existan varias adjudicaciones posteriores.
3. Los pares repetidos en prueba y los pares con entidad o proveedor nuevos se informan por separado; no se agregan al denominador del experimento principal. Una evaluación de repetición o de arranque en frío se podrá diseñar después con su propia pregunta.
4. Se evalúa el ranking por entidad con al menos un positivo elegible, sobre el mismo universo y positivos para todos los métodos. Una entidad sin positivo elegible no se evalúa con Recall/NDCG, pero se incluye en los reportes de cobertura y exclusión. Los candidatos sin adjudicación futura **no son negativos confirmados**: únicamente son relaciones no observadas en esta ventana.
5. No filtrar el universo con datos del futuro ni calcular similitudes, popularidad o normalización usando la prueba. El hecho de construir retrospectivamente las etiquetas de prueba no autoriza usar sus relaciones para seleccionar candidatos o entrenar.

### Métricas y comparabilidad

Usar inicialmente **K=10 y K=20**, definidos antes de medir; `K_u = min(K, cantidad de candidatos elegibles de la entidad)`. Un método puede devolver menos de `K_u` resultados: las posiciones faltantes cuentan como aciertos cero y se registra el tamaño real del ranking. Un ranking vacío tiene métricas cero para esa entidad evaluable.

- **Recall@K:** positivos distintos recuperados entre los primeros `K_u`, dividido por todos los positivos elegibles de la entidad. Media macro por entidad.
- **Precision@K:** aciertos entre los primeros `K_u`, divididos por `K_u`, para penalizar también posiciones faltantes. Media macro; no llamarla precisión de relevancia real, pues lo no observado no es negativo confirmado.
- **NDCG@K:** ganancia binaria de los positivos observados, con descuento logarítmico y normalización por el orden ideal limitado a `K_u`; media macro por entidad.
- **Cobertura y sesgo:** entidades con ranking nativo no vacío, proveedores distintos recomendados / catálogo entrenado, longitud del ranking, concentración por popularidad y cobertura de positivos frente a todos los pares nuevos. Separar las exclusiones por entidad fría, proveedor frío, ambos, historial y fecha/ID faltante, sin sumar categorías solapadas.
- Comparar además por segmentos de historial de la entidad y popularidad del proveedor, con tamaños por segmento; reportar distribución por entidad y no solo la media. Para incertidumbre usar, si hay suficientes entidades, intervalos bootstrap por entidad con semilla y número de réplicas registrados. Esos intervalos no corrigen sesgos de cobertura ni disponibilidad temporal.

Todos los métodos usan los mismos ID, corte, candidatos y reglas de desempate por `supplier_id`. La comparación principal usa las salidas nativas; no completar silenciosamente recomendaciones faltantes. Si se añade una variante con fallback a popularidad, etiquetarla por separado e informar métricas y cobertura antes y después.

## 5. Baselines y dos enfoques

### Baseline obligatorio: popularidad de entrenamiento

Ordenar proveedores por número de adjudicaciones o entidades distintas **calculado solo con entrenamiento**; elegir y congelar una definición, inicialmente número de entidades distintas. Aplicar el mismo catálogo, excluir vínculos previos y desempatar por ID. Este baseline hace visible cuánto aportan los modelos más allá de recomendar proveedores frecuentes. La comparación con un ranking aleatorio reproducible puede añadirse como referencia secundaria, con semilla fija.

### Enfoque A: vecindario colaborativo proveedor–proveedor

Usar la matriz dispersa de entrenamiento y calcular similitud coseno entre columnas de proveedores a partir de `log1p(count)`. Considerar solo coocurrencias observadas en entrenamiento; reducir similitudes basadas en pocas entidades mediante un factor documentado `n_común / (n_común + 20)` y conservar inicialmente hasta 50 vecinos por proveedor. Puntuar cada proveedor candidato sumando las similitudes con los proveedores históricos de la entidad, ponderadas por la interacción de entrenamiento. El corte de vecinos, factor y ponderación son hipótesis iniciales, a elegir en validación.

La interpretación es que dos proveedores tienen relaciones con entidades parecidas, **no** que entreguen productos equivalentes. Revisar categoría exclusivamente con evidencia de entrenamiento y explicar que categorías amplias no garantizan sustitución. Proteger memoria y expansión por pares: estimar dimensiones y costo de coocurrencias antes de calcular, imponer un límite y detener si se excede; no asumir que una matriz dispersa garantiza un producto pequeño.

### Enfoque B: factores latentes con ALS implícito de Spark

Usar `pyspark.ml.recommendation.ALS` con `implicitPrefs=True` sobre los índices y la señal `log1p(count)` de entrenamiento. Registrar semilla, rango, regularización, iteraciones y `alpha`; la confianza implícita se construye a partir de la señal no negativa y no es una probabilidad de preferencia. Explorar una rejilla pequeña predefinida en validación, por ejemplo rangos 16/32, regularización 0,05/0,1 y `alpha` 10/20, manteniendo fijos los demás parámetros; elegir la combinación con NDCG@10 macro y usar cobertura, Recall y complejidad para interpretar empates y límites. Registrar resultados de todas las combinaciones, no solo el ganador.

Evaluar ALS contra el **mismo catálogo y candidatos** que vecindario. Si se genera un ranking con APIs que devuelven un número limitado de proveedores, recuperar suficientes candidatos para eliminar historial y verificar que el top K resultante sea correcto; si el catálogo o el costo no lo permite, detener y documentar una estrategia exacta o una aproximación evaluada. `coldStartStrategy` no convierte un proveedor o entidad nuevos en evaluables. Fijar semilla y versiones no garantiza bit a bit igualdad entre plataformas.

Ambos enfoques y baseline se comparan con el mismo protocolo. Posteriormente se añadió un prototipo exploratorio por contenido en validación 2023, documentado en [README_ParteIII.md](README_ParteIII.md); la disponibilidad histórica de sus textos no está verificada. Un híbrido sigue sin implementarse.

## 6. Arquitectura y reproducción propuestas

```text
fact_award_supplier + fact_award y huellas
  → auditoría de fecha, disponibilidad y cobertura
  → cortes y eventos → matriz y diccionarios solo de entrenamiento
  → candidatos + positivos congelados por corte
  → popularidad / vecindario / ALS
  → rankings, métricas, cobertura y parámetros con linaje
  → notebook de análisis e interpretación → futuro reporte web
```

| Ubicación propuesta | Responsabilidad |
|---|---|
| `src/` | Código reutilizable de preparación y publicación oficial, experimentos y evaluación; definir nombres y módulos al implementar, evitando scripts de apuntes. |
| `notebooks/` | Un notebook narrado para auditoría temporal, cobertura, comparación e interpretación; no modificar datos fuente. |
| `tests/` | Pruebas pequeñas con eventos sintéticos para cortes, pares nuevos/repetidos, fríos, candidatos, métricas y desempates. |
| `data/processed/` y `artifacts/` | Salidas regenerables; staging, `_SUCCESS`, metadatos con huellas, fuentes, exclusiones, cortes, semillas, versiones y configuraciones. Rutas definitivas y comandos se documentarán solo cuando existan. |
| `docs/` | Contrato del producto real, comandos de réplica y reporte de conclusiones. Este plan conserva las hipótesis previas y el historial. |

Las rutas, comandos y resultados efectivamente implementados se documentan en [README_ParteIII.md](README_ParteIII.md). El reporte web interactivo pertenece a la entrega integral: consumirá artefactos cuando existan; no debe entrenar los modelos al abrir una página.

## 7. Etapas y criterios de aceptación

1. **Auditoría temporal:** verificar datos, claves, fuentes, fechas de publicación y cobertura por corte; reproducir los conteos anteriores y documentar disponibilidad histórica. Sin ello no se afirma una evaluación temporal prospectiva.
2. **Preparación y contrato:** definir exclusiones, cortes, señal, candidatos, positivos, diccionarios y guardas de memoria; publicar de manera reproducible y probar ausencia de cruces entre entrenamiento y período posterior.
3. **Baseline:** ejecutar popularidad de entrenamiento con candidatos comunes y calcular métricas, cobertura y segmentos.
4. **Vecindario:** calcular vecinos dentro de los límites, generar rankings y comparar contra baseline en validación.
5. **ALS:** entrenar rejilla acotada solo en validación, congelar elección, reentrenar antes de 2024 y evaluar una vez; comparar con vecindario y baseline en el mismo conjunto.
6. **Interpretación y cierre:** revisar recomendaciones y su sustento histórico, categorías conocidas, casos fríos, sesgos y sensibilidad; explicar errores y resultados negativos. Actualizar reporte, contrato, comandos, notebook y bitácora. No declarar mejoras sin métricas y cobertura comparables.

**Continuidad:** consultar los resultados y revisión de hipótesis en [README_ParteIII.md](README_ParteIII.md). Se implementó una opción exploratoria de contenido en validación 2023; se mantienen pendientes la evaluación de arranque en frío y la verificación de disponibilidad histórica.
