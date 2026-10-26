import csv
import shutil
import tempfile
import unittest
from unittest.mock import patch
import src.pipeline as pipeline_module
from pathlib import Path
from sqlalchemy import text
from src.pipeline import execute_pipeline
from src.load import make_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PipelineIntegrationTests(unittest.TestCase):
    def test_pipeline_loads_star_model_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_dataretail360.db"
            args = {
                "source_path": PROJECT_ROOT / "data" / "mini_ventas.csv",
                "db_path": db_path,
                "schema_path": PROJECT_ROOT / "db" / "schema.sql",
                "batch_size": 20,
            }
            first = execute_pipeline(**args)
            second = execute_pipeline(**args)
            self.assertEqual(first["total_leidos"], 7)
            self.assertEqual(first["total_validos"], 4)
            self.assertEqual(first["total_rechazados"], 3)
            self.assertEqual(first["total_hechos"], 4)
            self.assertEqual(first["filas_cliente_no_identificado"], 1)
            self.assertEqual(second["total_hechos"], first["total_hechos"])

            engine = make_engine(db_path)
            try:
                with engine.connect() as conn:
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM fact_ventas")).scalar_one(), 4)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM silver_rechazos")).scalar_one(), 3)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM silver_transacciones WHERE customer_identified=0")).scalar_one(), 1)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM fact_ventas f JOIN dim_cliente c ON f.cliente_key=c.cliente_key WHERE c.tipo_scd='MIEMBRO_DESCONOCIDO'")).scalar_one(), 1)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM dim_cliente WHERE cliente_id_hash=(SELECT customer_id_hash FROM silver_transacciones WHERE invoice_no='1001' LIMIT 1)")).scalar_one(), 2)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM dim_geografia")).scalar_one(), 6)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM dim_geografia WHERE pais='Chile'")).scalar_one(), 6)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM logs_ejecucion WHERE estado='OK'")).scalar_one(), 2)
                    previous_description = conn.execute(text("SELECT descripcion_anterior FROM dim_producto WHERE codigo_producto='P001'")).scalar_one()
                    self.assertEqual(previous_description, "USB Charger")
                    self.assertEqual(conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                engine.dispose()


    def test_included_2000_row_sample_runs_end_to_end(self):
        """Comprueba la muestra real incluida, no solo el fixture de unidad."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "sample_2000.db"
            result = execute_pipeline(
                source_path=PROJECT_ROOT / "data" / "online_retail_muestra_2000.csv",
                db_path=db_path,
                schema_path=PROJECT_ROOT / "db" / "schema.sql",
                batch_size=500,
                max_rows=2000,
            )
            self.assertEqual(result["estado"], "OK")
            self.assertEqual(result["total_leidos"], 2000)
            self.assertEqual(result["total_validos"], 1992)
            self.assertEqual(result["total_rechazados"], 8)
            self.assertEqual(result["total_hechos"], 1992)
            self.assertEqual(result["filas_cliente_no_identificado"], 484)

            engine = make_engine(db_path)
            try:
                with engine.connect() as conn:
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM bronze_transacciones")).scalar_one(), 2000)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM silver_transacciones")).scalar_one(), 1992)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM fact_ventas")).scalar_one(), 1992)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM silver_transacciones WHERE customer_identified=0")).scalar_one(), 484)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM dim_cliente WHERE tipo_scd='MIEMBRO_DESCONOCIDO'")).scalar_one(), 1)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM dim_geografia")).scalar_one(), 6)
                    self.assertEqual(conn.execute(text("SELECT COUNT(DISTINCT sucursal_codigo) FROM fact_ventas f JOIN dim_geografia g ON f.geografia_key=g.geografia_key")).scalar_one(), 6)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM bronze_transacciones WHERE country_scope <> 'Chile'")).scalar_one(), 0)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM silver_transacciones WHERE country <> 'Chile'")).scalar_one(), 0)
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM dim_cliente WHERE pais <> 'Chile'")).scalar_one(), 0)
                    region_counts = dict(conn.execute(text("SELECT region, COUNT(*) FROM dim_geografia GROUP BY region")).fetchall())
                    self.assertEqual(region_counts, {"Región Metropolitana de Santiago": 4, "Región de O'Higgins": 1, "Región de Valparaíso": 1})
                    self.assertEqual(conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                engine.dispose()


    def test_scd1_overwrites_current_category_without_history(self):
        """Cambiar la fuente actualiza la categoría SCD1 y no crea versiones históricas."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "mini_ventas.csv"
            shutil.copyfile(PROJECT_ROOT / "data" / "mini_ventas.csv", source)
            db_path = temp / "scd1.db"
            args = {
                "source_path": source,
                "db_path": db_path,
                "schema_path": PROJECT_ROOT / "db" / "schema.sql",
                "batch_size": 20,
                "max_rows": 0,
            }
            execute_pipeline(**args)
            engine = make_engine(db_path)
            try:
                with engine.connect() as conn:
                    category_before = conn.execute(text(
                        "SELECT categoria FROM dim_producto WHERE codigo_producto='P001'"
                    )).scalar_one()
                self.assertEqual(category_before, "Tecnología")
            finally:
                engine.dispose()

            with source.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
                fieldnames = list(rows[0].keys())
            for row in rows:
                if row["StockCode"] == "P001" and row["InvoiceDate"] == "2011-01-03 11:00:00":
                    row["Description"] = "CERAMIC TEA CUP"
            with source.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            execute_pipeline(**args)
            engine = make_engine(db_path)
            try:
                with engine.connect() as conn:
                    category_after = conn.execute(text(
                        "SELECT categoria FROM dim_producto WHERE codigo_producto='P001'"
                    )).scalar_one()
                    product_rows = conn.execute(text(
                        "SELECT COUNT(*) FROM dim_producto WHERE codigo_producto='P001'"
                    )).scalar_one()
                    description = conn.execute(text(
                        "SELECT descripcion_producto FROM dim_producto WHERE codigo_producto='P001'"
                    )).scalar_one()
                    description_previous = conn.execute(text(
                        "SELECT descripcion_anterior FROM dim_producto WHERE codigo_producto='P001'"
                    )).scalar_one()
                self.assertEqual(category_after, "Hogar")
                self.assertEqual(product_rows, 1)
                self.assertEqual(description, "CERAMIC TEA CUP")
                self.assertEqual(description_previous, "USB Charger")
            finally:
                engine.dispose()


    def test_elt_persists_bronze_before_transform_and_silver_before_gold(self):
        """Demuestra el orden ELT leyendo Bronze y Silver ya persistidas en SQLite."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "elt_order.db"
            args = {
                "source_path": PROJECT_ROOT / "data" / "mini_ventas.csv",
                "db_path": db_path,
                "schema_path": PROJECT_ROOT / "db" / "schema.sql",
                "batch_size": 20,
            }
            original_transform = pipeline_module.transform_bronze
            original_model = pipeline_module.build_star_model
            observations = {"bronze_seen_before_silver": False, "silver_seen_before_gold": False}

            def check_bronze_before_transform(bronze_rows, job_id):
                engine = make_engine(db_path)
                try:
                    with engine.connect() as conn:
                        stored_bronze = conn.execute(text("SELECT COUNT(*) FROM bronze_transacciones")).scalar_one()
                        stored_silver = conn.execute(text("SELECT COUNT(*) FROM silver_transacciones")).scalar_one()
                    self.assertEqual(stored_bronze, len(bronze_rows))
                    self.assertEqual(stored_silver, 0)
                    observations["bronze_seen_before_silver"] = True
                finally:
                    engine.dispose()
                return original_transform(bronze_rows, job_id)

            def check_silver_before_gold(silver_rows, job_id):
                engine = make_engine(db_path)
                try:
                    with engine.connect() as conn:
                        stored_silver = conn.execute(text("SELECT COUNT(*) FROM silver_transacciones")).scalar_one()
                        stored_facts = conn.execute(text("SELECT COUNT(*) FROM fact_ventas")).scalar_one()
                    self.assertEqual(stored_silver, len(silver_rows))
                    self.assertEqual(stored_facts, 0)
                    observations["silver_seen_before_gold"] = True
                finally:
                    engine.dispose()
                return original_model(silver_rows, job_id)

            with patch.object(pipeline_module, "transform_bronze", side_effect=check_bronze_before_transform), \
                 patch.object(pipeline_module, "build_star_model", side_effect=check_silver_before_gold):
                result = pipeline_module.execute_pipeline(**args)

            self.assertEqual(result["estado"], "OK")
            self.assertTrue(observations["bronze_seen_before_silver"])
            self.assertTrue(observations["silver_seen_before_gold"])
            self.assertTrue(result["bronze_persistida_antes_de_transformar"])
            self.assertTrue(result["gold_construida_desde_silver_persistida"])
            self.assertEqual(result["arquitectura"], "ELT (Bronze-first) con SQLite")


if __name__ == "__main__":
    unittest.main()
