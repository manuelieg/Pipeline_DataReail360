"""Persistencia SQLite para un flujo ELT Bronze -> Silver -> Gold."""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("dataretail.load")


def make_engine(db_path: str | Path) -> Engine:
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def initialize_schema(engine: Engine, schema_path: str | Path) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    with engine.begin() as conn:
        tables = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "dim_geografia" in tables:
            geo_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(dim_geografia)").fetchall()}
            silver_columns = ({row[1] for row in conn.exec_driver_sql("PRAGMA table_info(silver_transacciones)").fetchall()}
                              if "silver_transacciones" in tables else set())
            customer_columns = ({row[1] for row in conn.exec_driver_sql("PRAGMA table_info(dim_cliente)").fetchall()}
                                if "dim_cliente" in tables else set())
            bronze_columns = ({row[1] for row in conn.exec_driver_sql("PRAGMA table_info(bronze_transacciones)").fetchall()}
                              if "bronze_transacciones" in tables else set())
            if ("sucursal_codigo" not in geo_columns or "branch_code" not in silver_columns
                    or "region_observada" not in customer_columns or "country_scope" not in bronze_columns):
                for view in ("vw_ventas_por_pais", "vw_ventas_por_region", "vw_ventas_por_sucursal",
                             "vw_ventas_mensuales", "vw_ventas_por_categoria", "vw_kpis_ventas"):
                    conn.exec_driver_sql(f"DROP VIEW IF EXISTS {view}")
                for table in ("fact_ventas", "silver_rechazos", "silver_transacciones", "bronze_transacciones",
                              "dim_cliente", "dim_producto", "dim_fecha", "dim_geografia", "dim_canal"):
                    conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
                logger.info("Esquema anterior detectado: se actualizará a Bronze-first ELT y geografía Chile.")
        statements = [piece.strip() for piece in schema.split(";") if piece.strip()]
        for statement in statements:
            conn.execute(text(statement))
    logger.info("Esquema del Data Warehouse inicializado/verificado.")


def _insert_df(df: pd.DataFrame, table: str, conn, batch_size: int) -> int:
    if df.empty:
        return 0
    df.to_sql(table, con=conn, if_exists="append", index=False, chunksize=batch_size, method=None)
    logger.info("%s: %s filas cargadas.", table, f"{len(df):,}")
    return len(df)


def load_bronze_first(engine: Engine, bronze: pd.DataFrame, batch_size: int) -> int:
    """Limpia el snapshot previo y carga Bronze en una transacción independiente.

    La transacción se confirma ANTES de iniciar las transformaciones Silver. Así las
    reglas de calidad se aplican sobre datos que ya están persistidos en SQLite.
    """
    delete_order = [
        "fact_ventas", "dim_cliente", "dim_producto", "dim_fecha", "dim_geografia", "dim_canal",
        "silver_rechazos", "silver_transacciones", "bronze_transacciones",
    ]
    with engine.begin() as conn:
        for table in delete_order:
            conn.execute(text(f"DELETE FROM {table}"))
        inserted = _insert_df(bronze, "bronze_transacciones", conn, batch_size)
        count = conn.execute(text("SELECT COUNT(*) FROM bronze_transacciones")).scalar_one()
        if count != inserted or count != len(bronze):
            raise RuntimeError("La carga Bronze no coincide con el número de registros extraídos.")
    logger.info("Bronze persistida y confirmada en SQLite antes de cualquier transformación de negocio.")
    return int(count)


def read_bronze(engine: Engine, job_id: str) -> pd.DataFrame:
    """Recupera Bronze desde SQLite para iniciar ELT; no usa el DataFrame de extracción."""
    df = pd.read_sql_query(text("""
        SELECT source_record_id, source_file, source_row_number, invoice_no_raw,
               product_code_raw, description_raw, quantity_raw, invoice_date_raw,
               unit_price_raw, customer_id_hash, country_scope, job_id, extracted_at
        FROM bronze_transacciones
        WHERE job_id = :job_id
        ORDER BY source_row_number
    """), engine, params={"job_id": job_id})
    logger.info("ELT: se leyeron %s filas desde Bronze persistida para transformar Silver.", f"{len(df):,}")
    return df


def load_silver(engine: Engine, silver: pd.DataFrame, rejected: pd.DataFrame, batch_size: int) -> dict:
    """Carga el resultado de calidad derivado de Bronze en Silver y Silver Rechazos."""
    with engine.begin() as conn:
        valid_count = _insert_df(silver, "silver_transacciones", conn, batch_size)
        reject_count = _insert_df(rejected, "silver_rechazos", conn, batch_size)
        stored_valid = conn.execute(text("SELECT COUNT(*) FROM silver_transacciones")).scalar_one()
        stored_rejects = conn.execute(text("SELECT COUNT(*) FROM silver_rechazos")).scalar_one()
        if stored_valid != valid_count or stored_rejects != reject_count:
            raise RuntimeError("La persistencia Silver no coincide con el resultado de transformación.")
    return {"silver": int(valid_count), "rechazos": int(reject_count)}


def read_silver(engine: Engine, job_id: str) -> pd.DataFrame:
    """Recupera las filas válidas persistidas en Silver para crear Gold."""
    df = pd.read_sql_query(text("""
        SELECT source_record_id, invoice_no, product_code, description, invoice_datetime,
               quantity, unit_price, amount_net, customer_id_hash, customer_identified,
               country, region, branch_code, movement_type, quality_status, job_id, transformed_at
        FROM silver_transacciones
        WHERE job_id = :job_id
        ORDER BY invoice_datetime, source_record_id
    """), engine, params={"job_id": job_id})
    logger.info("ELT: se leyeron %s filas desde Silver persistida para construir Gold.", f"{len(df):,}")
    return df


def load_gold(engine: Engine, model: dict[str, pd.DataFrame], batch_size: int) -> dict:
    """Carga dimensiones y hechos Gold y ejecuta controles de integridad."""
    with engine.begin() as conn:
        for table in ("dim_fecha", "dim_producto", "dim_cliente", "dim_geografia", "dim_canal"):
            _insert_df(model[table], table, conn, batch_size)
        _insert_df(model["fact_ventas"], "fact_ventas", conn, batch_size)

        counts = {
            "bronze": conn.execute(text("SELECT COUNT(*) FROM bronze_transacciones")).scalar_one(),
            "silver": conn.execute(text("SELECT COUNT(*) FROM silver_transacciones")).scalar_one(),
            "rechazos": conn.execute(text("SELECT COUNT(*) FROM silver_rechazos")).scalar_one(),
            "hechos": conn.execute(text("SELECT COUNT(*) FROM fact_ventas")).scalar_one(),
            "dim_fechas": conn.execute(text("SELECT COUNT(*) FROM dim_fecha")).scalar_one(),
            "dim_productos": conn.execute(text("SELECT COUNT(*) FROM dim_producto")).scalar_one(),
            "dim_clientes_versiones": conn.execute(text("SELECT COUNT(*) FROM dim_cliente")).scalar_one(),
            "sucursales": conn.execute(text("SELECT COUNT(*) FROM dim_geografia")).scalar_one(),
            "regiones": conn.execute(text("SELECT COUNT(DISTINCT region) FROM dim_geografia")).scalar_one(),
        }
        if counts["bronze"] != counts["silver"] + counts["rechazos"]:
            raise RuntimeError("Bronze debe ser igual a Silver válida + registros rechazados.")
        if counts["silver"] != counts["hechos"]:
            raise RuntimeError("La cantidad de hechos no coincide con las transacciones limpias de Silver.")

        country_violations = conn.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM bronze_transacciones WHERE country_scope <> 'Chile') +
                (SELECT COUNT(*) FROM silver_transacciones WHERE country <> 'Chile') +
                (SELECT COUNT(*) FROM silver_rechazos WHERE country IS NOT NULL AND country <> 'Chile') +
                (SELECT COUNT(*) FROM dim_cliente WHERE pais <> 'Chile') +
                (SELECT COUNT(*) FROM dim_geografia WHERE pais <> 'Chile')
        """)).scalar_one()
        if country_violations:
            raise RuntimeError(f"Se encontraron {country_violations} registros fuera del alcance geográfico Chile.")

        expected_regions = {
            "Región Metropolitana de Santiago": 4,
            "Región de O'Higgins": 1,
            "Región de Valparaíso": 1,
        }
        actual_regions = dict(conn.execute(text("SELECT region, COUNT(*) FROM dim_geografia GROUP BY region")).fetchall())
        if actual_regions != expected_regions:
            raise RuntimeError(f"La dimensión geográfica no contiene las 6 sucursales/regiones requeridas: {actual_regions}")

        orphans = conn.execute(text("""
            SELECT COUNT(*) FROM fact_ventas f
            LEFT JOIN dim_fecha d ON d.fecha_key=f.fecha_key
            LEFT JOIN dim_producto p ON p.producto_key=f.producto_key
            LEFT JOIN dim_cliente c ON f.cliente_key=c.cliente_key
            LEFT JOIN dim_geografia g ON f.geografia_key=g.geografia_key
            LEFT JOIN dim_canal ca ON f.canal_key=ca.canal_key
            WHERE d.fecha_key IS NULL OR p.producto_key IS NULL OR c.cliente_key IS NULL
               OR g.geografia_key IS NULL OR ca.canal_key IS NULL
        """)).scalar_one()
        if orphans:
            raise RuntimeError(f"Se detectaron {orphans} hechos sin dimensión asociada.")
        fk_errors = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"Falló la integridad referencial: {fk_errors[:3]}")
        counts["registros_fuera_de_chile"] = int(country_violations)
        counts["hechos_sin_dimension"] = int(orphans)
        counts["errores_clave_foranea"] = len(fk_errors)
    logger.info("Gold cargada y validada: %s hechos; 0 errores referenciales.", f"{counts['hechos']:,}")
    return {key: int(value) for key, value in counts.items()}


def write_run_log(engine: Engine, summary: dict, error_message: str | None = None) -> None:
    """Guarda éxito o fallo sin incluir identificadores personales en el log."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO logs_ejecucion
            (job_id, fecha_inicio, fecha_fin, estado, origen_archivo,
             total_leidos, total_validos, total_rechazados, total_hechos, duracion_ms, mensaje_error)
            VALUES (:job_id, :fecha_inicio, :fecha_fin, :estado, :origen_archivo,
                    :total_leidos, :total_validos, :total_rechazados, :total_hechos, :duracion_ms, :mensaje_error)
        """), {
            "job_id": summary.get("job_id"),
            "fecha_inicio": summary.get("fecha_inicio"),
            "fecha_fin": summary.get("fecha_fin"),
            "estado": "ERROR" if error_message else "OK",
            "origen_archivo": summary.get("origen_archivo", "desconocido"),
            "total_leidos": summary.get("total_leidos", 0),
            "total_validos": summary.get("total_validos", 0),
            "total_rechazados": summary.get("total_rechazados", 0),
            "total_hechos": summary.get("total_hechos", 0),
            "duracion_ms": summary.get("duracion_ms"),
            "mensaje_error": (error_message or "")[:1000] or None,
        })
