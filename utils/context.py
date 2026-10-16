"""Contexto de sesión para propagación implícita entre la UI y los servicios.

Este módulo permite que los servicios lean el token de sesión sin importar
``streamlit`` (cumpliendo el principio de separación de responsabilidades
definido en ``AGENTS.md``) y sin que el caller tenga que pasarlo explícitamente
en cada llamada.

Patrón: la capa de UI (``views/``, ``app.py``) sincroniza el token desde
``st.session_state`` a este contexto en cada rerun del script, y los
servicios (``services/``) lo leen como fallback cuando el caller no lo
provee explícitamente.

Es el equivalente "thread-local" moderno de Python, nativo (``contextvars``)
y libre de dependencias externas.

Importante sobre Streamlit y ``ContextVar``:
    ``ContextVar`` NO se propaga automáticamente a través de los límites
    de ejecución de ``@st.dialog`` ni ``@st.fragment``: Streamlit crea un
    contexto de script independiente para cada uno, por lo que el token
    seteado en el script principal aparece como ``None`` dentro del
    diálogo/fragmento si no se vuelve a sincronizar explícitamente.
    Por eso se ofrece ``sync_session_token()``.
"""

__all__ = ["set_token", "get_token", "clear_token", "sync_session_token"]

from contextvars import ContextVar
from typing import Optional

# Token de autenticación de la sesión actual. ``None`` cuando no hay sesión.
_current_token: ContextVar[Optional[str]] = ContextVar(
    "current_token", default=None
)


# --------------------------------------------------
def set_token(token: str) -> None:
    """
    Establece el token de autenticación en el contexto actual.

    Debe llamarse desde la capa de UI (típicamente en ``app.py`` después de
    que ``st.session_state["token"]`` haya sido seteado por ``login.py``).

    Args:
        token: Token JWT de la sesión.
    """
    _current_token.set(token)


# --------------------------------------------------
def get_token() -> Optional[str]:
    """
    Obtiene el token de autenticación del contexto actual.

    Returns:
        Token si está seteado, o ``None`` en caso contrario.
    """
    return _current_token.get()


# --------------------------------------------------
def clear_token() -> None:
    """
    Limpia el token del contexto actual (e.g. al hacer logout).
    """
    _current_token.set(None)


# --------------------------------------------------
def sync_session_token(token: Optional[str]) -> Optional[str]:
    """
    Sincroniza el token del ``st.session_state`` al ``ContextVar`` actual
    y lo retorna, listo para pasarlo a un servicio.

    Helper de defensa para ser invocado al inicio de ``@st.dialog`` y
    ``@st.fragment``, donde Streamlit no propaga los ``ContextVar``
    automáticamente. Centraliza la política "si hay token, setealo; si
    no, limpialo" en una sola función para evitar inconsistencias.

    Args:
        token: Token leído de ``st.session_state`` (puede ser ``None``).

    Returns:
        El mismo ``token`` recibido, para encadenar::
        
            token = sync_session_token(st.session_state.get("token"))
            delete_request(endpoint, token=token)
    """
    if token:
        set_token(token)
    else:
        clear_token()
    return token
