CREATE TABLE IF NOT EXISTS bronze_transacciones (
    source_record_id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    invoice_no_raw TEXT,
    product_code_raw TEXT,
    description_raw TEXT,
    quantity_raw TEXT,
    invoice_date_raw TEXT,
    unit_price_raw TEXT,
    customer_id_hash TEXT,
    country_scope TEXT NOT NULL CHECK (country_scope = 'Chile'),
    job_id TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS silver_transacciones (
    source_record_id TEXT PRIMARY KEY,
    invoice_no TEXT NOT NULL,
    product_code TEXT NOT NULL,
    description TEXT NOT NULL,
    invoice_datetime TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    amount_net REAL NOT NULL,
    customer_id_hash TEXT NOT NULL,
    customer_identified INTEGER NOT NULL CHECK (customer_identified IN (0,1)),
    country TEXT NOT NULL CHECK (country = 'Chile'),
    region TEXT NOT NULL,
    branch_code TEXT NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('Venta', 'Devolución')),
    quality_status TEXT NOT NULL,
    job_id TEXT NOT NULL,
    transformed_at TEXT NOT NULL,
    FOREIGN KEY(source_record_id) REFERENCES bronze_transacciones(source_record_id)
);

CREATE TABLE IF NOT EXISTS silver_rechazos (
    source_record_id TEXT PRIMARY KEY,
    invoice_no TEXT,
    product_code TEXT,
    description TEXT,
    invoice_datetime_raw TEXT,
    quantity_raw TEXT,
    unit_price_raw TEXT,
    customer_id_hash TEXT,
    country TEXT CHECK (country IS NULL OR country = 'Chile'),
    rejection_reason TEXT NOT NULL,
    job_id TEXT NOT NULL,
    rejected_at TEXT NOT NULL,
    FOREIGN KEY(source_record_id) REFERENCES bronze_transacciones(source_record_id)
);

CREATE TABLE IF NOT EXISTS dim_fecha (
    fecha_key INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL UNIQUE,
    dia INTEGER NOT NULL,
    mes INTEGER NOT NULL,
    nombre_mes TEXT NOT NULL,
    trimestre INTEGER NOT NULL,
    anio INTEGER NOT NULL,
    dia_semana INTEGER NOT NULL,
    nombre_dia TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_producto (
    producto_key INTEGER PRIMARY KEY,
    codigo_producto TEXT NOT NULL UNIQUE,
    descripcion_producto TEXT NOT NULL,
    descripcion_anterior TEXT,
    categoria TEXT NOT NULL,
    fecha_actualizacion TEXT,
    tipo_scd_categoria TEXT NOT NULL,
    tipo_scd_descripcion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_cliente (
    cliente_key INTEGER PRIMARY KEY,
    cliente_id_hash TEXT NOT NULL,
    pais TEXT NOT NULL CHECK (pais = 'Chile'),
    region_observada TEXT NOT NULL,
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,
    es_actual INTEGER NOT NULL CHECK (es_actual IN (0,1)),
    tipo_scd TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_geografia (
    geografia_key INTEGER PRIMARY KEY,
    sucursal_codigo TEXT NOT NULL UNIQUE,
    pais TEXT NOT NULL CHECK (pais = 'Chile'),
    region TEXT NOT NULL,
    comuna TEXT NOT NULL,
    sucursal TEXT NOT NULL,
    latitud REAL,
    longitud REAL,
    nivel_detalle_disponible TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_canal (
    canal_key INTEGER PRIMARY KEY,
    canal TEXT NOT NULL UNIQUE,
    descripcion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_ventas (
    fact_venta_key INTEGER PRIMARY KEY,
    source_record_id TEXT NOT NULL UNIQUE,
    invoice_no TEXT NOT NULL,
    fecha_key INTEGER NOT NULL,
    producto_key INTEGER NOT NULL,
    cliente_key INTEGER NOT NULL,
    geografia_key INTEGER NOT NULL,
    canal_key INTEGER NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('Venta', 'Devolución')),
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    monto_venta_bruta REAL NOT NULL,
    monto_devolucion REAL NOT NULL,
    monto_neto REAL NOT NULL,
    job_id TEXT NOT NULL,
    FOREIGN KEY(source_record_id) REFERENCES silver_transacciones(source_record_id),
    FOREIGN KEY(fecha_key) REFERENCES dim_fecha(fecha_key),
    FOREIGN KEY(producto_key) REFERENCES dim_producto(producto_key),
    FOREIGN KEY(cliente_key) REFERENCES dim_cliente(cliente_key),
    FOREIGN KEY(geografia_key) REFERENCES dim_geografia(geografia_key),
    FOREIGN KEY(canal_key) REFERENCES dim_canal(canal_key)
);

CREATE TABLE IF NOT EXISTS logs_ejecucion (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    fecha_inicio TEXT NOT NULL,
    fecha_fin TEXT,
    estado TEXT NOT NULL,
    origen_archivo TEXT NOT NULL,
    total_leidos INTEGER NOT NULL DEFAULT 0,
    total_validos INTEGER NOT NULL DEFAULT 0,
    total_rechazados INTEGER NOT NULL DEFAULT 0,
    total_hechos INTEGER NOT NULL DEFAULT 0,
    duracion_ms REAL,
    mensaje_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_fact_fecha ON fact_ventas(fecha_key);
CREATE INDEX IF NOT EXISTS idx_fact_producto ON fact_ventas(producto_key);
CREATE INDEX IF NOT EXISTS idx_fact_cliente ON fact_ventas(cliente_key);
CREATE INDEX IF NOT EXISTS idx_fact_geografia ON fact_ventas(geografia_key);
CREATE INDEX IF NOT EXISTS idx_fact_canal ON fact_ventas(canal_key);
CREATE INDEX IF NOT EXISTS idx_rechazos_motivo ON silver_rechazos(rejection_reason);
CREATE INDEX IF NOT EXISTS idx_cliente_historia ON dim_cliente(cliente_id_hash, vigente_desde, vigente_hasta);

-- Capa semántica: métricas con nombres de negocio compartidos entre usuarios y consultas NLQ.
CREATE VIEW IF NOT EXISTS vw_ventas_mensuales AS
SELECT f.anio, f.mes, f.nombre_mes,
       SUM(v.monto_venta_bruta) AS venta_bruta,
       SUM(v.monto_devolucion) AS devoluciones,
       SUM(v.monto_neto) AS venta_neta,
       SUM(v.cantidad) AS unidades_netas,
       COUNT(*) AS lineas_transaccion
FROM fact_ventas v JOIN dim_fecha f ON v.fecha_key = f.fecha_key
GROUP BY f.anio, f.mes, f.nombre_mes;

CREATE VIEW IF NOT EXISTS vw_ventas_por_categoria AS
SELECT p.categoria, SUM(v.monto_venta_bruta) AS venta_bruta,
       SUM(v.monto_devolucion) AS devoluciones,
       SUM(v.monto_neto) AS venta_neta, SUM(v.cantidad) AS unidades_netas
FROM fact_ventas v JOIN dim_producto p ON v.producto_key = p.producto_key
GROUP BY p.categoria;

CREATE VIEW IF NOT EXISTS vw_ventas_por_region AS
SELECT g.region, SUM(v.monto_venta_bruta) AS venta_bruta,
       SUM(v.monto_devolucion) AS devoluciones,
       SUM(v.monto_neto) AS venta_neta, SUM(v.cantidad) AS unidades_netas,
       COUNT(*) AS lineas_transaccion
FROM fact_ventas v JOIN dim_geografia g ON v.geografia_key = g.geografia_key
GROUP BY g.region;

CREATE VIEW IF NOT EXISTS vw_ventas_por_sucursal AS
SELECT g.sucursal_codigo, g.sucursal, g.comuna, g.region, g.pais,
       SUM(v.monto_venta_bruta) AS venta_bruta,
       SUM(v.monto_devolucion) AS devoluciones,
       SUM(v.monto_neto) AS venta_neta, SUM(v.cantidad) AS unidades_netas,
       COUNT(*) AS lineas_transaccion
FROM fact_ventas v JOIN dim_geografia g ON v.geografia_key = g.geografia_key
GROUP BY g.sucursal_codigo, g.sucursal, g.comuna, g.region, g.pais;

CREATE VIEW IF NOT EXISTS vw_kpis_ventas AS
SELECT COUNT(*) AS lineas_validas,
       SUM(CASE WHEN movement_type = 'Venta' THEN 1 ELSE 0 END) AS lineas_venta,
       SUM(CASE WHEN movement_type = 'Devolución' THEN 1 ELSE 0 END) AS lineas_devolucion,
       SUM(monto_venta_bruta) AS venta_bruta,
       SUM(monto_devolucion) AS monto_devoluciones,
       SUM(monto_neto) AS venta_neta,
       SUM(cantidad) AS unidades_netas
FROM fact_ventas;
