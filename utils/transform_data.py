__all__ = [
    "build_retenciones_payload",
    "formato_moneda_ar",
    "parse_moneda_ar",
    "normalize_name_for_match",
]

import re
from typing import Any

import pandas as pd


# --------------------------------------------------
def normalize_name_for_match(name: Any) -> str:
    """
    Normaliza un nombre para hacer matching robusto entre fuentes
    heterogéneas (con/sin coma, con prefijos como ``(JUBILADO)`` o
    ``[LP]``, mayúsculas/minúsculas distintas, etc.).

    La idea es generar una clave estable que permita emparejar
    variaciones del mismo agente sin alterar el nombre original que
    se conserva en el DataFrame.

    Args:
        name: Nombre crudo (cualquier tipo; ``None``/``NaN`` -> ``""``).

    Returns:
        Clave normalizada en mayúsculas y sin puntuación.
    """
    if pd.isna(name):
        return ""
    text: str = str(name).upper().strip()
    # 1. Quitar prefijos opcionales entre paréntesis o corchetes al inicio.
    text = re.sub(r"^\s*[\(\[][^\)\]]*[\)\]]\s*", "", text)
    # 2. Reemplazar comas y puntos y coma por espacios.
    text = re.sub(r"[,;]", " ", text)
    # 3. Colapsar espacios múltiples.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --------------------------------------------------
def build_retenciones_payload(data: dict) -> dict:
    # Mapeo de campos del objeto a códigos contables de Planillometro.
    mapeo_codigos = {
        "iibb": "101",
        "sellos": "102",
        "lp": "104",
        "embargo": "255",
        "descuento": "341",
        "seguro": "413",
    }

    payload_items = []

    for campo, codigo in mapeo_codigos.items():
        # Obtenemos el valor, si no existe o no es numérico usamos 0
        valor = data.get(campo, 0)

        # Filtro: Solo agregamos si es mayor a 0
        if valor > 0:
            payload_items.append(
                {
                    "codigo": codigo,
                    "importe": round(float(valor), 2),  # Aseguramos 2 decimales
                }
            )

    return {"retenciones": payload_items}


# --------------------------------------------------
def formato_moneda_ar(valor: object) -> str:
    # Formato inicial: 1,234.56 -> X para no solapar reemplazos
    return f"$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------
def parse_moneda_ar(valor: Any) -> float:
    """
    Convierte un importe con formato argentino a ``float``.

    Inverso de :func:`formato_moneda_ar`: acepta tanto el valor
    numerico crudo como la cadena ya formateada (``"$ 1.234,56"``).

    Args:
        valor: Importe numerico o cadena con formato AR/US.

    Returns:
        El importe como ``float``. ``0.0`` si el valor es nulo o no
        numerico (best-effort, igual que ``_parse_moneda`` de
        ``services/process_df.py``: no interrumpe al caller).
    """
    if valor is None or pd.isna(valor):
        return 0.0
    if isinstance(valor, str):
        texto: str = valor.strip().replace("$", "").replace(" ", "")
        if texto == "" or texto.lower() in ("nan", "-"):
            return 0.0
        if "," in texto and "." in texto:
            # El ultimo separador es el decimal: "1.234,56" (AR)
            # o "1,234.56" (US).
            if texto.rfind(",") > texto.rfind("."):
                texto = texto.replace(".", "").replace(",", ".")
            else:
                texto = texto.replace(",", "")
        elif "," in texto:
            # Sin punto: la coma es el separador decimal ("1234,56").
            texto = texto.replace(",", ".")
        elif texto.count(".") > 1:
            # Varios puntos: todos son de miles ("1.234.567").
            texto = texto.replace(".", "")
        elif texto.count(".") == 1:
            parte_entera, _, parte_decimal = texto.partition(".")
            if len(parte_decimal) > 2:
                # Un solo punto con 3+ digitos: miles ("1.234").
                texto = parte_entera + parte_decimal
        try:
            return float(texto)
        except ValueError:
            return 0.0
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0
