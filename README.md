# DataRetail 360 — Pipeline ELT

Este proyecto procesa una muestra de ventas y la organiza en una base de datos para poder consultarla y analizarla. Está preparado como demostración académica y utiliza las **2.000 filas incluidas en `data/`**, por lo que no necesitas descargar el conjunto de datos completo.

## ¿Cómo funciona?

El pipeline utiliza una arquitectura **ELT**:

1. Lee el archivo de ventas.
2. Guarda primero los registros en **Bronze** dentro de SQLite.
3. Vuelve a leer Bronze, valida los datos y guarda los registros válidos en **Silver**. Los que no cumplen las reglas quedan separados para su revisión.
4. Lee Silver y crea **Gold**, que contiene las dimensiones y la tabla de hechos para analizar las ventas.
5. Comprueba los resultados y genera un registro y un reporte de cada ejecución.

**Importante sobre la geografía:** la fuente original no contiene ventas verificadas en Chile ni información real de sucursales. Para probar el modelo, se asignan las transacciones de forma determinística a seis sucursales demostrativas de Chile. Por eso, la distribución por país, región y sucursal es simulada y no debe interpretarse como información comercial real.

## Requisitos

- Python 3.10 o posterior.
- Las dependencias indicadas en `requirements.txt`.
- VS Code es opcional, pero recomendado si quieres ejecutar también el notebook.

SQLite viene incluido con Python; no necesitas instalar un servidor de base de datos.

## Instalación en Windows

1. Descomprime el ZIP y abre la carpeta **`DataRetail360_Pipeline`** en VS Code.
2. Abre **Terminal → New Terminal**. Asegúrate de estar en la carpeta donde aparecen `requirements.txt`, `src/` y `data/`.
3. Crea el entorno virtual:

   ```powershell
   py -m venv .venv
   ```

4. Instala las dependencias:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

## Ejecutar el pipeline

Desde esa misma carpeta, ejecuta:

```powershell
.\.venv\Scripts\python.exe -m src.pipeline
```

Con la muestra incluida, el resultado esperado es:

- 2.000 filas cargadas en Bronze.
- 1.992 registros válidos en Silver.
- 8 registros rechazados y guardados para revisión.
- 1.992 hechos cargados en Gold.

Al finalizar, la terminal debería mostrar `Estado: OK`. Se generan la base de datos `dataretail360.db`, los logs en `logs/` y un reporte JSON en `logs/reportes/`.

## Ejecutar las pruebas

Para comprobar el funcionamiento del proyecto, ejecuta:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas verifican el orden ELT (Bronze antes de transformar Silver y Silver antes de construir Gold), las reglas SCD, que repetir la ejecución no duplique hechos y que la muestra funcione correctamente.

## Abrir el notebook en VS Code

1. Abre `notebooks/DataRetail360_demo.ipynb`.
2. Si VS Code lo solicita, instala las extensiones **Python** y **Jupyter**.
3. En **Select Kernel**, elige el Python que está dentro de `.venv`.
4. Pulsa **Run All**.

Abre la carpeta completa `DataRetail360_Pipeline` en VS Code para que el notebook encuentre el código y los datos.

## Archivos de apoyo

Los diagramas, las consultas y la evidencia están en `../Documentacion/docs/`. El informe EP3 y la presentación EP4 están en `../Entrega/`. Estas carpetas sirven como documentación y no son necesarias para ejecutar el pipeline.
