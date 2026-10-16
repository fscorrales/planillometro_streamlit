"""Servicio de autenticación y gestión de usuarios para INVICO Planillometro."""

__all__ = ["get_current_user", "login", "register"]

import httpx

from models.schemas import PublicStoredUser
from utils.config import settings
import utils.exceptions as ex

BASE_URL: str = settings.BASE_URL
DEFAULT_TIMEOUT: float = settings.DEFAULT_TIMEOUT


def login(username: str, password: str) -> str:
    """
    Autentica al usuario contra el backend y devuelve el token JWT.

    Raises:
        ValidationError: Si faltan credenciales requeridas.
        AuthenticationError: Si las credenciales no coinciden o no existe el usuario.
        APIConnectionError: Si no se puede conectar con el servidor.
        APIResponseError: Si el servidor devuelve un código de error inesperado.
    """
    if not username or not password:
        raise ex.ValidationError("Usuario y contraseña son requeridos.")

    data = {"username": username, "password": password}

    try:
        response = httpx.post(
            f"{BASE_URL}/auth/login",
            data=data,
            timeout=DEFAULT_TIMEOUT,
        )

        if response.status_code in (401, 404):
            raise ex.AuthenticationError("Usuario o contraseña incorrectos.")
        if response.status_code == 503:
            raise ex.APIConnectionError(
                "El servidor está iniciando. Por favor, reintente en unos segundos..."
            )
        if not (200 <= response.status_code < 300):
            detail = _extract_error_detail(response)
            raise ex.APIResponseError(f"Error del servidor ({response.status_code}): {detail}")

        token_data = response.json()
        token = token_data.get("access_token") or response.cookies.get("access_token")
        if not token:
            raise ex.APIResponseError("Respuesta de token inválida del servidor.")

        return str(token)

    except httpx.RequestError as exc:
        raise ex.APIConnectionError(f"Error de conexión con el servidor: {exc}")


def register(username: str, password: str) -> None:
    """
    Registra un nuevo usuario en el sistema.

    Raises:
        ValidationError: Si faltan datos obligatorios.
        APIConnectionError: Si no se puede conectar con el backend.
        APIResponseError: Si el registro es rechazado (ej. usuario duplicado).
    """
    if not username or not password:
        raise ex.ValidationError("Usuario y contraseña son requeridos.")

    data = {"username": username, "password": password}

    try:
        response = httpx.post(
            f"{BASE_URL}/auth/register",
            data=data,
            timeout=DEFAULT_TIMEOUT,
        )

        if response.status_code in (400, 422):
            detail = _extract_error_detail(response)
            raise ex.APIResponseError(f"No se pudo registrar: {detail}")

        if not (200 <= response.status_code < 300):
            detail = _extract_error_detail(response)
            raise ex.APIResponseError(f"Error del servidor ({response.status_code}): {detail}")

    except httpx.RequestError as exc:
        raise ex.APIConnectionError(f"Error de conexión con el servidor: {exc}")


def get_current_user(token: str) -> PublicStoredUser:
    """
    Obtiene los datos del usuario logueado utilizando el token JWT.

    Raises:
        ValidationError: Si no se suministra un token.
        AuthenticationError: Si el token expiró o es inválido.
        APIConnectionError: Si hay fallas de red.
        APIResponseError: Si hay un error inesperado al consultar el perfil.
    """
    if not token:
        raise ex.ValidationError("Token de autenticación no proporcionado.")

    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = httpx.get(
            f"{BASE_URL}/users/me",
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )

        if response.status_code == 401:
            raise ex.AuthenticationError("Token expirado o inválido. Inicie sesión nuevamente.")

        if response.status_code != 200:
            detail = _extract_error_detail(response)
            raise ex.APIResponseError(f"Error al obtener perfil de usuario: {detail}")

        return PublicStoredUser(**response.json())

    except httpx.RequestError as exc:
        raise ex.APIConnectionError(f"Error de conexión con el servidor: {exc}")


def _extract_error_detail(response: httpx.Response) -> str:
    """Función auxiliar para obtener el mensaje de detalle de una respuesta de FastAPI."""
    try:
        data = response.json()
        if isinstance(data, dict) and "detail" in data:
            detail = data["detail"]
            if isinstance(detail, list):
                # Errores de validación de FastAPI
                return "; ".join([item.get("msg", str(item)) for item in detail])
            return str(detail)
    except Exception:
        pass
    return response.text
