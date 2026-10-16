__all__ = [
    "ReportState",
    "report_filter_key",
    "report_selections_key",
    "report_data_version_key",
    "report_header",
    "report_template",
    "dataframe_with_buttons",
]

import time
from collections.abc import Callable
from typing import Any, NamedTuple

import pandas as pd
import streamlit as st

from components.buttons import (
    button_add,
    button_delete,
    button_edit,
    button_export,
    button_submit,
)
from components.dataframes import dataframe
from components.multiselects import multiselect_filter
from components.text_inputs import text_input_advance_filter
from services.api import fetch_excel_stream, post_request
from utils.context import sync_session_token
from utils.handling_files import read_csv_file


# --------------------------------------------------
def params_preparation(
    selections: list[tuple[str, list[Any]]] | None = None,
    filtro_avanzado: str = "",
) -> dict[str, Any]:
    """
    Prepara los parámetros de la API a partir de selecciones y filtro avanzado.

    Args:
        selections: Lista de tuplas ``(nombre_param, valores)`` (e.g. desde
            multiselects). ``valores`` se serializa como string separado por comas.
        filtro_avanzado: Cadena con el filtro dinámico (e.g. ``ejercicio=2024``).

    Returns:
        Diccionario listo para enviar como query params.
    """
    params_peticion: dict[str, Any] = {"limit": 0, "queryFilter": filtro_avanzado}

    if selections:
        for nombre_param, valores in selections:
            if valores:
                params_peticion[nombre_param] = ",".join(map(str, valores))

    return params_peticion


# --------------------------------------------------
class ReportState(NamedTuple):
    """
    Estado que :func:`report_header` retorna a la página caller.

    Attributes:
        filtro_avanzado: Valor vigente del filtro avanzado (``queryFilter``).
        selections: Tuplas ``(query_param, valores)`` de los multiselects
            server-side, listas para :func:`params_preparation`.
        data_version: Versión de datos del reporte; sirve como
            ``update_trigger`` de los ``@st.cache_data`` de servicios.
    """

    filtro_avanzado: str
    selections: list[tuple[str, list[Any]]]
    data_version: int


# --------------------------------------------------
def report_filter_key(report_key: str) -> str:
    """
    Clave de ``st.session_state`` donde ``report_header()`` sincroniza
    el filtro avanzado del reporte.

    Args:
        report_key: Identificador único del reporte (ej. ``precarizados``).

    Returns:
        Clave con formato ``{report_key}_advanced_filter``.
    """
    return f"{report_key}_advanced_filter"


# --------------------------------------------------
def report_data_version_key(report_key: str) -> str:
    """
    Clave de ``st.session_state`` con la versión de datos del reporte.

    Es el contador que ``report_header()`` incrementa tras cada carga
    de CSV y que los CRUD (modales, borrado) incrementan tras cada
    escritura, para invalidar el ``@st.cache_data`` de los servicios
    (ej. ``get_precarizados(update_trigger=...)``).

    Args:
        report_key: Identificador único del reporte (ej. ``precarizados``).

    Returns:
        Clave con formato ``{report_key}_data_version``.
    """
    return f"{report_key}_data_version"


# --------------------------------------------------
def report_selections_key(report_key: str) -> str:
    """
    Clave de ``st.session_state`` donde ``report_header()`` sincroniza
    las selecciones de sus multiselects server-side (``filters_config``).

    Args:
        report_key: Identificador único del reporte (ej. ``precarizados``).

    Returns:
        Clave con formato ``{report_key}_selections``.
    """
    return f"{report_key}_selections"


@st.fragment  # Permite que los filtros internos no recarguen TODA la página
# --------------------------------------------------
def report_header(
    key: str,
    title: str,
    endpoint: str,
    description: str,
    filters_config: list[dict[str, Any]] | None = None,
    has_export: bool = True,
    has_upload: bool = False,
    uploader_func: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    uploader_help: str | None = None,
) -> ReportState:
    """
    Cabecera reutilizable de un reporte: título, descripción, filtros
    server-side (multiselects + filtro avanzado), exportación a Excel y
    (opcional) carga de CSV.

    Es un ``@st.fragment``: las interacciones con los filtros, el
    uploader y el botón de exportación se resuelven sin re-ejecutar la
    página completa. Cuando un filtro **cambia**, se fuerza
    ``st.rerun()`` porque la página exterior —quien refetcha los datos—
    debe re-ejecutarse con el estado nuevo.

    Args:
        key: Identificador único del reporte. Prefijo de todas las keys
            de ``session_state`` que genera (ver Side Effects).
        title: Título renderizado como encabezado principal.
        endpoint: Endpoint base para la exportación
            (``{endpoint}/export``) y para el ``POST`` de carga.
        description: Párrafo informativo bajo el título.
        filters_config: Lista opcional de multiselects server-side.
            Cada dict requiere ``label``, ``options``, ``query_param`` y
            ``key``; acepta ``default``. Se retornan en
            ``ReportState.selections`` como ``(query_param, valores)``
            listos para :func:`params_preparation`.
        has_export: Habilita el botón de exportación a Excel.
        has_upload: Habilita el uploader CSV y su POST a ``endpoint``.
        uploader_func: Transformación opcional aplicada al ``DataFrame``
            leído del CSV antes de validarlo y cargarlo.
        uploader_help: Texto de ayuda del uploader CSV.

    Returns:
        :class:`ReportState` con el filtro avanzado vigente, las
        selecciones de los multiselects y la versión de datos. El caller
        usa este retorno para refetchar; no necesita leer
        ``session_state``.

    Side Effects:
        - ``st.session_state[report_filter_key(key)]``: espejo del
          filtro avanzado para otros consumidores.
        - ``st.session_state[report_selections_key(key)]``: espejo de
          las selecciones de los multiselects.
        - ``st.session_state[report_data_version_key(key)]``: contador
          que el caller puede usar como ``update_trigger`` de caché.
        - ``st.session_state[f"temp_file_{key}"]``: binario del Excel
          pendiente de descarga.
    """
    # CRÍTICO: Streamlit ejecuta ``@st.fragment`` en un contexto de script
    # separado donde los ``ContextVar`` (token) NO se heredan del script
    # principal. Sin esta sincronización, ``post_request`` (línea más abajo)
    # fallaría con ``APIConnectionError("No hay token de sesión...")``.
    token = sync_session_token(st.session_state.get("token"))

    data_version_key: str = report_data_version_key(key)
    if data_version_key not in st.session_state:
        st.session_state[data_version_key] = 0

    # Selecciones de los multiselects server-side (se llenan al renderizar)
    selections: list[tuple[str, list[Any]]] = []

    st.markdown(f"# {title}")
    st.write(description)

    # 0. Lógica de Exportación
    def download_file():
        # Validamos filtros antes de proceder
        try:
            # Limpiamos basura anterior antes de empezar el proceso pesado
            if f"temp_file_{key}" in st.session_state:
                del st.session_state[f"temp_file_{key}"]
            with st.spinner("Preparando archivos Excel..."):
                # Llamada a la API que devuelve StreamingResponse
                excel_binario = fetch_excel_stream(
                    f"{endpoint}/export",
                    params_preparation(selections, filtro_avanzado),
                )

                if excel_binario:
                    # IMPORTANTE: Como st.download_button recarga la página,
                    # a veces es mejor usar un link o guardarlo en session_state
                    st.session_state[f"temp_file_{key}"] = excel_binario
                    st.success("✅ Archivo generado con éxito.")
                    st.rerun()

        except Exception as e:
            st.error(f"Error al exportar: {e}")

    # 1. Renderizar Filtros (server-side: afectan los params del fetch)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        if filters_config:
            for filter_conf in filters_config:
                selected_values = multiselect_filter(
                    label=filter_conf["label"],
                    options=filter_conf["options"],
                    default=filter_conf.get("default", []),
                    key=filter_conf["key"],
                )
                # El nombre de la clave debe coincidir con lo que espera la API
                selections.append((filter_conf["query_param"], selected_values))

        filtro_avanzado = text_input_advance_filter(
            key="text_input_advance_filter-" + key
        )

        uploaded_file = (
            st.file_uploader(
                f"Cargar CSV de {title}",
                type=["csv"],
                key=f"{key}_upload_file_{st.session_state[data_version_key]}",
                label_visibility="visible",
                disabled=not has_upload,  # Add this line to disable the uploader if has_upload is False´
                accept_multiple_files=False,
                help=uploader_help,
            )
            if has_upload
            else None
        )

        if has_export:
            # Aquí podrías integrar tu logic de exportación
            if f"temp_file_{key}" not in st.session_state:
                if button_export("Exportar a Excel", key=f"button_export_{key}"):
                    download_file()
            else:
                # Si hay archivo, el botón "Exportar" desaparece y aparece el de "Descargar"
                st.download_button(
                    label="📥 GUARDAR EXCEL",
                    data=st.session_state[f"temp_file_{key}"],
                    file_name=f"reporte_{key}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"btn_dl_{key}",
                    type="primary",  # Lo ponemos en color para que resalte
                    on_click=lambda: st.session_state.pop(f"temp_file_{key}"),
                )

    if uploaded_file:
        df = read_csv_file(uploaded_file)
        if uploader_func:
            df = uploader_func(df)
        # Validación Visual (El "seguro" del usuario)
        col1, col2, col3 = st.columns(3)
        col1.metric("Filas a procesar", len(df))
        col2.metric("Columnas", len(df.columns))
        col3.info("Validación: OK" if not df.empty else "Error: CSV Vacío o Incorrecto")

        with st.expander("Ver vista previa de datos limpios"):
            st.dataframe(df.head(10), width="stretch")

        if not df.empty:
            with st.container(horizontal=True, horizontal_alignment="center"):
                if button_submit("Confirmar CARGA BD", key=f"btn_add_{key}"):
                    with st.spinner("Ejecutando script de carga..."):
                        # Transformación final para Mongo
                        registros = df.to_dict(orient="records")

                        res = post_request(endpoint, registros, token=token)

                        if res:
                            # 1. Extraer datos principales
                            titulo = res.get("title", "Sincronización")
                            agregados = res.get("added", 0)
                            eliminados = res.get("deleted", 0)
                            lista_errores = res.get("errors", [])
                            num_errores = len(lista_errores)

                            # 2. Toast Combinado (Resumen Ejecutivo)
                            # Ejemplo: 📊 Epam: +160 agregados, -160 eliminados.
                            mensaje_toast = f"📊 {titulo}: +{agregados} agregados, -{eliminados} eliminados."

                            if num_errores > 0:
                                mensaje_toast += f" ({num_errores} con errores)"
                                st.toast(mensaje_toast, icon="⚠️")
                            else:
                                st.toast(mensaje_toast, icon="✅")

                            # 3. Gestión de Errores Detallados (Si existen)
                            if num_errores > 0:
                                with st.expander(
                                    "❌ Detalle de Inconsistencias por Documento",
                                    expanded=True,
                                ):
                                    for error_doc in lista_errores:
                                        doc_id = error_doc.get(
                                            "doc_id", "ID Desconocido"
                                        )
                                        details = error_doc.get("details", [])

                                        st.markdown(f"**Documento ID:** `{doc_id}`")
                                        for det in details:
                                            # Estructura: loc, msg, error_type
                                            st.caption(
                                                f"📍 {det['loc']} | 🏷️ {det['error_type']}"
                                            )
                                            st.write(f"💬 {det['msg']}")
                                        st.divider()
                            else:
                                st.balloons()
                                st.session_state[data_version_key] += 1
                                time.sleep(3)
                                st.rerun()

    # Sincronizamos con session_state (por si otra capa lo lee) y, si el
    # filtro o las selecciones cambiaron, forzamos un rerun completo: un
    # cambio dentro del fragmento NO re-ejecuta la página exterior, que
    # es quien refetcha con el estado nuevo.
    filter_key: str = report_filter_key(key)
    previous_filter: str | None = st.session_state.get(filter_key)
    if previous_filter is None:
        st.session_state[filter_key] = filtro_avanzado
    elif previous_filter != filtro_avanzado:
        st.session_state[filter_key] = filtro_avanzado
        st.rerun()  # Forzamos que toda la página (fuera del fragmento) reaccione

    selections_key: str = report_selections_key(key)
    previous_selections: list | None = st.session_state.get(selections_key)
    if previous_selections is None:
        st.session_state[selections_key] = selections
    elif previous_selections != selections:
        st.session_state[selections_key] = selections
        st.rerun()

    return ReportState(
        filtro_avanzado=filtro_avanzado,
        selections=selections,
        data_version=int(st.session_state[data_version_key]),
    )


# --------------------------------------------------
def report_template(
    key: str,
    title: str,
    endpoint: str,
    description: str,
    has_export: bool = True,
    has_upload: bool = False,
    uploader_func: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    uploader_help: str | None = None,
) -> str:
    """
    Wrapper de compatibilidad de :func:`report_header`.

    Mantiene la firma histórica y retorna solo el filtro avanzado para
    los callers que no necesitan multiselects ni ``data_version``.
    """
    state: ReportState = report_header(
        key=key,
        title=title,
        endpoint=endpoint,
        description=description,
        has_export=has_export,
        has_upload=has_upload,
        uploader_func=uploader_func,
        uploader_help=uploader_help,
    )
    return state.filtro_avanzado


# --------------------------------------------------
def dataframe_with_buttons(
    df: pd.DataFrame,
    key: str = "df_with_btns",
    height: int = 150,
    column_order: list = [],
    selection_mode: str = None,
    add_func=None,
    edit_func=None,
    delete_func=None,
    show_buttons: bool = True,
    **kwargs,
):

    event = dataframe(
        df,
        key=f"{key}",
        height=height,
        column_order=column_order,
        on_select="rerun" if selection_mode else "ignore",
        selection_mode=selection_mode or "multi-row",
    )
    if show_buttons:
        with st.container(
            horizontal=True,
            border=False,
            width="stretch",
            horizontal_alignment="center",
            gap="medium",
        ):
            if button_add(
                "Agregar",
                key=f"btn_add_{key}",
                type="primary",
                disabled=not add_func,
            ):
                if add_func:
                    add_func()
            if button_edit("Editar", key=f"btn_edit_{key}", disabled=not edit_func):
                if edit_func:
                    if len(event.selection.rows) > 0:
                        selected_row_index = event.selection.rows[0]
                        datos_edicion = df.iloc[selected_row_index].to_dict()
                        edit_func(datos_edicion)
            if button_delete(
                "Borrar", key=f"btn_delete_{key}", disabled=not delete_func
            ):
                if delete_func:
                    if len(event.selection.rows) > 0:
                        selected_row_index = event.selection.rows[0]
                        datos_eliminar = df.iloc[selected_row_index].to_dict()
                        delete_func(datos_eliminar)
