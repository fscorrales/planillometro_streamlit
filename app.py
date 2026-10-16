"""INVICO Planillometro — Entrypoint principal.

Gestiona el flujo de autenticación (Login) y la navegación MPA
con los módulos de Precarizados, Honorarios y Reportes.
"""

import os
import time

import streamlit as st

from services import sincronizar_caches
from utils.context import clear_token, set_token
from utils.version import get_version
from views.aux_tables import report_data_version_key
from views.login import render_login

st.set_page_config(
    page_title="Planillometro",
    page_icon="🏢",
    layout="wide",
)

st.markdown(
    """
    <style>
        .stAppDeployButton {
            display: none !important;
        }
    </style>
""",
    unsafe_allow_html=True,
)


# Control de cierre de aplicación
if "app_closing" not in st.session_state:
    st.session_state.app_closing = False

if st.session_state.app_closing:
    st.empty()
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] {display: none;}
        </style>
    """,
        unsafe_allow_html=True,
    )

    st.write("#")
    st.success("### 🔒 Sesión Finalizada")
    st.write("La aplicación de **INVICO Planillometro** se ha detenido correctamente.")
    st.info("Ya puedes cerrar esta ventana del navegador.")

    time.sleep(1)
    os._exit(0)


# ──────────────────────────────────────────────
# Inicialización del estado de sesión
# ──────────────────────────────────────────────
def initialize_state() -> None:
    """
    Inicializa las claves mínimas en ``session_state`` y sincroniza el
    token con el contexto de servicios.

    El contexto (``utils.context``) es leído por los servicios
    (``services/api.py``) como fallback cuando el caller no les
    pasa el token explícitamente. Esto evita tener que "threading" el
    token a través de cada llamada.
    """
    if "token" not in st.session_state:
        st.session_state["token"] = None
    if "user" not in st.session_state:
        st.session_state["user"] = None

    # Propagar el token de session_state al contexto de servicios
    current_token = st.session_state.get("token")
    if current_token:
        set_token(current_token)
    else:
        clear_token()


# ──────────────────────────────────────────────
def incrementar_triggers_sincronizacion() -> int:
    """
    Incrementa (creándolos si faltan) los triggers de ``session_state``
    que invalidan el ``@st.cache_data`` de cada colección.

    Se incrementan ``precarizados_data_version`` y
    ``honorarios_dataframes_iteration`` (éste obliga a las vistas de
    honorarios a ir a la API en vez del snapshot rápido de 24h) y, de
    paso, cualquier otra clave ``*_data_version`` ya presente en la
    sesión para que futuras vistas entren en la misma invalidación
    masiva.

    Returns:
        Valor ya incrementado del trigger de precarizados, listo para
        pasarse como ``update_trigger`` a ``sincronizar_caches``.
    """
    claves: list[str] = [
        report_data_version_key("precarizados"),
        "honorarios_dataframes_iteration",
    ]
    # Barrido genérico de otras vistas registradas en la sesión
    # (claves únicas: las dos conocidas ya están en la lista).
    claves.extend(
        clave
        for clave in list(st.session_state.keys())
        if clave.endswith("_data_version") and clave not in claves
    )

    for clave in claves:
        st.session_state[clave] = int(st.session_state.get(clave, 0)) + 1

    return int(st.session_state[report_data_version_key("precarizados")])


# ──────────────────────────────────────────────
# Navegación MPA
# ──────────────────────────────────────────────
def build_navigation() -> None:
    """Construye la navegación con st.navigation y ejecuta la página."""
    user = st.session_state.get("user") or {}
    username = user.get("username", "Usuario")

    pages: list[st.Page] = [
        st.Page(
            "views/obras_recuperadas.py",
            title="Obras Recuperadas",
            icon="👥",
        ),
        st.Page(
            "views/obras_desactivadas.py",
            title="Obras Desactivadas (otros motivos)",
            icon="💼",
        ),
        st.Page(
            "views/reportes.py",
            title="Reportes (en construcción)",
            icon="📊",
        ),
    ]

    pg = st.navigation(pages)

    # Sidebar: Info de usuario, logout y versión
    with st.sidebar:
        if st.button(
            "🔄 Sincronizar Datos",
            use_container_width=True,
            help=(
                "Invalida los cachés (memoria y triggers), baja el "
                "padrón de Precarizados, refresca las listas de "
                "referencia y deja a cada vista bajando sus datos "
                "frescos desde la API."
            ),
        ):
            # 1) Invalida los triggers de sesión (grillas y referencias).
            trigger_precarizados = incrementar_triggers_sincronizacion()

            # 2) Sincronización ligera: limpia la memoria, refresca el
            #    padrón y los Parquet de las listas de referencia.
            #    Honorarios sólo se invalida: cada vista baja su
            #    ejercicio cuando lo necesita.
            with st.spinner("Sincronizando con la API..."):
                actualizados, errores = sincronizar_caches(
                    trigger_precarizados=trigger_precarizados,
                )

            # 3) Informe de fallos: se persiste en sesión para que
            #    sobreviva al rerun (un fallo parcial no debe pasar
            #    inadvertido). Una sync OK lo limpia.
            st.session_state["informe_errores_sincronizacion"] = [
                f"⚠️ **{recurso}**: {mensaje}" for recurso, mensaje in errores.items()
            ]

            if not errores:
                resumen: str = " · ".join(
                    f"{recurso}: {cantidad} registros"
                    for recurso, cantidad in actualizados.items()
                )
                st.toast(
                    f"✅ Sincronizado — {resumen} · Honorarios: "
                    "caché invalidado (bajado por vista/modal)",
                    icon="🚀",
                )
                time.sleep(1)  # Deja ver el toast antes del rerun
                st.rerun()
            # Con errores NO se rerunea: el informe de abajo queda a
            # la vista y el usuario puede reintentar.

        # Errores del último intento de sincronización (si los hubo).
        for mensaje in st.session_state.get("informe_errores_sincronizacion", []):
            st.error(mensaje)

        st.divider()

        # Bloque de Usuario y Logout
        cols = st.columns([0.6, 0.4], vertical_alignment="center")
        cols[0].write(f"👤 **{username}**")

        if cols[1].button("Log out", key="logout_btn"):
            st.session_state.app_closing = True
            st.session_state["token"] = None
            st.session_state["user"] = None
            clear_token()  # Limpiar también el contexto de servicios
            st.rerun()

        with st.container():
            st.caption(f"Versión: {get_version()}", text_alignment="center")

    # CSS para optimizar el padding superior
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 1rem !important;
            }
            .stAppHeader {
                background-color: transparent !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    pg.run()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main() -> None:
    initialize_state()

    # Si el usuario no está autenticado, mostramos la pantalla de login
    if not st.session_state.get("token"):
        render_login()
    else:
        build_navigation()


if __name__ == "__main__":
    main()
