# PLAN MAESTRO: Migración Planillometro Google Sheet a Streamlit + API Koyeb (Poetry + HTTPX)

## 1. Contexto y Objetivos
Migrar el contenido de la Google Sheet (https://docs.google.com/spreadsheets/d/1Hmb7xmzhZBoicnL5_tN7mr1kOj-r3gw8lCkPErR8Xd4) a una aplicación local ejecutable construida en Python Streamlit, gestionando dependencias con Poetry y empacable vía PyInstaller (`run.py`). La persistencia se realiza llamando a la API remota en Koyeb (FastAPI + MongoDB).

## 2. Gestión de Entorno y Dependencias (Poetry)
- **Gestor:** Poetry (`pyproject.toml` / `poetry.lock`).
- **Dependencias principales:**
  - `streamlit`
  - `httpx`
  - `pandas`
  - `pydantic`
  - `python-dotenv`
- **Dependencias de desarrollo (dev):**
  - `pyinstaller`

## 3. Arquitectura del Proyecto
proyecto_planillometro/
├── pyproject.toml             # Configuración de dependencias de Poetry
├── poetry.lock
├── app.py                     # Entrypoint Streamlit (Navegación / Dashboard)
├── run.py                 # Wrapper ejecutable para PyInstaller
├── .env                       # API_BASE_URL=https://fixed-marita-invico-d13e43fa.koyeb.app
├── models/
│   ├── __init__.py
│   └── schemas.py             # Pydantic models (FactureroReport, HonorarioReport)
├── services/
│   ├── __init__.py
│   └── api.py           # Requests a la API con httpx
├── components/
│   ├── buttons.py
│   └── dataframes.py        
├── views/
│   ├── __init__.py
│   └── pages.py           # Distintas páginas de las app
└── utils/
    └── config.py

## 4. Especificaciones de Datos
- **ObrasRecuperadasReport:** ejercicio (int), cod_barrio (str), estructura (str), importe (float), notas (str), updated_at (datatime)
- **ObrasDesactivadasReport:** ejercicio (int), cta_contable (str), estructura (str), importe (float), notas (str), updated_at (datatime)

## 5. Tareas de Implementación para Antigravity
1. Inicializar el proyecto con Poetry (`poetry init`) e instalar todas las dependencias nombradas (usando `httpx` en lugar de `requests`).
2. Crear los esquemas de datos Pydantic en `models/schemas.py`.
3. Crear `services/api.py` usando `httpx.Client` para consumir los endpoints `/sgv` y `/reporte/reporte_planillometro` de la API en Koyeb.
4. Migrar datos cargados en el Google Sheet (`https://docs.google.com/spreadsheets/d/1Hmb7xmzhZBoicnL5_tN7mr1kOj-r3gw8lCkPErR8Xd4`) de las hojas Obras Recuperadas y Otras a sgv_obras_recuperadas (`/sgv/obrasRecuperadas`) y sgv_obras_desactivadas (`/sgv/obrasDesactivadas`) respectivamente 
5. Crear la interfaz Streamlit con dos secciones principales:
   - **Obras Recuperadas:** CRUD de registros de la colección con modales o directamente desde la tabla (st.data_editor).
   - **Obras Desactivadas:** CRUD de registros de la colección con modales o directamente desde la tabla (st.data_editor).
6. Crear `run.py` y verificar la compilación ejecutando PyInstaller dentro del entorno de Poetry (`poetry run pyinstaller ...`).