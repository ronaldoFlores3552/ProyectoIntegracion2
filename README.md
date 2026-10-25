# Proyecto Integrador 2

Análisis de grafos, clustering, recomendación y aprendizaje de representaciones
sobre contrataciones públicas del Perú en formato OCDS.

## Replicación

Las instrucciones para Windows, Linux y macOS están en
[docs/ComandosEjecutarOrdenReplica.md](docs/ComandosEjecutarOrdenReplica.md).

El contexto, la arquitectura objetivo, las decisiones, el plan de trabajo y la
bitácora de relevo están en
[docs/README_Estrategico.md](docs/README_Estrategico.md).

La metodología, resultados, límites y estado de la Parte I están en
[docs/README_ParteI.md](docs/README_ParteI.md).

El diseño propuesto para clustering y anomalías está en
[docs/PlanParteIIClustering.md](docs/PlanParteIIClustering.md). Los resultados
actuales y pendientes están en [docs/README_ParteII.md](docs/README_ParteII.md).

El control técnico de calidad y la ruta del análisis exploratorio están en
[docs/PlanFase2CalidadEDA.md](docs/PlanFase2CalidadEDA.md). El análisis narrado
se realiza en [notebooks/01_calidad_y_eda.ipynb](notebooks/01_calidad_y_eda.ipynb)
y solo lee artefactos ya publicados.

El diagnóstico de posibles inconsistencias de identidad se encuentra en
[notebooks/02_diagnostico_resolucion_entidades.ipynb](notebooks/02_diagnostico_resolucion_entidades.ipynb).
Sus coincidencias son candidatas para revisión, no fusiones automáticas.

La formulación de las tablas y representaciones que preceden a los modelos está
en [docs/PlanFase3Representaciones.md](docs/PlanFase3Representaciones.md).

La fuente de datos es OECE/OSCE mediante el Registro OCDS, bajo licencia CC BY
4.0. Los datos y artefactos regenerables no se versionan: el descargador
conserva URL, fecha y checksum en un manifiesto.
