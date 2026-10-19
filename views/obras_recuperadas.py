"""
Author: Fernando Corrales <fscpython@gmail.com>
Purpose: Planillometro's "Obras Recuperadas" view
"""

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

import utils.exceptions as ex
from components import text_filters_bar
from services.data_fetcher import get_ejercicios_list, get_obras_recuperadas
from services.process_df import apply_text_filters
from utils.endpoints import Endpoints
from views import (
    ReportState,
    dataframe_with_buttons,
    modal_delete_registro_gral,
    modal_obras_recuperadas,
    report_data_version_key,
    report_header,
)

REPORTE = "obras_recuperadas"
# Filtros particulares de la grilla (frontend puro): se renderizan con
# text_filters_bar() y se aplican en cascada con apply_text_filters()
# sobre el DataFrame ya obtenido de la API, sin volver a tocar la API.
FILTROS_TABLA: list[dict[str, str]] = [
    {"label": "Cod. barrio", "column": "cod_barrio", "placeholder": "Ej: 884"},
    {
        "label": "Estructura",
        "column": "estructura",
        "placeholder": "Ej: 11-00-02-79-421",
    },
]


# --------------------------------------------------
def add_obras_recuperadas() -> None:
    modal_obras_recuperadas(
        key_prefix=f"add_obras_recuperadas_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    )


# --------------------------------------------------
def edit_obras_recuperadas(datos_edicion: dict[str, Any]) -> None:
    modal_obras_recuperadas(
        key_prefix=f"edit_obras_recuperadas_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        datos_carga=datos_edicion,
        es_edicion=True,
    )


# --------------------------------------------------
def delete_obras_recuperadas(datos_eliminar: dict[str, Any]) -> None:
    modal_delete_registro_gral(
        endpoint=f"{Endpoints.OBRAS_RECUPERADAS.value}/delete_one/{datos_eliminar['id']}",
        desc_registro=f"con código de barrio {datos_eliminar['cod_barrio']} y estructura {datos_eliminar['estructura']}",
        session_state_update_key=report_data_version_key(REPORTE),
        key_prefix=f"delete_obras_recuperadas_{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )


# --------------------------------------------------
def render() -> None:
    mis_filtros = [
        {
            "label": "Elija los ejercicios a consultar",
            "options": get_ejercicios_list(),
            "query_param": "ejercicio",
            "key": "ejercicios_" + REPORTE,
            "default": get_ejercicios_list()[-1],
        },
    ]

    # La cabecera (título, filtros, export) es un @st.fragment que retorna
    # el estado del reporte: no hace falta leer nada de session_state.
    state: ReportState = report_header(
        key=REPORTE,
        title=REPORTE.capitalize(),
        description="",
        endpoint=Endpoints.OBRAS_RECUPERADAS.value,
        filters_config=mis_filtros,
        has_export=True,
    )

    # Ejecutamos la lógica con el servicio cacheado (@st.cache_data vive
    # en services/data_fetcher.py desde que AGENTS.md §1 lo autorizó).
    # state.data_version se incrementa al crear/editar/borrar registros
    # y sirve de update_trigger para invalidar ese caché.
    df_obras_recuperadas = pd.DataFrame()  # type: ignore  # fallback por defecto
    try:
        df_obras_recuperadas = get_obras_recuperadas(
            filtro_avanzado=state.filtro_avanzado,
            update_trigger=state.data_version,
        )
        if df_obras_recuperadas.empty:
            st.info("No se encontraron resultados.")
    except ex.APIConnectionError as exc:
        st.error(f"🌐 {exc}")
    except ex.APIResponseError as exc:
        st.error(f"⚠️ {exc}")

    # Mostrar resultados (usando session_state para que no desaparezcan)
    if not df_obras_recuperadas.empty:
        # Filtros particulares de la grilla (frontend puro, sin llamadas
        # a la API): declarativos en FILTROS_TABLA y aplicados en cascada.
        with st.container(horizontal=False, border=True, width="stretch"):
            valores_filtro = text_filters_bar(FILTROS_TABLA, key_prefix=REPORTE)
            df_vista = apply_text_filters(df_obras_recuperadas, valores_filtro)

            dataframe_with_buttons(
                df_vista,
                key=f"{REPORTE}_df_obras_recuperadas",
                height=300,
                column_order=[
                    "ejercicio",
                    "estructura",
                    "cod_barrio",
                    "importe",
                    "notas",
                ],
                selection_mode="single-row",
                add_func=add_obras_recuperadas,
                edit_func=edit_obras_recuperadas,
                delete_func=delete_obras_recuperadas,
            )


if __name__ == "__main__":
    render()
