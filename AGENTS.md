# AGENT RULES: Estándares de Calidad y Arquitectura

## 1. Separación Estricta de Responsabilidades (SoC)
- **Módulos de Datos (`models/schemas.py`):** Pura definición de Pydantic. No importan Streamlit ni HTTPX.
- **Módulos de Servicio (`services/api.py`):** Contienen las llamadas HTTP con `httpx.Client`[cite: 1]. 
  - **Permitido:** Se autoriza el uso de `@st.cache_data` / `@st.cache_resource` para optimizar peticiones y `st.error()` / `st.toast()` para notificar fallos de red directamente al usuario de forma amigable.
  - **Restricción:** No deben contener widgets interactivos de entrada de datos (como `st.button`, `st.text_input` o `st.file_uploader`), los cuales pertenecen exclusivamente a los archivos de UI (`app.py` o `components/`)[cite: 1].

## 2. Estilo de Código Python (PEP 8)
- **Formateo:** Cumplimiento estricto de PEP 8. Usar exactamente 4 espacios por nivel de sangría.
- **Nombres:** Usar `snake_case` para variables/funciones, `CamelCase` para clases y `UPPER_CASE` para constantes. EVITAR variables de una sola letra.
- **Tipado Estático (Type Hints):** Todas las firmas de funciones y métodos deben incluir *type hints* explícitos.

## 3. Manejo Riguroso de Errores y Excepciones
- **Prohibido Silenciar Errores:** Queda prohibido el uso de bloques `try...except` vacíos o capturas genéricas que silenciadores.
- **Propagación desde HTTPX hacia la UI:**
  1. En `services/api.py`, capturar errores HTTP de `httpx` (`httpx.HTTPStatusError`, `httpx.RequestError`) y re-elevarlos o transformarlos.
  2. La UI en Streamlit debe capturar estas excepciones y mostrar mensajes explicativos al usuario mediante `st.error()`.

## 4. Control de Cambios y Git (Límites)
- Queda **prohibido** ejecutar comandos de Git autónomos (`git add`, `git commit`, `git push`) sin la autorización explícita del usuario.