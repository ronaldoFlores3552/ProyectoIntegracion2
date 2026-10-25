# Proyecto Integrador 2

Análisis de grafos, clustering, recomendación y aprendizaje de representaciones
sobre contrataciones públicas del Perú en formato OCDS.

## Replicación

Las instrucciones para Windows, Linux y macOS están en
[docs/ComandosEjecutarOrdenReplica.md](docs/ComandosEjecutarOrdenReplica.md).

El contexto, la arquitectura objetivo, las decisiones, el plan de trabajo y la
bitácora de relevo están en
[docs/README_Estrategico.md](docs/README_Estrategico.md).

El control técnico de calidad y la ruta del análisis exploratorio están en
[docs/PlanFase2CalidadEDA.md](docs/PlanFase2CalidadEDA.md). El análisis narrado
se realiza en [notebooks/01_calidad_y_eda.ipynb](notebooks/01_calidad_y_eda.ipynb)
y solo lee artefactos ya publicados.

La formulación de las tablas y representaciones que preceden a los modelos está
en [docs/PlanFase3Representaciones.md](docs/PlanFase3Representaciones.md).

La fuente de datos es OECE/OSCE mediante el Registro OCDS, bajo licencia CC BY
4.0. Los datos y artefactos regenerables no se versionan: el descargador
conserva URL, fecha y checksum en un manifiesto.
