"""Servicio para interactuar con los endpoints de Planillometro en la API de Koyeb."""

import json
from io import BytesIO
from typing import Any, Optional

import httpx
import pandas as pd

from utils.config import API_BASE_URL, DEFAULT_TIMEOUT
from utils.context import get_token
from utils.exceptions import APIConnectionError, APIResponseError

BASE_URL = API_BASE_URL


# --------------------------------------------------
def _get_headers(token: Optional[str] = None) -> dict[str, str]:
    """
    Construye headers de autorización con fallback al contexto de sesión.

    Resolución del token (en orden de prioridad):

        1. ``token`` explícito pasado por el caller (preferido; robusto
           frente a ``@st.dialog``/``@st.fragment`` que no propagan
           ``ContextVar``).
        2. ``utils.context.get_token()`` (seteado por la UI en cada rerun
           del script principal; fallback cuando el caller no lo provee).
        3. Error: ``APIConnectionError``.

    Este patrón permite que los servicios lean el token sin importar
    ``streamlit`` (cumpliendo ``AGENTS.md``) y sin que cada caller tenga
    que pasarlo explícitamente.

    Args:
        token: Token JWT de la sesión (opcional).

    Raises:
        APIConnectionError: Si no hay token ni en el parámetro ni en el contexto.

    Returns:
        Diccionario con el header ``Authorization``.
    """
    actual_token: Optional[str] = token if token else get_token()
    if not actual_token:
        raise APIConnectionError("No hay token de sesión. Inicie sesión nuevamente.")
    return {"Authorization": f"Bearer {actual_token}"}


# --------------------------------------------------
def fetch_data(
    endpoint: str, params: Optional[dict[str, Any]] = None, token: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Realiza un GET genérico a la API y retorna la lista de registros.

    Args:
        endpoint: Ruta relativa del endpoint (ej. ``/siif/rf602/``).
        params: Parámetros de query opcionales.
        token: Token de autenticación.

    Returns:
        Lista de diccionarios con los datos.

    Raises:
        APIConnectionError: Si no hay conexión o el servidor está en
            despliegue (503).
        APIResponseError: Si la API retorna un error (status >= 400).
    """
    headers = _get_headers(token=token)
    clean_params = (
        {k: v for k, v in params.items() if v is not None} if params else None
    )

    try:
        response = httpx.get(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            params=clean_params,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        return _handle_response(response)

    except httpx.RequestError as exc:
        raise APIConnectionError(f"Error de conexión (GET): {exc}") from exc


# --------------------------------------------------
def fetch_dataframe(
    endpoint: str, params: Optional[dict[str, Any]] = None, token: Optional[str] = None
) -> pd.DataFrame:
    """
    Realiza un GET y retorna los datos como ``pd.DataFrame``.

    Args:
        endpoint: Ruta relativa del endpoint.
        params: Parámetros de query opcionales.
        token: Token de autenticación.

    Returns:
        DataFrame con los registros. Vacío si la API no retorna datos.
    """
    data = fetch_data(endpoint, params, token=token)
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


# --------------------------------------------------
def fetch_excel_stream(
    endpoint: str, params: dict, token: Optional[str] = None
) -> BytesIO:
    """
    Realiza un GET y retorna el contenido como un ``BytesIO`` listo para
    ser consumido por ``st.download_button``.

    Args:
        endpoint: Ruta relativa del endpoint (ej. ``/planillometro/factureros/export``).
        params: Parámetros de query.
        token: Token de autenticación.

    Returns:
        Buffer en memoria con el archivo descargado.

    Raises:
        APIConnectionError: Si hay un error de red.
        APIResponseError: Si la API retorna un código de error HTTP.
    """
    headers = _get_headers(token=token)
    # Limpiamos None y nos aseguramos de no enviar listas si la API espera valores únicos
    clean_params: dict[str, Any] = {}
    if params:
        for key, value in params.items():
            if value is not None:
                # Si es una lista (de un multiselect), tomamos el primer elemento
                clean_params[key] = value[0] if isinstance(value, list) else value

    try:
        response = httpx.get(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            params=clean_params,
            timeout=DEFAULT_TIMEOUT + 60.0,
            follow_redirects=True,  # CRÍTICO: soluciona errores 307 en Koyeb
        )
        # Si el cuerpo es binario (Excel) no podemos parsear como JSON.
        # Por eso validamos manualmente en lugar de delegar en _handle_response.
        if response.status_code == 200:
            return BytesIO(response.content)
        return _handle_response(response)

    except httpx.RequestError as exc:
        raise APIConnectionError(
            f"Error de conexión al obtener Excel (GET): {exc}"
        ) from exc


# --------------------------------------------------
def patch_request(
    endpoint: str,
    json_body: Optional[dict[str, Any]] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Realiza un PATCH genérico a la API.

    Args:
        endpoint: Ruta relativa del endpoint.
        json_body: Cuerpo JSON opcional.
        token: Token de autenticación.

    Returns:
        Diccionario con la respuesta.

    Raises:
        APIConnectionError: Si hay un error de red.
        APIResponseError: Si la API retorna un error HTTP.
    """
    headers = _get_headers(token=token)

    try:
        response = httpx.patch(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            json=json_body,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.RequestError as e:
        raise APIConnectionError(f"Error de conexión con el servidor: {e}") from e

    if response.status_code == 401:
        raise APIResponseError("Token expirado o inválido. Inicie sesión nuevamente.")
    if response.status_code != 200:
        raise APIResponseError(
            f"Error de API ({response.status_code}): {response.text}"
        )

    return response.json()


# --------------------------------------------------
def post_request(
    endpoint: str,
    json_body: Optional[Any] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Realiza un POST genérico a la API. Útil para actualizar base de datos.
    """
    headers = _get_headers(token=token)

    # --- FIX: Convertir Timestamps a strings ---
    if json_body is not None:
        # Serializamos a string y volvemos a cargar a dict
        # Esto convierte automáticamente los Timestamps a strings
        json_body = json.loads(
            json.dumps(
                json_body,
                default=lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x),
            )
        )
    # --------------------------------------------

    try:
        response = httpx.post(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            json=json_body,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        return _handle_response(response)
    except httpx.RequestError as e:
        raise APIConnectionError(f"Error de conexión (POST): {e}") from e


# --------------------------------------------------
def put_request(
    endpoint: str,
    json_body: Optional[Any] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Realiza un PUT genérico a la API. Útil para actualizar base de datos.
    """
    headers = _get_headers(token=token)

    # --- FIX: Convertir Timestamps a strings ---
    if json_body is not None:
        # Serializamos a string y volvemos a cargar a dict
        # Esto convierte automáticamente los Timestamps a strings
        json_body = json.loads(
            json.dumps(
                json_body,
                default=lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x),
            )
        )
    # --------------------------------------------

    try:
        response = httpx.put(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            json=json_body,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        return _handle_response(response)
    except httpx.RequestError as e:
        raise APIConnectionError(f"Error de conexión (PUT): {e}") from e


# --------------------------------------------------
def delete_request(
    endpoint: str,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Realiza un DELETE genérico a la API. Útil para actualizar base de datos.
    """
    headers = _get_headers(token=token)

    try:
        response = httpx.delete(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        return _handle_response(response)
    except httpx.RequestError as e:
        raise APIConnectionError(f"Error de conexión (DELETE): {e}") from e


# --------------------------------------------------
def _handle_response(response: httpx.Response) -> Any:
    """Centraliza la validación de respuestas HTTP."""
    if response.status_code == 401:
        raise APIResponseError("Sesión expirada. Por favor, ingrese de nuevo.")

    # # Manejo de estados de despliegue en Koyeb (503 Service Unavailable)
    if response.status_code == 503:
        raise APIConnectionError(
            "El servidor está despertando. Reintente en unos segundos..."
        )

    if not (200 <= response.status_code < 300):
        raise APIResponseError(
            f"Error de API ({response.status_code}): {response.text}"
        )

    return response.json()


def get_client(token: str | None = None) -> httpx.Client:
    """Retorna un cliente HTTPX configurado con timeout y token opcional."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=API_BASE_URL, headers=headers, timeout=DEFAULT_TIMEOUT)


def fetch_factureros(token: str | None = None) -> dict[str, Any]:
    """
    Obtiene el padrón de factureros desde la API.

    Args:
        token: Token de autenticación.

    Returns:
        Diccionario con la respuesta de la API.

    Raises:
        APIConnectionError: Si hay un error de red.
        APIResponseError: Si la API retorna un código de error HTTP.
    """
    with get_client(token=token) as client:
        try:
            response = client.get("/slave/factureros")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise APIResponseError(
                f"Error de API al obtener factureros "
                f"({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise APIConnectionError(
                f"Error de conexión al obtener factureros: {exc}"
            ) from exc


def fetch_honorarios(token: str | None = None) -> dict[str, Any]:
    """
    Obtiene el listado de honorarios desde la API.

    Args:
        token: Token de autenticación.

    Returns:
        Diccionario con la respuesta de la API.

    Raises:
        APIConnectionError: Si hay un error de red.
        APIResponseError: Si la API retorna un código de error HTTP.
    """
    with get_client(token=token) as client:
        try:
            response = client.get("/slave/honorarios")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise APIResponseError(
                f"Error de API al obtener honorarios "
                f"({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise APIConnectionError(
                f"Error de conexión al obtener honorarios: {exc}"
            ) from exc
