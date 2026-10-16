#!/usr/bin/env python3
"""
Author: Fernando Corrales <fscpython@gmail.com>
Purpose: Working With Files in Python
Source: https://realpython.com/working-with-files-in-python/#:~:text=To%20get%20a%20list%20of,scandir()%20in%20Python%203.
"""

__all__ = [
    "get_df_from_sql_table",
    "read_xls",
    "read_csv_file",
]


import logging
import sqlite3
from io import BytesIO
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# --------------------------------------------------
def get_df_from_sql_table(sqlite_path: str, table: str) -> pd.DataFrame:
    """
    Carga una tabla SQLite en un DataFrame.

    Args:
        sqlite_path: Ruta al archivo ``.sqlite``/``.db``.
        table: Nombre de la tabla.

    Returns:
        DataFrame con todo el contenido de la tabla.
    """
    with sqlite3.connect(sqlite_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)


# --------------------------------------------------
def read_xls(file_path: str | Path, header: int = 0) -> pd.DataFrame:
    """
    Lee un archivo Excel y devuelve todas las columnas como ``str``.

    Args:
        file_path: Ruta al archivo Excel.
        header: Fila a usar como encabezado (default 0). Si es 0, se
            reemplazan las columnas por índices string numéricos
            ``"0"..N-1``.

    Returns:
        DataFrame con los datos.
    """
    df: pd.DataFrame = pd.read_excel(
        file_path, index_col=None, header=header, na_filter=False, dtype=str
    )
    if header == 0:
        df.columns = [str(x) for x in range(df.shape[1])]
    return df


# --------------------------------------------------
def read_csv_file(
    file_path: str | Path | BytesIO, encoding: str = "ISO-8859-1"
) -> pd.DataFrame:
    """
    Lee un CSV admitiendo hasta 100 columnas y normalizando nombres a
    índices numéricos (``"0"..`` ``"99"``).

    Args:
        file_path: Ruta al CSV o buffer en memoria.
        encoding: Encoding del CSV (default ISO-8859-1 por compatibilidad
            con archivos generados por el sistema legado).

    Returns:
        DataFrame con los datos. Vacío si hubo error de lectura.
    """
    nombres_columnas: list[str] = [str(i) for i in range(100)]
    try:
        df: pd.DataFrame = pd.read_csv(
            file_path,
            names=nombres_columnas,
            index_col=None,
            header=None,
            na_filter=False,
            dtype=str,
            encoding=encoding,
        )
        df.columns = [str(x) for x in range(df.shape[1])]
        return df
    except (OSError, UnicodeDecodeError, ValueError) as read_exc:
        logger.error("Error al leer el archivo CSV: %s", read_exc)
        return pd.DataFrame()
