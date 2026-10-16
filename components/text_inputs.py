__all__ = ["text_input_advance_filter", "text_filters_bar", "op_map"]

from typing import Any

import streamlit as st


# --------------------------------------------------
def text_input_advance_filter(
    key: str = "text_input_advance_filter", **kwargs: Any
) -> str:
    """
    Input de texto especializado para filtros avanzados dinámicos.

    Muestra una guía inline con operadores soportados (``=``, ``!=``,
    ``>``, ``>=``, ``<``, ``<=``, ``~``), tips de formato y atajos
    de regex. La sintaxis completa se documenta en el ``helper_text``.

    Args:
        key: Key única para el widget.
        **kwargs: Argumentos adicionales pasados a ``st.text_input``.

    Returns:
        El texto ingresado por el usuario.
    """
    helper_text: str = """ 
        ### 🔍 Guía de Filtros Dinámicos
        Podés combinar múltiples filtros usando comas (`,`).

        | Operador | Significado | Ejemplo |
        | :--- | :--- | :--- |
        | `=` | Igual a | `ejercicio=2024` |
        | ` ! ` ` = ` | Desigual | `fuente!=str:11` |
        | `>` | Mayor que | `importe>50000` |
        | `>` `=` | Mayor o igual | `fecha>=2024-01-01` |
        | `<` | Menor que | `limite<100` |
        | `<` `=` | Menor o igual | `offset<=10` |
        | `~` | Contiene (Regex) | `desc_obra~54 viv` |

        ---

        ### 💡 Tips de Formato
        * **Forzar Texto:** `grupo=str:2` (útil para IDs numéricos guardados como texto).
        * **Forzar Número:** `codigo=num:101`.

        ---

        ### 🧩 Atajos de Búsqueda (Regex)
        El operador ` ~ ` es insensible a mayúsculas y permite usar comodines:

        * **Posición:**
            * ` ^ ` Inicio: `desc_obra~^54` (Empieza con 54).
            * ` $ ` Fin: `expediente~2023$` (Termina en 2023).
        * **Comodines:**
            * ` . ` Uno solo: `obra~v.v` (Busca viv, vav, vuv...).
            * ` .* ` Varios: `obra~54.*viv` (Busca '54' seguido de cualquier cosa y luego 'viv').
        * **Lógica:**
            * ` | ` O (OR): `fuente~10|11` (Que sea fuente 10 o fuente 11).
            * ` [ ] ` Rango: `ejercicio~202[4-6]` (Busca 2024, 2025 o 2026).
        * **Especiales:**
            * ` ^(?!.*texto) ` No contiene: `obra~^(?!.*cancelada)` (Obras que NO digan cancelada).
        """
    with st.container(border=False, width="stretch"):
        text: str = st.text_input(
            "Filtro avanzado",
            value="",
            placeholder="ej: ejercicio=2024, fuente!=str:11",
            help=helper_text,
            key=key,
            **kwargs,
        )
    return text


# Mapa de operadores del lenguaje de filtros a operadores MongoDB.
op_map: dict[str, str] = {
    ">=": "$gte",
    "<=": "$lte",
    "!=": "$ne",
    ">": "$gt",
    "<": "$lt",
    "=": "$eq",
    "~": "$regex",
}


# --------------------------------------------------
def text_filters_bar(
    filters: list[dict[str, str]],
    key_prefix: str,
    columns: int = 3,
) -> dict[str, str]:
    """
    Barra de filtros de texto particulares (frontend puro) en columnas.

    Cada filtro requiere al menos ``label`` y ``column``; acepta
    ``placeholder`` y ``help``. La key del widget se deriva como
    ``{column}_{key_prefix}`` para evitar colisiones entre reportes.

    No toca la API: los valores retornados se aplican en cascada sobre
    el DataFrame con
    ``services.process_df.apply_text_filters()``.

    Args:
        filters: Lista de dicts con la configuración de cada filtro
            (``label``, ``column``, ``placeholder?``, ``help?``).
        key_prefix: Prefijo único del reporte para las keys de widgets.
        columns: Cantidad de columnas por fila.

    Returns:
        Dict ``{columna: valor_ingresado}``; vacío si ``filters`` está
        vacío.
    """
    if not filters:
        return {}

    valores: dict[str, str] = {}
    cols = st.columns(columns)
    for index, filtro in enumerate(filters):
        with cols[index % columns]:
            valores[filtro["column"]] = st.text_input(
                filtro["label"],
                placeholder=filtro.get("placeholder", ""),
                help=filtro.get("help"),
                key=f"{filtro['column']}_{key_prefix}",
            )
    return valores
