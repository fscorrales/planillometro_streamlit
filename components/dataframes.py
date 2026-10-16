__all__ = ["dataframe"]

from typing import Any

import pandas as pd
import streamlit as st


# --------------------------------------------------
def dataframe(
    data: pd.DataFrame, key: str = "df", **kwargs: Any
) -> Any:
    """
    Wrapper de ``st.dataframe`` con configuraciones por defecto orientadas
    a tablas de gestión: oculta el índice y estira el ancho al contenedor.

    Args:
        data: DataFrame a mostrar.
        key: Key única para el widget.
        **kwargs: Argumentos adicionales pasados a ``st.dataframe``.

    Returns:
        El generador devuelto por ``st.dataframe``.
    """
    with st.container(border=False, width="stretch"):
        return st.dataframe(
            data,
            key=key,
            width="stretch",
            hide_index=True,
            **kwargs,
        )
