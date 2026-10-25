# Ejecución reproducible del proyecto

Todos los comandos se ejecutan desde la raíz del repositorio. Los datos y los
artefactos se regeneran; no se incluyen en Git. La primera tabla, definida en
[ContratoDatos.md](ContratoDatos.md), tiene el grano proceso × adjudicación ×
proveedor × ítem y se publica en `data/processed/fact_award_item/`.

## 0. Antes de empezar

Se necesita Git y al menos 5 GB libres. Actualice primero la rama `main` que
contiene los scripts de prevención para Windows:

~~~bash
git pull
~~~

Elija **una sola ruta** y sígala de arriba abajo. No mezcle una ruta local con
la ruta de Docker.

| Ruta | Cuándo elegirla | Requisitos locales |
|---|---|---|
| A. Docker (recomendada) | Cualquier sistema; evita diferencias de Python, Java y Hadoop. | Docker Desktop/Engine y Docker Compose v2. |
| B. Windows local | Necesita ejecutar Spark fuera de Docker. | Python 3.12.x, Java 17 y Visual C++ 2010 x64 si lo solicita el control. |
| C. Linux/macOS local | Tiene Python 3.12.x y Java 17 instalados. | Python 3.12.x y Java 17. |

PySpark 3.5.6 incluye Hadoop 3.3.4. En Windows, los helpers 3.3.5 usados por el
proyecto están verificados como compatibles. Linux, macOS y Docker no necesitan
`winutils.exe` ni `hadoop.dll`.

## 1. Ruta A — Docker (recomendada)

Docker fija Python 3.12 y Java 17. El contenedor monta el repositorio: los datos
descargados y el Parquet creado quedan en su directorio local. No ejecute aquí
comandos de Python locales.

1. Compruebe que el daemon responde.

   ~~~bash
   docker info
   ~~~

   Punto de control: el comando muestra información del servidor y termina con
   código 0. Si falla, abra Docker Desktop y espere hasta que indique
   `running`; después repita este mismo comando antes de avanzar.

2. Construya la imagen.

   ~~~bash
   docker compose build pipeline
   ~~~

   Punto de control: finaliza con código 0 y la imagen
   `proyecto-integrador-2:pipeline` queda creada.

3. Valide el entorno del contenedor.

   ~~~bash
   docker compose run --rm pipeline
   ~~~

   Punto de control: aparece `Entorno válido para iniciar el pipeline.`

4. Descargue los datos de 2023 y 2024.

   ~~~bash
   docker compose run --rm pipeline python scripts/download_data.py --years 2023 2024
   ~~~

   Punto de control: aparece `Manifiesto actualizado:` y se crea o actualiza
   `data/raw/manifest.json`.

5. Construya y publique la tabla.

   ~~~bash
   docker compose run --rm pipeline python -m src.processing.build_fact_award_item --years 2023 2024 --overwrite
   ~~~

   Punto de control: aparece `Tabla creada:` y el comando termina con código 0.

6. Genere el perfil técnico de calidad que usará el notebook.

   ~~~bash
   docker compose run --rm pipeline python -m src.quality.profile_fact_award_item --overwrite
   ~~~

   Punto de control: aparecen `Perfil creado:` y `Perfil publicado:`; el comando
   termina con código 0.

7. Construya la tabla de adjudicaciones sin repetición por ítem.

   ~~~bash
   docker compose run --rm pipeline python -m src.processing.build_fact_award --overwrite
   ~~~

   Punto de control: aparece `Tabla creada:` y el comando termina con código 0.

8. Construya la tabla de adjudicación–proveedor.

   ~~~bash
   docker compose run --rm pipeline python -m src.processing.build_fact_award_supplier --overwrite
   ~~~

   Punto de control: aparece `Tabla creada:` y el comando termina con código 0.

9. Construya las interacciones anuales por proveedor y categoría.

   ~~~bash
   docker compose run --rm pipeline python -m src.features.build_interactions --overwrite
   ~~~

   Punto de control: aparecen dos líneas `Tabla creada:` y una
   `Corrida de interacciones:`. El comando termina con código 0.

10. Extraiga evidencia de identidad y construya los artefactos de la Parte I.

    ~~~bash
    docker compose run --rm pipeline python -m src.processing.build_identity_evidence --years 2023 2024 --overwrite
    ~~~

    Punto de control: aparece `Evidencia publicada:` y termina con código 0.

    ~~~bash
    docker compose run --rm pipeline python -m src.features.build_part1 --overwrite
    ~~~

    Punto de control: aparece `Parte I publicada:` y termina con código 0.

11. Compruebe las publicaciones completas.

   ~~~bash
   docker compose run --rm pipeline test -f data/processed/fact_award_item/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

   ~~~bash
   docker compose run --rm pipeline test -f data/processed/fact_award_supplier/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

   ~~~bash
   docker compose run --rm pipeline test -f data/processed/fact_award/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

   ~~~bash
   docker compose run --rm pipeline test -f artifacts/quality/fact_award_item/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

   ~~~bash
   docker compose run --rm pipeline test -f data/processed/entity_supplier_year/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

   ~~~bash
   docker compose run --rm pipeline test -f data/processed/entity_category_year/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

   ~~~bash
   docker compose run --rm pipeline test -f data/processed/identity_evidence/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

   ~~~bash
   docker compose run --rm pipeline test -f data/processed/part1/_SUCCESS
   ~~~

   Punto de control: termina con código 0 y no imprime errores.

## 2. Ruta B — Windows local (PowerShell)

Abra PowerShell en la raíz del repositorio. Esta ruta usa Python **3.12.x** (no
3.13 ni 3.14), Java 17 y PySpark 3.5.6. No avance cuando un punto de control
indique un error.

1. Compruebe Python 3.12.

   ~~~powershell
   py -3.12 --version
   ~~~

   Punto de control: debe mostrar `Python 3.12.x`. Si no aparece, instale
   Python 3.12, abra una terminal nueva y repita este paso. No use otra versión.

2. Compruebe Java 17.

   ~~~powershell
   java -version
   ~~~

   Punto de control: debe aparecer una versión `17`. Si no aparece, instale
   Java 17 de 64 bits, abra una terminal nueva y repita este paso.

3. Cree el entorno virtual.

   ~~~powershell
   py -3.12 -m venv .venv312
   ~~~

   Punto de control: se crea el directorio `.venv312`. Si falla, corrija la
   instalación de Python 3.12 antes de continuar.

4. Active el entorno.

   ~~~powershell
   .\.venv312\Scripts\Activate.ps1
   ~~~

   Punto de control: el prompt empieza por `(.venv312)`. Si PowerShell bloquea
   el script de activación, consulte la sección **Solución de problemas**.

5. Actualice pip.

   ~~~powershell
   python -m pip install --upgrade pip
   ~~~

   Punto de control: termina con código 0 y `python --version` sigue siendo
   3.12.x.

6. Instale las dependencias fijadas del proyecto.

   ~~~powershell
   pip install -r requirements.txt
   ~~~

   Punto de control: termina con código 0, sin compilación fallida de pandas o
   Meson. Si ve esos errores, no continúe: consulte **Solución de problemas**.

7. Prepare y compruebe los helpers nativos de Windows antes de iniciar Spark.

   ~~~powershell
   python scripts/setup_windows_hadoop.py
   ~~~

   Punto de control: debe terminar con
   `Helpers nativos verificados (hash, carga de hadoop.dll y winutils.exe)`.
   El script descarga `winutils.exe` y `hadoop.dll` a
   `.tools/hadoop-3.3.5/bin/` y verifica sus SHA-256. Si informa que falta
   `MSVCR100.dll`, ejecute el siguiente comando, abra una terminal nueva,
   reactive `.venv312` y verifique de nuevo con `--check`:

   ~~~powershell
   winget install --id Microsoft.VCRedist.2010.x64 --exact
   ~~~

   ~~~powershell
   python scripts/setup_windows_hadoop.py --check
   ~~~

   Si el control sigue fallando, use la Ruta A. No avance hasta que pase. No
   copie DLLs a `C:\Windows\System32` ni defina `HADOOP_HOME` permanentemente:
   los scripts usan solo el helper verificado dentro de su propio proceso.

8. Valide todos los requisitos del proyecto.

   ~~~powershell
   python scripts/validate_environment.py
   ~~~

   Punto de control: aparece `Entorno válido para iniciar el pipeline.` Si no
   aparece, resuelva el mensaje mostrado antes de continuar.

9. Descargue o valide los datos fuente.

   ~~~powershell
   python scripts/download_data.py --years 2023 2024
   ~~~

   Punto de control: aparece `Manifiesto actualizado:`. Si los archivos ya
   coinciden con el checksum registrado, verá `[omitido]` y es correcto.

10. Ejecute las pruebas.

    ~~~powershell
    pytest
    ~~~

    Punto de control: termina sin fallos.

11. Revise el estilo.

    ~~~powershell
    ruff check .
    ~~~

    Punto de control: aparece `All checks passed!`.

12. Construya y publique la tabla.

    ~~~powershell
    python -m src.processing.build_fact_award_item --years 2023 2024 --overwrite
    ~~~

    Punto de control: aparece `Tabla creada:` y termina con código 0.

13. Genere el perfil técnico de calidad que usará el notebook.

    ~~~powershell
    python -m src.quality.profile_fact_award_item --overwrite
    ~~~

    Punto de control: aparecen `Perfil creado:` y `Perfil publicado:`; el comando
    termina con código 0.

14. Construya la tabla de adjudicaciones sin repetición por ítem.

    ~~~powershell
    python -m src.processing.build_fact_award --overwrite
    ~~~

    Punto de control: aparece `Tabla creada:` y termina con código 0.

15. Construya la tabla de adjudicación–proveedor.

    ~~~powershell
    python -m src.processing.build_fact_award_supplier --overwrite
    ~~~

    Punto de control: aparece `Tabla creada:` y termina con código 0.

16. Construya las interacciones anuales por proveedor y categoría.

    ~~~powershell
    python -m src.features.build_interactions --overwrite
    ~~~

    Punto de control: aparecen dos líneas `Tabla creada:` y una
    `Corrida de interacciones:`. El comando termina con código 0.

17. Extraiga evidencia de identidad y construya los artefactos de la Parte I.

    ~~~powershell
    python -m src.processing.build_identity_evidence --years 2023 2024 --overwrite
    ~~~

    Punto de control: aparece `Evidencia publicada:` y termina con código 0.

    ~~~powershell
    python -m src.features.build_part1 --overwrite
    ~~~

    Punto de control: aparece `Parte I publicada:` y termina con código 0.

18. Verifique que las publicaciones terminaron completamente.

    ~~~powershell
    Test-Path data\processed\fact_award_item\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`.

    ~~~powershell
    Test-Path data\processed\fact_award_supplier\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`.

    ~~~powershell
    Test-Path data\processed\fact_award\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`.

    ~~~powershell
    Test-Path artifacts\quality\fact_award_item\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`. Solo entonces las tablas y el
    perfil están listos para el notebook.

    ~~~powershell
    Test-Path data\processed\entity_supplier_year\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`.

    ~~~powershell
    Test-Path data\processed\entity_category_year\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`.

    ~~~powershell
    Test-Path data\processed\identity_evidence\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`.

    ~~~powershell
    Test-Path data\processed\part1\_SUCCESS
    ~~~

    Punto de control: debe devolver `True`.

## 3. Ruta C — Linux/macOS local (bash)

Abra una terminal en la raíz del repositorio. Esta ruta necesita Python 3.12.x y
Java 17; no usa los helpers de Windows.

1. Compruebe Python.

   ~~~bash
   python3.12 --version
   ~~~

   Punto de control: debe mostrar `Python 3.12.x`.

2. Compruebe Java.

   ~~~bash
   java -version
   ~~~

   Punto de control: debe mostrar una versión `17`.

3. Cree el entorno virtual.

   ~~~bash
   python3.12 -m venv .venv312
   ~~~

   Punto de control: se crea `.venv312`.

4. Active el entorno.

   ~~~bash
   source .venv312/bin/activate
   ~~~

   Punto de control: el prompt muestra `(.venv312)`.

5. Actualice pip.

   ~~~bash
   python -m pip install --upgrade pip
   ~~~

   Punto de control: termina con código 0.

6. Instale las dependencias.

   ~~~bash
   pip install -r requirements.txt
   ~~~

   Punto de control: termina con código 0.

7. Valide el entorno.

   ~~~bash
   python scripts/validate_environment.py
   ~~~

   Punto de control: aparece `Entorno válido para iniciar el pipeline.`

8. Descargue o valide los datos fuente.

   ~~~bash
   python scripts/download_data.py --years 2023 2024
   ~~~

   Punto de control: aparece `Manifiesto actualizado:`.

9. Ejecute las pruebas.

   ~~~bash
   pytest
   ~~~

   Punto de control: termina sin fallos.

10. Revise el estilo.

    ~~~bash
    ruff check .
    ~~~

    Punto de control: aparece `All checks passed!`.

11. Construya y publique la tabla.

    ~~~bash
    python -m src.processing.build_fact_award_item --years 2023 2024 --overwrite
    ~~~

    Punto de control: aparece `Tabla creada:` y termina con código 0.

12. Genere el perfil técnico de calidad que usará el notebook.

    ~~~bash
    python -m src.quality.profile_fact_award_item --overwrite
    ~~~

    Punto de control: aparecen `Perfil creado:` y `Perfil publicado:`; el comando
    termina con código 0.

13. Construya la tabla de adjudicaciones sin repetición por ítem.

    ~~~bash
    python -m src.processing.build_fact_award --overwrite
    ~~~

    Punto de control: aparece `Tabla creada:` y termina con código 0.

14. Construya la tabla de adjudicación–proveedor.

    ~~~bash
    python -m src.processing.build_fact_award_supplier --overwrite
    ~~~

    Punto de control: aparece `Tabla creada:` y termina con código 0.

15. Construya las interacciones anuales por proveedor y categoría.

    ~~~bash
    python -m src.features.build_interactions --overwrite
    ~~~

    Punto de control: aparecen dos líneas `Tabla creada:` y una
    `Corrida de interacciones:`. El comando termina con código 0.

16. Extraiga evidencia de identidad y construya los artefactos de la Parte I.

    ~~~bash
    python -m src.processing.build_identity_evidence --years 2023 2024 --overwrite
    ~~~

    Punto de control: aparece `Evidencia publicada:` y termina con código 0.

    ~~~bash
    python -m src.features.build_part1 --overwrite
    ~~~

    Punto de control: aparece `Parte I publicada:` y termina con código 0.

17. Compruebe las publicaciones completas.

    ~~~bash
    test -f data/processed/fact_award_item/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

    ~~~bash
    test -f data/processed/fact_award_supplier/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

    ~~~bash
    test -f data/processed/fact_award/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

    ~~~bash
    test -f artifacts/quality/fact_award_item/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

    ~~~bash
    test -f data/processed/entity_supplier_year/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

    ~~~bash
    test -f data/processed/entity_category_year/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

    ~~~bash
    test -f data/processed/identity_evidence/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

    ~~~bash
    test -f data/processed/part1/_SUCCESS
    ~~~

    Punto de control: termina con código 0.

## 4. Criterio de éxito común

El flujo técnico y de calidad termina correctamente solo si el comando de
construcción devuelve código 0, imprime `Tabla creada: ...` y existe
`data/processed/fact_award_item/_SUCCESS`, debe existir
`data/processed/fact_award/_SUCCESS` y
`data/processed/fact_award_supplier/_SUCCESS`. Las dos tablas de interacción
deben contener `_SUCCESS` y sus `_metadata.json` deben tener el mismo `run_id`;
además, el perfil debe imprimir
`Perfil publicado: ...` y publicar
`artifacts/quality/fact_award_item/_SUCCESS`. Spark escribe primero en
`data/processed/.fact_award_item.staging/` y publica el directorio final solo al
encontrar `_SUCCESS`.

La extracción de identidad debe imprimir `Evidencia publicada: ...` y crear
`data/processed/identity_evidence/_SUCCESS` junto con `_metadata.json`. El
proceso puede tardar varios minutos: espere a que termine y vuelva el prompt.
Sus grupos son candidatos de revisión, no identidades fusionadas.

La construcción de representaciones debe imprimir `Parte I publicada: ...` y
crear `data/processed/part1/_SUCCESS`. Por defecto usa adjudicaciones de 2023 a
2024, cinco vecinos y un límite de 10 millones de pares; consulte su README
para interpretar el resultado y ajustar recursos.

Como referencia, con los archivos 2023/2024 cuyos SHA-256 figuran en
`data/raw/manifest.json`, se obtuvieron 137 292 filas, 119 762 procesos, 128 395
adjudicaciones, 62 919 proveedores y 2 967 entidades. Si la fuente pública una
versión distinta, las cifras pueden variar.

## 4.1. Abrir el notebook de calidad y EDA

Después de construir las tablas y generar el perfil de calidad, abra JupyterLab:

~~~powershell
python -m jupyter lab
~~~

Abra `notebooks/01_calidad_y_eda.ipynb`. El notebook lee los artefactos
publicados y sirve para gráficos, hipótesis y anotaciones; no reemplaza el
pipeline ni modifica `data/processed/`.

Para examinar posibles inconsistencias de identificadores y nombres, abra
`notebooks/02_diagnostico_resolucion_entidades.ipynb` en la misma sesión. Es
exploratorio: las coincidencias que muestra no se fusionan automáticamente.
La revisión de referencias sin cruce vuelve a verificar los hashes y leer los
archivos originales completos; puede tardar varios minutos. La muestra de
nombres compartidos se ordena de forma determinista y no es representativa.

## 5. Recuperación de una salida incompleta

- Si falta `_SUCCESS`, ejecute de nuevo el comando de construcción con
  `--overwrite`.
- Los directorios `.fact_award_item.staging/`, `.fact_award.staging/`,
  `.fact_award_supplier.staging/`, `fact_award_item.previous/`,
  `fact_award.previous/` y `fact_award_supplier.previous/` que queden en
  `data/processed/` tras una interrupción se pueden borrar.
- Sin `--overwrite`, el script se niega a escribir si la salida ya existe.
- `--overwrite` solo modifica la salida del comando ejecutado en
  `data/processed/`; nunca toca `data/raw/`.
- Las interacciones se publican atómicamente por separado. Si falta una salida o
  sus `_metadata.json` tienen distinto `run_id`, repita `build_interactions`
  con `--overwrite` para regenerar ambas en la misma corrida.
- Si se interrumpe la extracción de identidad, puede borrar los directorios
  sobrantes `.identity_evidence.staging/` e `identity_evidence.previous/` en
  `data/processed/` y repetir su comando con `--overwrite`.

## 6. Convenciones de almacenamiento

~~~text
data/raw/        JSONL.GZ originales y manifest.json
data/interim/    resultados temporales de transformación
data/processed/  Parquet limpio y modelado
artifacts/       modelos, métricas y datos para la web
~~~

No modifique manualmente los archivos descargados. El manifiesto conserva la procedencia y permite verificar los checksums.

## 7. Fuente y licencia

- Registro OCDS: <https://data.open-contracting.org/es/publication/135>
- Descargas OECE/OSCE: <https://contratacionesabiertas.oece.gob.pe/descargas>
- Licencia: CC BY 4.0

## 8. Estado de los comandos

| Comando | Estado | Función |
|---|---|---|
| `validate_environment.py` | Disponible | Comprueba Python, Java y paquetes básicos |
| `download_data.py` | Disponible | Descarga datos y genera el manifiesto |
| `setup_windows_hadoop.py` | Disponible en Windows | Prepara y verifica los helpers nativos locales (`--check` solo verifica) |
| `pytest` | Disponible | Prueba las utilidades iniciales y la publicación segura de salidas |
| `ruff check .` | Disponible | Revisa estilo e imports |
| `build_fact_award_item` | Disponible | Construye `data/processed/fact_award_item/` (Parte I) |
| `build_fact_award` | Disponible | Construye `data/processed/fact_award/` con una fila por adjudicación |
| `build_fact_award_supplier` | Disponible | Construye `data/processed/fact_award_supplier/` con una fila por adjudicación–proveedor |
| `build_interactions` | Disponible | Publica interacciones anuales por proveedor y categoría y sus metadatos |
| `build_identity_evidence` | Disponible | Extrae evidencia OCDS y candidatos de identidad sin fusionar ID |
| `build_part1` | Disponible | Publica vectores, matriz dispersa y grafo KNN con Spark |
| `profile_fact_award_item` | Disponible | Publica el control técnico de calidad para el notebook de EDA |
| `01_calidad_y_eda.ipynb` | Disponible | Explora y documenta hallazgos sin alterar tablas oficiales |
| `02_diagnostico_resolucion_entidades.ipynb` | Disponible | Examina candidatos de identidad sin modificar identificadores |
| `03_particionamiento_spark.ipynb` | Disponible | Analiza filtros, plan Spark y configuraciones de shuffle |
| Resto del pipeline Spark | Pendiente | Se añadirá en la siguiente fase |
| API y frontend | Pendiente | Se añadirán cuando existan artefactos |

## 9. Solución de problemas

Use esta sección únicamente si un punto de control no se cumple.

### `pandas` intenta compilarse; aparece Meson o `vswhere.exe` → Python distinto de 3.12 → crear el entorno correcto

~~~powershell
py -3.12 -m venv .venv312
~~~

Active ese entorno y repita la instalación. No intente corregirlo instalando
Visual Studio: pandas fijado para el proyecto requiere Python 3.12.x.

### `HADOOP_HOME and hadoop.home.dir are unset` → falta o no es válido `winutils.exe` → preparar y verificar helpers

~~~powershell
python scripts/setup_windows_hadoop.py
~~~

No avance hasta recibir el mensaje de helpers verificados.

### `UnsatisfiedLinkError ... NativeIO$Windows.access0` → `hadoop.dll` o `MSVCR100.dll` no se puede cargar → verificar helpers

~~~powershell
python scripts/setup_windows_hadoop.py --check
~~~

Si el resultado menciona `MSVCR100.dll`, instale el redistribuible oficial antes
de repetir el control. Si no se corrige, use Docker.

### Un `HADOOP_HOME` antiguo está definido en el sistema → el proyecto lo ignora, pero hay que validar el helper local → ejecutar el control

~~~powershell
python scripts/setup_windows_hadoop.py --check
~~~

No defina ni cambie `HADOOP_HOME` permanentemente. Durante la construcción, el
script ignora el valor externo y configura el helper del repositorio solo en su
propio proceso.

### Existe `C:\Windows\System32\hadoop.dll` → la JVM puede cargar una DLL ajena → ejecutar el control y retirar esa copia o usar Docker

~~~powershell
python scripts/setup_windows_hadoop.py --check
~~~

El control detecta esa copia. No copie DLLs al directorio del sistema.

### `docker info` falla o no muestra información del servidor → Docker daemon apagado → iniciar Docker Desktop

~~~bash
docker info
~~~

Abra Docker Desktop y espere hasta que indique `running`; después repita el
comando. En Linux, inicie el servicio Docker de su distribución.
