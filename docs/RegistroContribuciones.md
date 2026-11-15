# Registro de contribuciones

La traza verificable es el historial de commits del repositorio
(`git log --no-merges --format='%h %an %ad %s' --date=short`). La tabla resume lo que
cada integrante aportó según esos commits. Completar la columna de nombre y revisar la
descripción antes de la entrega.

| Usuario en git | Nombre | Aporte principal | Commits de referencia |
|---|---|---|---|
| `ronaldoFlores3552` | Ronaldo Dylan Flores Soto | Entorno reproducible (Docker, versiones, validación), ingesta con manifiesto, `fact_award_item`, `fact_award`, `fact_award_supplier`, interacciones anuales, evidencia de identidad, representaciones de la Parte I, clustering inicial de la Parte II, cadena de recomendación de la Parte III (popularidad, vecindario, ALS, contenido) y notebooks 01 a 07. | `c7cec37` a `fa65ac4` |
| `IsaacVera10` / `Isaac Vera Romero` | Isaac Vera Romero | Replanteamiento de las preguntas P1 y P2 con medición de participantes en la fuente; tablas `fact_tender`, `fact_tenderer` y `dim_buyer`; unidad comprador × segmento × modalidad y análisis de P1 con bootstrap y nulo; grafos de P2; HITS y PageRank; Louvain; perfiles renovados de compradores; SVD y convergencia; híbrido ALS + TF-IDF; particiones exactas, BigCLAM, t-SNE sobre SVD, sustitutos por segmento, reporte web interactivo y documentación de resultados. | `8ef6a14`, `916b29e`, `e29c486`, `8a03dd5`, `5f3fbf5`, `146443c`, `1ef6410` y siguientes |
| `NotRtro` | Rodo Vilcarromero | Reproducción local del replanteamiento con corrección de lectura UTF-8, reporte de reproducción, diagnóstico de la proyección P2 (componentes y nodos de grado 1), modelo nulo Curveball de comunidades, actualización de notebooks y contratos, generador del informe PDF y verificador de consistencia de la entrega. | `7b4e71e`, `4db2be2`, `1bf6727`, `939fbe1`, `fcb14da` |

El commit `8974503` (notebooks 08 y 09, BigCLAM inicial de Puno) figura con la cuenta
`IsaacVera10`; confirmar su autoría material antes de la entrega. Su BigCLAM se unificó
después en `src/models/bigclam_p2.py`.

El commit `d9a51b3` solo versiona documentos que existían localmente (README de las
Partes I a III, planes y guías); su autoría de contenido corresponde a los commits y
fechas originales del trabajo.
