__all__ = [
    "button_update",
    "button_export",
    "button_submit",
    "button_cancel",
    "button_add",
    "button_edit",
    "button_delete",
    "button_selfadd",
    "button_robot",
]

from typing import Any

import streamlit as st

DEFAULT_WIDTH = 120


# --------------------------------------------------
def button_update(label: str, key: str = "button_update", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón."""
    with st.container(border=False, width="content"):
        return st.button("🔄 " + label, key=key, width=DEFAULT_WIDTH, **kwargs)


# --------------------------------------------------
def button_export(label: str, key: str = "button_export", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón."""
    with st.container(border=False, width="content"):
        return st.button("📤 " + label, key=key, width=DEFAULT_WIDTH, **kwargs)


# --------------------------------------------------
def button_submit(label: str, key: str = "button_submit", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón (primario)."""
    with st.container(border=False, width="content"):
        return st.button(
            "🗳️ " + label, key=key, width=DEFAULT_WIDTH, **kwargs, type="primary"
        )


# --------------------------------------------------
def button_cancel(label: str, key: str = "button_cancel", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón."""
    with st.container(border=False, width="content"):
        return st.button("❌ " + label, key=key, width=DEFAULT_WIDTH, **kwargs)


# --------------------------------------------------
def button_add(label: str, key: str = "button_add", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón."""
    with st.container(border=False, width="content"):
        return st.button("💾 " + label, key=key, width=DEFAULT_WIDTH, **kwargs)


# --------------------------------------------------
def button_edit(label: str, key: str = "button_edit", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón."""
    with st.container(border=False, width="content"):
        return st.button("✏️ " + label, key=key, width=DEFAULT_WIDTH, **kwargs)


# --------------------------------------------------
def button_delete(label: str, key: str = "button_delete", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón."""
    with st.container(border=False, width="content"):
        return st.button("🗑️ " + label, key=key, width=DEFAULT_WIDTH, **kwargs)


# --------------------------------------------------
def button_selfadd(label: str, key: str = "button_selfadd", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón."""
    with st.container(border=False, width="content"):
        return st.button("🔮 " + label, key=key, width=DEFAULT_WIDTH, **kwargs)


# --------------------------------------------------
def button_robot(label: str, key: str = "button_robot", **kwargs: Any) -> bool:
    """Componente reutilizable: retorna ``True`` si se presiona el botón (primario)."""
    with st.container(border=False, width="content"):
        return st.button(
            "📎 " + label, key=key, width=DEFAULT_WIDTH, **kwargs, type="primary"
        )
