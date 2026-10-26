"""Catálogo geográfico chileno para la demostración DataRetail 360.

Las ubicaciones representan comunas de referencia; no son direcciones verificadas
ni sucursales comerciales reales. La asignación de facturas es sintética y estable.
"""
from __future__ import annotations
import hashlib

BRANCHES = [
    {
        "sucursal_codigo": "RM01", "pais": "Chile",
        "region": "Región Metropolitana de Santiago", "comuna": "Santiago",
        "sucursal": "Sucursal Santiago Centro", "latitud": -33.445222,
        "longitud": -70.657366,
    },
    {
        "sucursal_codigo": "RM02", "pais": "Chile",
        "region": "Región Metropolitana de Santiago", "comuna": "Providencia",
        "sucursal": "Sucursal Providencia", "latitud": -33.431447,
        "longitud": -70.609332,
    },
    {
        "sucursal_codigo": "RM03", "pais": "Chile",
        "region": "Región Metropolitana de Santiago", "comuna": "Maipú",
        "sucursal": "Sucursal Maipú", "latitud": -33.510587,
        "longitud": -70.757261,
    },
    {
        "sucursal_codigo": "RM04", "pais": "Chile",
        "region": "Región Metropolitana de Santiago", "comuna": "Las Condes",
        "sucursal": "Sucursal Las Condes", "latitud": -33.416101,
        "longitud": -70.534092,
    },
    {
        "sucursal_codigo": "OH01", "pais": "Chile",
        "region": "Región de O'Higgins", "comuna": "Rancagua",
        "sucursal": "Sucursal Rancagua", "latitud": -34.170290,
        "longitud": -70.740710,
    },
    {
        "sucursal_codigo": "VA01", "pais": "Chile",
        "region": "Región de Valparaíso", "comuna": "Valparaíso",
        "sucursal": "Sucursal Valparaíso", "latitud": -33.033333,
        "longitud": -71.600000,
    },
]

BRANCH_BY_CODE = {item["sucursal_codigo"]: item for item in BRANCHES}


def branch_for_invoice(invoice_number: object) -> str:
    """Asigna cada factura siempre a la misma sucursal de demostración.

    La fuente original no trae una sucursal real. Por eso esta regla se usa
    solo para probar la integración geográfica; no representa una asignación
    histórica u operacional de venta.
    """
    normalized = str(invoice_number or "").strip().upper()
    if normalized.startswith("C"):
        normalized = normalized[1:]
    digits = "".join(char for char in normalized if char.isdigit())
    if digits:
        index = int(digits) % len(BRANCHES)
    else:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        index = int(digest[:12], 16) % len(BRANCHES)
    return BRANCHES[index]["sucursal_codigo"]
