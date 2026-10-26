"""Extracción de CSV, CSV comprimido o Excel con trazabilidad por fila."""
from __future__ import annotations
import hashlib
import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger("dataretail.extract")
SOURCE_COLUMNS = [
    "InvoiceNo", "StockCode", "Description", "Quantity",
    "InvoiceDate", "UnitPrice", "CustomerID", "Country",
]


def _customer_hash(value) -> str | None:
    """Pseudonimiza el identificador antes de persistirlo en cualquier capa."""
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
        if number.is_integer():
            text = str(int(number))
    except (TypeError, ValueError):
        pass
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_id(source_name: str, row_number: int) -> str:
    base = f"{Path(source_name).name}|{row_number}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()[:32]


def read_source(path: str | Path, max_rows: int = 0) -> pd.DataFrame:
    """Lee la fuente y añade IDs estables. No registra IDs de cliente en claro.

    max_rows > 0 limita la lectura a las primeras filas (muestra determinística);
    max_rows == 0 procesa la fuente completa.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo fuente: {path}")

    logger.info("Extrayendo fuente: %s", path.name)
    suffix = path.suffix.lower()
    nrows = max_rows if max_rows > 0 else None
    if path.name.lower().endswith(".csv.gz"):
        df = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="replace", compression="gzip", nrows=nrows)
    elif suffix == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="replace", nrows=nrows)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, nrows=nrows)
    else:
        raise ValueError("Formato no soportado. Usa .xlsx, .xls, .csv o .csv.gz.")

    missing = [col for col in SOURCE_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en la fuente: {missing}")

    df = df[SOURCE_COLUMNS].copy()
    df["source_row_number"] = range(1, len(df) + 1)
    df["source_record_id"] = [
        _record_id(path.name, row_num) for row_num in df["source_row_number"]
    ]
    df["customer_id_hash"] = df["CustomerID"].map(_customer_hash)
    df["source_file"] = path.name
    logger.info("Extracción completada: %s filas%s.", f"{len(df):,}", f" (límite={max_rows:,})" if max_rows > 0 else " (archivo completo)")
    return df
