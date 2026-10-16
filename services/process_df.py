"""
Servicio de transformación de DataFrames crudos (CSV legados del
sistema anterior) a DataFrames estructurados según los modelos
Pydantic de ``models/schemas.py``.

No importa ``streamlit`` ni realiza llamadas HTTP (AGENTS.md §1).
"""

__all__ = [
    "apply_text_filters",
]


import pandas as pd


# --------------------------------------------------
def apply_text_filters(
    df: pd.DataFrame,
    filters: dict[str, str],
) -> pd.DataFrame:
    """
    Aplica filtros de texto en cascada sobre un DataFrame (frontend puro).

    Cada entrada ``{columna: valor}`` conserva las filas cuyo valor de
    ``columna`` contiene ``valor`` (búsqueda literal sin regex,
    case-insensitive). Las entradas con valor vacío se ignoran.

    Pensada para los filtros particulares de tabla que renderiza
    ``components.text_inputs.text_filters_bar()``.

    Args:
        df: DataFrame a filtrar (no se modifica en el lugar).
        filters: Dict ``{nombre_columna: texto_buscado}``.

    Returns:
        Subconjunto de ``df`` que satisface todos los filtros.

    Raises:
        KeyError: Si ``filters`` menciona una columna inexistente en
            ``df`` (error de configuración; se propaga sin silenciar).
    """
    df_filtrado: pd.DataFrame = df
    for columna, valor in filters.items():
        if not valor:
            continue
        df_filtrado = df_filtrado[
            df_filtrado[columna].astype(str).str.contains(
                valor, case=False, regex=False
            )
        ]
    return df_filtrado

# --------------------------------------------------
def _parse_moneda(valor: object) -> float:
    """
    Convierte un monto con formato argentino a ``float``.

    Ejemplos:
        ``"1,770,025.00"`` -> ``1770025.0``
        ``"8,850.13"``     -> ``8850.13``
        ``"TOTALES"``      -> ``0.0``
        ``""``             -> ``0.0``

    Args:
        valor: Celda cruda (cualquier tipo).

    Returns:
        El monto como ``float``. ``0.0`` si el valor no es
        numérico o está vacío (nunca lanza excepción, para no
        interrumpir la transformación de filas vecinas válidas).
    """
    if pd.isna(valor):
        return 0.0
    texto: str = str(valor).strip().replace(",", "")
    if texto in ("", "-", "TOTALES", "nan", "NaN"):
        return 0.0
    try:
        return float(texto)
    except ValueError:
        return 0.0


# --------------------------------------------------
def _texto_limpio(valor: object) -> str:
    """
    Convierte un escalar de pandas/numpy a ``str`` saneado.

    Normaliza ``None``/``NaN``/``pd.NA`` a cadena vacía y recorta la
    parte decimal de los floats enteros (p.ej. ``354.0`` -> ``"354"``)
    para coincidir con el valor canónico del padrón.

    Args:
        valor: Cualquier escalar proveniente de una fila.

    Returns:
        Cadena limpia (vacía si el valor era nulo).
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if pd.isna(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)