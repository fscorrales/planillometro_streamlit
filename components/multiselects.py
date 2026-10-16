__all__ = ["multiselect_filter"]

from typing import Any

import streamlit as st


# --------------------------------------------------
def multiselect_filter(
    label: str,
    options: list[str],
    default: Any = None,
    key: str = "multiselect_filter",
    **kwargs,
):
    """Un componente reutilizable"""
    with st.container(border=False, width="stretch"):
        values = st.multiselect(
            label, options=options, default=default, key=key, **kwargs
        )
    return values
