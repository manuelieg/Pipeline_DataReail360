"""Transformaciones ELT: lee datos ya persistidos en Bronze y produce Silver."""
from __future__ import annotations
import logging
import pandas as pd
from src.geografia import BRANCH_BY_CODE, branch_for_invoice

logger = logging.getLogger("dataretail.transform")
UNKNOWN_CUSTOMER_HASH = "__CLIENTE_NO_IDENTIFICADO__"
BRONZE_TO_SOURCE = {
    "invoice_no_raw": "InvoiceNo",
    "product_code_raw": "StockCode",
    "description_raw": "Description",
    "quantity_raw": "Quantity",
    "invoice_date_raw": "InvoiceDate",
    "unit_price_raw": "UnitPrice",
    "country_scope": "Country",
}


def transform_bronze(bronze_rows: pd.DataFrame, job_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna (Silver válida, rechazos) leyendo filas recuperadas desde la tabla Bronze."""
    df = bronze_rows.copy().rename(columns=BRONZE_TO_SOURCE)
    now = pd.Timestamp.now().isoformat(timespec="seconds")

    duplicate_columns = [
        "InvoiceNo", "StockCode", "Description", "Quantity",
        "InvoiceDate", "UnitPrice", "customer_id_hash", "Country",
    ]
    df["_duplicate"] = df.duplicated(subset=duplicate_columns, keep="first")

    df["invoice_no"] = df["InvoiceNo"].astype("string").str.strip()
    df["product_code"] = df["StockCode"].astype("string").str.strip()
    df["description"] = df["Description"].astype("string").str.strip()
    df["country"] = "Chile"
    df["branch_code"] = df["invoice_no"].map(branch_for_invoice)
    df["region"] = df["branch_code"].map(lambda code: BRANCH_BY_CODE[code]["region"])
    df["invoice_datetime"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
    df["quantity_numeric"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["unit_price_numeric"] = pd.to_numeric(df["UnitPrice"], errors="coerce")
    df["_cause"] = pd.NA

    rules = [
        (df["_duplicate"], "duplicado_exacto"),
        (df["invoice_datetime"].isna(), "fecha_invalida"),
        (df["product_code"].isna() | (df["product_code"].str.strip() == ""), "codigo_producto_vacio"),
        (df["description"].isna() | (df["description"].str.strip() == ""), "descripcion_faltante"),
        (df["quantity_numeric"].isna(), "cantidad_no_numerica"),
        (df["quantity_numeric"].fillna(0).eq(0), "cantidad_cero"),
        (df["unit_price_numeric"].isna(), "precio_no_numerico"),
        (df["unit_price_numeric"].fillna(0).le(0), "precio_invalido"),
    ]
    for condition, cause in rules:
        df.loc[df["_cause"].isna() & condition, "_cause"] = cause

    rejected_rows = df[df["_cause"].notna()].copy()
    valid_rows = df[df["_cause"].isna()].copy()

    rejected = pd.DataFrame({
        "source_record_id": rejected_rows["source_record_id"],
        "invoice_no": rejected_rows["invoice_no"],
        "product_code": rejected_rows["product_code"],
        "description": rejected_rows["description"],
        "invoice_datetime_raw": rejected_rows["InvoiceDate"].astype("string"),
        "quantity_raw": rejected_rows["Quantity"].astype("string"),
        "unit_price_raw": rejected_rows["UnitPrice"].astype("string"),
        "customer_id_hash": rejected_rows["customer_id_hash"],
        "country": "Chile",
        "rejection_reason": rejected_rows["_cause"].astype(str),
        "job_id": job_id,
        "rejected_at": now,
    })

    qty = valid_rows["quantity_numeric"].astype(int)
    canceled_invoice = valid_rows["invoice_no"].fillna("").str.upper().str.startswith("C")
    signed_qty = qty.where(~canceled_invoice, -qty.abs())
    is_return = signed_qty.lt(0) | canceled_invoice
    signed_qty = signed_qty.where(~is_return, -signed_qty.abs())

    silver = pd.DataFrame({
        "source_record_id": valid_rows["source_record_id"],
        "invoice_no": valid_rows["invoice_no"].astype(str),
        "product_code": valid_rows["product_code"].astype(str),
        "description": valid_rows["description"].astype(str).str.strip(),
        "invoice_datetime": valid_rows["invoice_datetime"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "quantity": signed_qty.astype(int),
        "unit_price": valid_rows["unit_price_numeric"].astype(float).round(4),
        "amount_net": (signed_qty * valid_rows["unit_price_numeric"].astype(float)).round(2),
        "customer_id_hash": valid_rows["customer_id_hash"].fillna(UNKNOWN_CUSTOMER_HASH),
        "customer_identified": valid_rows["customer_id_hash"].notna().astype(int),
        "country": "Chile",
        "region": valid_rows["region"].astype(str),
        "branch_code": valid_rows["branch_code"].astype(str),
        "movement_type": is_return.map({True: "Devolución", False: "Venta"}),
        "quality_status": "VALIDO",
        "job_id": job_id,
        "transformed_at": now,
    })
    logger.info(
        "Transformación desde Bronze completada: %s válidas y %s rechazadas.",
        f"{len(silver):,}", f"{len(rejected):,}",
    )
    return silver.reset_index(drop=True), rejected.reset_index(drop=True)
