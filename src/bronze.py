"""Preparación mínima de aterrizaje y carga inicial de Bronze.

Las reglas de negocio y calidad se aplican DESPUÉS de persistir Bronze.
Antes de esa persistencia solo se asigna trazabilidad, se protege el identificador
personal y se normaliza el país de salida a Chile para respetar el alcance solicitado.
"""
from __future__ import annotations
import logging
import pandas as pd

logger = logging.getLogger("dataretail.bronze")


def prepare_bronze(raw: pd.DataFrame, job_id: str) -> pd.DataFrame:
    """Prepara una representación trazable para aterrizar primero en Bronze.

    No realiza validación de fechas/precios/cantidades ni reglas de rechazo. El ID
    de cliente nunca se persiste en claro y la geografía original no se persiste:
    la columna country_scope refleja el escenario Chile de esta demostración.
    """
    now = pd.Timestamp.now().isoformat(timespec="seconds")
    bronze = pd.DataFrame({
        "source_record_id": raw["source_record_id"].astype(str),
        "source_file": raw["source_file"].astype(str),
        "source_row_number": raw["source_row_number"].astype(int),
        "invoice_no_raw": raw["InvoiceNo"].astype("string"),
        "product_code_raw": raw["StockCode"].astype("string"),
        "description_raw": raw["Description"].astype("string"),
        "quantity_raw": raw["Quantity"].astype("string"),
        "invoice_date_raw": raw["InvoiceDate"].astype("string"),
        "unit_price_raw": raw["UnitPrice"].astype("string"),
        "customer_id_hash": raw["customer_id_hash"],
        "country_scope": "Chile",
        "job_id": job_id,
        "extracted_at": now,
    })
    logger.info(
        "Aterrizaje Bronze preparado: %s filas; sin validación de negocio previa; "
        "CustomerID pseudonimizado y alcance geográfico Chile.",
        f"{len(bronze):,}",
    )
    return bronze.reset_index(drop=True)
