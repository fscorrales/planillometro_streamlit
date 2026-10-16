"""Modales (``st.dialog``) reutilizables de la capa de vistas."""

import re
import time
from datetime import date, datetime
from io import BytesIO
from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from components.buttons import button_cancel, button_submit
from services.api import delete_request, post_request, put_request
from services.data_fetcher import (
    get_precarizados,
    get_referencias_factureros,
    get_referencias_honorarios,
)

from utils.context import sync_session_token
from utils.endpoints import Endpoints
from utils.exceptions import AppBaseException
from views.aux_tables import report_data_version_key

# Tipo de comprobante que exige la partida real del padrón de
# Precarizados. El Back fuerza la partida "399" a todo tipo distinto
# de este al agregar o editar (ver modal_honorarios).
TIPO_HONORARIOS: str = "Honorarios"


# --- MODAL: ELIMINAR COMPROBANTE GENERICO ---
@st.dialog("Confirmar Eliminación PERMANENTE", width="small")
def modal_delete_registro_gral(
    endpoint: str,
    desc_registro: str,
    session_state_update_key: str = None,
    key_prefix: str = "",
):
    # CRÍTICO: Streamlit ejecuta ``@st.dialog`` en un contexto de script
    # separado donde los ``ContextVar`` (usados por ``utils.context`` para
    # propagar el token) NO se heredan automáticamente del script principal.
    # Sin esta sincronización, ``delete_request`` recibiría ``None`` y
    # lanzaría ``APIConnectionError("No hay token de sesión...")``.
    token = sync_session_token(st.session_state.get("token"))

    st.warning(
        f"⚠️ ¿Estás seguro de que deseás eliminar el registro **{desc_registro}**?"
    )
    st.write(
        "Esta acción es permanente y también eliminará todas las retenciones asociadas."
    )

    st.markdown("---")
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel("Cancelar", key=f"{key_prefix}_btn_cancel", type="secondary"):
            st.rerun()

        if button_submit("Si, Eliminar", key=f"{key_prefix}_btn_eliminar"):
            with st.spinner("Eliminando registro..."):
                try:
                    # Pasamos el token explícitamente como defensa adicional
                    # (no dependemos solo del ContextVar, que es frágil).
                    res = delete_request(endpoint, token=token)

                    if res:
                        st.success("Registro eliminado correctamente.")
                        if session_state_update_key:
                            if session_state_update_key not in st.session_state:
                                st.session_state[session_state_update_key] = 0
                            else:
                                st.session_state[session_state_update_key] += 1

                    else:
                        st.error(
                            "Error al eliminar el registro. Por favor, intenta nuevamente."
                        )

                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"Error al eliminar: {e}")


# --------------------------------------------------
def _a_texto(valor: Any) -> str:
    """
    Convierte escalares de ``pandas``/``numpy`` a ``str`` saneado.

    Normaliza ``None``, ``numpy.nan``, ``pd.NA`` y ``pd.NaT`` a cadena
    vacía. Necesario porque ``DataFrame.to_dict()``
    (usado por la grilla para pasar ``datos_carga``) puede traer ``NaN``
    en campos opcionales como ``cuit``, y ``NaN`` no es JSON válido.

    Args:
        valor: Cualquier escalar proveniente de una fila del DataFrame.

    Returns:
        Cadena limpia (vacía si el valor era nulo).
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if pd.isna(valor):  # numpy.nan, pd.NA, pd.NaT
        return ""
    if isinstance(valor, float) and valor.is_integer():
        # Float entero (p.ej. 354.0): pierde la parte decimal para
        # coincidir con el valor canónico "354" de las referencias.
        return str(int(valor))
    return str(valor)


# --------------------------------------------------
def _a_fecha(valor: Any) -> date | None:
    """
    Convierte un escalar de fecha a ``datetime.date``.

    Acepta ``datetime``, ``date``, ``pd.Timestamp``/``NaT`` y strings
    en los formatos habituales de la API (``"2026-09-23"``,
    ``"2026-09-23T00:00:00"``, ``"23/09/2026"``).

    Args:
        valor: Cualquier escalar proveniente de una fila.

    Returns:
        ``date`` o ``None`` si el valor es nulo o no reconocido (para
        que el widget caiga en su default).
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if pd.isna(valor):
        return None
    texto: str = str(valor).strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None
