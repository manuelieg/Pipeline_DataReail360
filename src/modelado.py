"""Construcción de dimensiones, hechos y SCD 1, 2 y 3 para el esquema estrella."""
from __future__ import annotations
import re
import pandas as pd
from src.geografia import BRANCHES

UNKNOWN_CUSTOMER_HASH = "__CLIENTE_NO_IDENTIFICADO__"

MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def categorize_product(description: str) -> str:
    """Clasificación preliminar por palabras clave; debe validarse con el catálogo real."""
    text = str(description or "").upper()
    technology = ("USB", "BATTERY", "BATTERIES", "CAMERA", "COMPUTER", "ELECTRIC", "LED ", "LED-", "PHONE", "CHARGER", "ADAPTER", "ELECTRONIC", "RADIO")
    home = ("CUP", "MUG", "BOWL", "KITCHEN", "PLATE", "DOORMAT", "CANDLE", "CUSHION", "LANTERN", "JAR ", "GLASS", "HOLDER", "BASKET", "FRAME", "LIGHT", "DECOR", "HANGING", "VASE", "TEA TOWEL", "T-LIGHT", "TIN", "TRAY", "NAPKIN", "COASTER", "POT", "HOOK", "SHELF", "ORNAMENT")
    accessories = ("BAG", "WALLET", "KEYRING", "JEWEL", "NECKLACE", "BRACELET", "SCARF", "HAT", "UMBRELLA", "PURSE", "CASE", "PENCIL", "STATIONERY", "RIBBON", "WRAP", "GIFT", "PARTY", "TOY", "DOLL", "CARD", "RULER", "PAPER", "CLOTHES", "APRON")
    if any(word in text for word in technology):
        return "Tecnología"
    if any(word in text for word in home):
        return "Hogar"
    if any(word in text for word in accessories):
        return "Accesorios"
    return "Otros / por clasificar"


def _build_dates(silver: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(silver["invoice_datetime"]).dt.normalize().drop_duplicates().sort_values()
    if dates.empty:
        return pd.DataFrame(columns=["fecha_key", "fecha", "dia", "mes", "nombre_mes", "trimestre", "anio", "dia_semana", "nombre_dia"])
    out = pd.DataFrame({"fecha": dates.dt.strftime("%Y-%m-%d")})
    dt = pd.to_datetime(out["fecha"])
    out["fecha_key"] = dt.dt.strftime("%Y%m%d").astype(int)
    out["dia"] = dt.dt.day
    out["mes"] = dt.dt.month
    out["nombre_mes"] = dt.dt.month.map(lambda x: MONTHS_ES[x - 1])
    out["trimestre"] = dt.dt.quarter
    out["anio"] = dt.dt.year
    out["dia_semana"] = dt.dt.dayofweek + 1
    out["nombre_dia"] = dt.dt.dayofweek.map(lambda x: WEEKDAYS_ES[x])
    return out[["fecha_key", "fecha", "dia", "mes", "nombre_mes", "trimestre", "anio", "dia_semana", "nombre_dia"]]


def _build_products(silver: pd.DataFrame) -> pd.DataFrame:
    cols = ["producto_key", "codigo_producto", "descripcion_producto", "descripcion_anterior", "categoria", "fecha_actualizacion", "tipo_scd_categoria", "tipo_scd_descripcion"]
    if silver.empty:
        return pd.DataFrame(columns=cols)
    df = silver.copy()
    df["invoice_datetime"] = pd.to_datetime(df["invoice_datetime"])
    df = df.sort_values(["invoice_datetime", "source_record_id"])
    rows = []
    for product_key, (code, group) in enumerate(df.groupby("product_code", sort=True), start=1):
        descriptions = [x for x in group["description"].astype(str).str.strip().tolist() if x and x.lower() != "nan"]
        unique_history = []
        for desc in descriptions:
            if not unique_history or unique_history[-1] != desc:
                unique_history.append(desc)
        current = unique_history[-1] if unique_history else str(code)
        previous = unique_history[-2] if len(unique_history) > 1 else None
        rows.append({
            "producto_key": product_key,
            "codigo_producto": str(code),
            "descripcion_producto": current,
            "descripcion_anterior": previous,
            "categoria": categorize_product(current),
            "fecha_actualizacion": group["invoice_datetime"].max().strftime("%Y-%m-%d %H:%M:%S"),
            "tipo_scd_categoria": "SCD1",
            "tipo_scd_descripcion": "SCD3",
        })
    return pd.DataFrame(rows, columns=cols)


def _build_customers(silver: pd.DataFrame) -> pd.DataFrame:
    """SCD2: versiona la región de sucursal observada para cada cliente.

    La ubicación de cada factura es sintética para esta demostración; la fuente
    no contiene domicilio del cliente ni sucursal real. El país se mantiene Chile.
    """
    cols = ["cliente_key", "cliente_id_hash", "pais", "region_observada", "vigente_desde", "vigente_hasta", "es_actual", "tipo_scd"]
    unknown_member = {
        "cliente_key": 1,
        "cliente_id_hash": UNKNOWN_CUSTOMER_HASH,
        "pais": "Chile",
        "region_observada": "No identificada",
        "vigente_desde": "1900-01-01 00:00:00",
        "vigente_hasta": None,
        "es_actual": 1,
        "tipo_scd": "MIEMBRO_DESCONOCIDO",
    }
    if silver.empty:
        return pd.DataFrame([unknown_member], columns=cols)
    df = silver[["customer_id_hash", "invoice_datetime", "region", "source_record_id"]].copy()
    df = df[df["customer_id_hash"].ne(UNKNOWN_CUSTOMER_HASH)].copy()
    df["invoice_datetime"] = pd.to_datetime(df["invoice_datetime"])
    df = df.sort_values(["customer_id_hash", "invoice_datetime", "source_record_id"])
    events = df.drop_duplicates(subset=["customer_id_hash", "invoice_datetime"], keep="first")
    events = events[["customer_id_hash", "invoice_datetime", "region"]].rename(columns={"region": "region_observada"})
    events = events.sort_values(["customer_id_hash", "invoice_datetime"])
    events["region_anterior"] = events.groupby("customer_id_hash")["region_observada"].shift(1)
    events = events[events["region_anterior"].isna() | events["region_observada"].ne(events["region_anterior"])].copy()
    events["vigente_hasta_dt"] = events.groupby("customer_id_hash")["invoice_datetime"].shift(-1)
    events["cliente_id_hash"] = events["customer_id_hash"]
    events["pais"] = "Chile"
    events["cliente_key"] = range(2, len(events) + 2)
    events["vigente_desde"] = events["invoice_datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    events["vigente_hasta"] = events["vigente_hasta_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")
    events["es_actual"] = events["vigente_hasta_dt"].isna().astype(int)
    events["tipo_scd"] = "SCD2"
    output = pd.concat([pd.DataFrame([unknown_member], columns=cols), events[cols]], ignore_index=True)
    return output[cols].reset_index(drop=True)


def build_star_model(silver: pd.DataFrame, job_id: str) -> dict[str, pd.DataFrame]:
    """Construye dimensiones y hechos. La granularidad del hecho es una línea fuente."""
    dates = _build_dates(silver)
    products = _build_products(silver)
    customers = _build_customers(silver)

    geographies = pd.DataFrame([
        {
            "geografia_key": idx,
            **branch,
            "nivel_detalle_disponible": "Sucursal de demostración; coordenada referencial de comuna",
        }
        for idx, branch in enumerate(BRANCHES, start=1)
    ], columns=["geografia_key", "sucursal_codigo", "pais", "region", "comuna", "sucursal", "latitud", "longitud", "nivel_detalle_disponible"])
    channels = pd.DataFrame([{"canal_key": 1, "canal": "Digital / eCommerce", "descripcion": "Canal digital representado por la muestra de transacciones Online Retail"}])

    fact_cols = ["source_record_id", "invoice_no", "fecha_key", "producto_key", "cliente_key", "geografia_key", "canal_key", "movement_type", "cantidad", "precio_unitario", "monto_venta_bruta", "monto_devolucion", "monto_neto", "job_id"]
    if silver.empty:
        facts = pd.DataFrame(columns=fact_cols)
    else:
        tx = silver.copy()
        tx["invoice_datetime"] = pd.to_datetime(tx["invoice_datetime"])
        tx["fecha"] = tx["invoice_datetime"].dt.strftime("%Y-%m-%d")
        tx = tx.merge(dates[["fecha", "fecha_key"]], on="fecha", how="left", validate="many_to_one")
        tx = tx.merge(products[["codigo_producto", "producto_key"]], left_on="product_code", right_on="codigo_producto", how="left", validate="many_to_one")
        tx = tx.merge(geographies[["sucursal_codigo", "geografia_key"]], left_on="branch_code", right_on="sucursal_codigo", how="left", validate="many_to_one")

        customer_map = customers[["cliente_key", "cliente_id_hash", "vigente_desde", "vigente_hasta"]].copy()
        customer_map["customer_id_hash"] = customer_map["cliente_id_hash"]
        customer_map["vigente_desde_dt"] = pd.to_datetime(customer_map["vigente_desde"])
        customer_map["vigente_hasta_dt"] = pd.to_datetime(customer_map["vigente_hasta"], errors="coerce")
        tx = pd.merge_asof(
            tx.sort_values("invoice_datetime"),
            customer_map.sort_values("vigente_desde_dt"),
            left_on="invoice_datetime", right_on="vigente_desde_dt",
            by="customer_id_hash", direction="backward", allow_exact_matches=True,
        )
        applicable = tx["cliente_key"].notna() & (tx["vigente_hasta_dt"].isna() | tx["invoice_datetime"].lt(tx["vigente_hasta_dt"]))
        tx = tx[applicable].copy()
        tx["canal_key"] = 1
        tx["monto_venta_bruta"] = tx["amount_net"].where(tx["movement_type"].eq("Venta"), 0.0).round(2)
        tx["monto_devolucion"] = tx["amount_net"].abs().where(tx["movement_type"].eq("Devolución"), 0.0).round(2)
        tx["monto_neto"] = tx["amount_net"].round(2)
        tx["precio_unitario"] = tx["unit_price"].astype(float)
        tx["job_id"] = job_id
        facts = tx[["source_record_id", "invoice_no", "fecha_key", "producto_key", "cliente_key", "geografia_key", "canal_key", "movement_type", "quantity", "precio_unitario", "monto_venta_bruta", "monto_devolucion", "monto_neto", "job_id"]].copy()
        facts = facts.rename(columns={"quantity": "cantidad"})
        facts = facts[fact_cols]
        if len(facts) != len(silver):
            missing_ids = len(silver) - len(facts)
            raise ValueError(f"No se pudo asociar dimensión temporal a {missing_ids} transacciones válidas.")

    return {
        "dim_fecha": dates,
        "dim_producto": products,
        "dim_cliente": customers,
        "dim_geografia": geographies,
        "dim_canal": channels,
        "fact_ventas": facts,
    }

