"""Orquestador ELT: extraer -> cargar Bronze -> transformar Silver -> construir Gold."""
from __future__ import annotations
import argparse
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from src import config
from src.extract import read_source
from src.bronze import prepare_bronze
from src.transform import transform_bronze
from src.modelado import build_star_model
from src.load import (
    make_engine, initialize_schema, load_bronze_first, read_bronze,
    load_silver, read_silver, load_gold, write_run_log,
)


def configure_logging(job_id: str, logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"job_{job_id}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    return log_path


def execute_pipeline(
    source_path: str | Path | None = None,
    db_path: str | Path | None = None,
    schema_path: str | Path | None = None,
    batch_size: int | None = None,
    max_rows: int | None = None,
) -> dict:
    source_path = Path(source_path or config.DATA_PATH).resolve()
    db_path = Path(db_path or config.DB_PATH).resolve()
    schema_path = Path(schema_path or config.SCHEMA_PATH).resolve()
    batch_size = max(1, int(batch_size or config.BATCH_SIZE))
    max_rows = config.MAX_SOURCE_ROWS if max_rows is None else max(0, int(max_rows))
    job_id = uuid.uuid4().hex[:10]
    log_path = configure_logging(job_id, config.LOGS_DIR)
    logger = logging.getLogger("dataretail.pipeline")
    engine = make_engine(db_path)
    start = time.perf_counter()
    started_at = datetime.now().isoformat(timespec="seconds")
    summary = {
        "job_id": job_id, "fecha_inicio": started_at,
        "origen_archivo": source_path.name, "base_datos": str(db_path),
        "estado": "EN_PROCESO", "total_leidos": 0,
        "total_validos": 0, "total_rechazados": 0, "total_hechos": 0,
        "arquitectura": "ELT (Bronze-first) con SQLite",
        "orden_etapas": [
            "Extract: lectura de fuente y metadatos mínimos",
            "Load: persistencia de Bronze",
            "Transform: lectura de Bronze persistida, validación y carga de Silver",
            "Transform: lectura de Silver persistida y construcción de dimensiones/hechos Gold",
            "Load/Validate: carga Gold y controles finales",
        ],
    }
    try:
        logger.info(
            "Inicio job=%s; arquitectura=ELT Bronze-first; fuente=%s; max_filas=%s; tamaño_lote_sql=%s; alcance_geografico=Chile; sucursales_demostrativas=6",
            job_id, source_path.name, max_rows or "sin límite", batch_size,
        )
        initialize_schema(engine, schema_path)

        raw = read_source(source_path, max_rows=max_rows)
        summary["total_leidos"] = len(raw)

        bronze = prepare_bronze(raw, job_id)
        bronze_count = load_bronze_first(engine, bronze, batch_size)
        logger.info("Etapa ELT 1/3 completada: Bronze contiene %s filas persistidas.", f"{bronze_count:,}")

        bronze_stored = read_bronze(engine, job_id)
        silver, rejected = transform_bronze(bronze_stored, job_id)
        silver_counts = load_silver(engine, silver, rejected, batch_size)
        logger.info("Etapa ELT 2/3 completada: Silver válida=%s; rechazos=%s.",
                    f"{silver_counts['silver']:,}", f"{silver_counts['rechazos']:,}")

        silver_stored = read_silver(engine, job_id)
        model = build_star_model(silver_stored, job_id)
        counts = load_gold(engine, model, batch_size)
        logger.info("Etapa ELT 3/3 completada: Gold construida desde Silver y validada.")

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        summary.update({
            "fecha_fin": datetime.now().isoformat(timespec="seconds"),
            "estado": "OK", "max_source_rows": max_rows,
            "total_validos": counts["silver"], "total_rechazados": counts["rechazos"],
            "total_hechos": counts["hechos"], "duracion_ms": duration_ms,
            "conteos_almacenamiento": counts,
            "bronze_persistida_antes_de_transformar": True,
            "gold_construida_desde_silver_persistida": True,
            "scd": {
                "scd1": "dim_producto.categoria (se sobrescribe la clasificación vigente)",
                "scd2": "dim_cliente.region_observada (versiones según cambios de región observada en asignaciones de sucursal demostrativas)",
                "scd3": "dim_producto.descripcion_anterior (guarda la descripción previa)",
            },
            "filas_cliente_no_identificado": int((silver_stored["customer_identified"] == 0).sum()) if not silver_stored.empty else 0,
            "alcance_geografico": {
                "pais": "Chile", "sucursales_demostrativas": 6,
                "regiones": ["Región Metropolitana de Santiago", "Región de O'Higgins", "Región de Valparaíso"],
                "asignacion_sucursal": "Determinística por número de factura; la fuente original no incluye sucursal real.",
                "advertencia": "La geografía y el reparto por sucursal son datos sintéticos para la demostración académica; no son ventas chilenas geográficamente verificadas.",
            },
        })
        write_run_log(engine, summary)
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = config.REPORTS_DIR / f"reporte_{job_id}.json"
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Pipeline ELT terminado correctamente: %s válidas, %s rechazadas, %s hechos.",
                    f"{counts['silver']:,}", f"{counts['rechazos']:,}", f"{counts['hechos']:,}")
        print("\nRESUMEN DEL PIPELINE DATARETAIL 360 · ELT")
        print(f"Job: {job_id} | Estado: OK")
        print(f"Filas leídas y aterrizadas en Bronze: {bronze_count:,}")
        print(f"Filas válidas en Silver:              {counts['silver']:,}")
        print(f"Filas rechazadas en Silver:           {counts['rechazos']:,}")
        print(f"Hechos cargados en Gold:              {counts['hechos']:,}")
        print(f"Sucursales Chile:                     {counts['sucursales']:,} (asignación demostrativa)")
        print(f"Errores de clave foránea:             {counts['errores_clave_foranea']}")
        print(f"Duración:                             {duration_ms:,.2f} ms")
        print(f"Base de datos:                        {db_path}")
        print(f"Log:                                  {log_path}")
        print(f"Reporte JSON:                         {report_path}")
        return summary
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        summary.update({"fecha_fin": datetime.now().isoformat(timespec="seconds"), "duracion_ms": duration_ms})
        logger.exception("El pipeline ELT falló. Se detiene para no ocultar el error.")
        try:
            write_run_log(engine, summary, error_message=f"{type(exc).__name__}: {exc}")
        except Exception:
            logger.exception("No fue posible registrar el fallo en logs_ejecucion.")
        raise
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline ELT DataRetail 360")
    parser.add_argument("--file", type=str, default=None, help="Archivo fuente .xlsx o .csv")
    parser.add_argument("--db-path", type=str, default=None, help="Ruta de la base SQLite destino")
    parser.add_argument("--schema-path", type=str, default=None, help="Ruta de db/schema.sql")
    parser.add_argument("--batch-size", type=int, default=None, help="Tamaño de lote para inserción SQL")
    parser.add_argument("--max-rows", type=int, default=None, help="Máximo de filas a leer; 0 procesa el archivo completo. Por defecto: 2000.")
    args = parser.parse_args()
    execute_pipeline(args.file, args.db_path, args.schema_path, args.batch_size, args.max_rows)


if __name__ == "__main__":
    main()
