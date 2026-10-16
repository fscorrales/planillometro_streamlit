"""
Servicio de transformación de DataFrames crudos (CSV legados del
sistema anterior) a DataFrames estructurados según los modelos
Pydantic de ``models/schemas.py``.

No importa ``streamlit`` ni realiza llamadas HTTP (AGENTS.md §1).
"""

__all__ = [
    "process_informe_por_destino",
    "merge_informe_con_precarizados",
    "construir_payload_honorarios",
    "construir_payload_actualizacion_caratula",
    "componer_nro_comprobante",
    "separar_nro_comprobante",
    "apply_text_filters",
]


from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from models.schemas import (
    HonorarioReport,
    HonorariosUpdate,
    InformePorDestino,
)
from utils.handling_files import read_csv_file
from utils.transform_data import normalize_name_for_match


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
# Estructura del reporte "Resumen de Pagos por Destino"
# --------------------------------------------------
# El CSV crudo se lee con ``read_csv_file``, que normaliza los
# nombres de columna a índices numéricos de cadena
# (``"0".."99"``). Cada fila del reporte contiene:
#
#   - Posiciones  0..9  : metadatos (institución, título, fechas,
#                          filtros). El título está en la 1.
#   - Posiciones 10..25 : encabezados repetidos en cada fila
#                          (no son datos).
#   - Posiciones 26..40 : datos del registro individual.
#   - Posición      41  : literal "TOTALES" (marcador).
#   - Posiciones 42..50 : totales globales (constantes).
#   - Posiciones 51..52 : pie de página.
#
# Mapeo de datos a campos del modelo ``InformePorDestino``.
# Salvedades verificadas empíricamente sobre el reporte
# "Resumen de Pagos por Destino":
#
#   1. ``Firma`` (encabezado 18 / dato 34) NO forma parte del
#      modelo, por lo que las retenciones quedan en 34..39.
#   2. La posición 40 es el **NETO A PAGAR** (validado con
#      ``Monto - (32 + 33 + 34 + 38 + 39) == pos40`` en todas
#      las filas), NO un descuento. No se mapea al modelo.
#
# ``mutual`` y ``embargo`` no existen en el
# reporte -> se inicializan en 0.0 (campos no ``Optional``).
# --------------------------------------------------
_MAPEO_COLUMNAS: dict[str, int] = {
    "nombre_completo": 28,  # Proveedor
    "importe_bruto": 31,  # Monto Imponible
    "sellos": 32,  # Sellos
    "lp": 33,  # L. Pago
    "iibb": 34,  # IB
    "otras_retenciones": 36,  # O. Ret.
    "anticipo": 37,  # Antic.
    "seguro": 38,  # Seguro
    "descuento": 39,  # No existe en el reporte -> 0.0
}

# Campos del modelo sin contraparte en el reporte -> 0.0
_CAMPOS_SIN_DATO: tuple[str, ...] = ("mutual", "embargo")

# Título que identifica al reporte esperado (posición 1).
_TITULO_ESPERADO: str = "Resumen de Pagos por Destino"

# --------------------------------------------------
# Campos de la línea de un comprobante de honorarios.
#
# La **carátula** (compartida por todas las líneas de un comprobante)
# es: ejercicio, mes, fecha, nro_comprobante, cta_cte, tipo.
# Estos son los campos *por línea*, que se conservan sin cambios al
# editar la carátula y se toman del CSV al dar de alta.
# --------------------------------------------------
_CAMPOS_TEXTO_LINEA: tuple[str, ...] = (
    "cuit",
    "nombre_completo",
    "actividad",
    "partida",
)

_CAMPOS_MONTO: tuple[str, ...] = (
    "importe_bruto",
    "iibb",
    "lp",
    "sellos",
    "seguro",
    "otras_retenciones",
    "anticipo",
    "descuento",
    "mutual",
    "embargo",
)


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


# --------------------------------------------------
def _montar_registro(
    fila: dict[str, Any],
    *,
    ejercicio: int,
    mes: str,
    fecha: datetime,
    nro_comprobante: str,
    cta_cte: str,
    tipo: str,
) -> dict[str, Any]:
    """
    Arma un registro ``HonorarioReport`` a partir de una fila.

    Combina la **carátula** (parámetros, aplicados a todas las líneas
    del comprobante) con los **campos de línea** leídos de ``fila``
    (que se conservan sin tocar al editar la carátula).

    Es el helper que arma un registro completo ``HonorarioReport``
    para el alta de comprobantes
    (:func:`construir_payload_honorarios`).

    Nota: la edición simple de carátula NO usa este helper porque
    sólo envía los campos de carátula vía ``HonorariosUpdate``; sí
    lo usan el alta (:func:`construir_payload_honorarios`) y la
    reescritura por cambio a tipo Honorarios
    (:func:`construir_payload_reescritura`).

    Args:
        fila: Diccionario con los campos de la línea (p.ej. una fila
            de ``DataFrame.to_dict(orient="records")``).
        ejercicio: Ejercicio derivado del año de la fecha.
        mes: Mes en formato ``"%m/%Y"``.
        fecha: Fecha del comprobante (``datetime``).
        nro_comprobante: Comprobante completo ``"00000/aa"``.
        cta_cte: Cuenta corriente.
        tipo: Tipo de comprobante.

    Returns:
        Dict compatible con ``HonorarioReport`` (sin ``id``).
    """
    registro: dict[str, Any] = {
        "ejercicio": int(ejercicio),
        "mes": str(mes),
        "fecha": fecha,
        "nro_comprobante": str(nro_comprobante),
        "cta_cte": str(cta_cte),
        "tipo": str(tipo),
    }
    for campo in _CAMPOS_TEXTO_LINEA:
        registro[campo] = _texto_limpio(fila.get(campo))
    for campo in _CAMPOS_MONTO:
        valor = fila.get(campo, 0.0)
        registro[campo] = float(valor) if pd.notna(valor) else 0.0
    registro["updated_at"] = datetime.now()
    return registro


# --------------------------------------------------
def merge_informe_con_precarizados(
    df_informe: pd.DataFrame,
    df_precarizados: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Cruza el informe por destino con el padrón de precarizados para
    completar ``cuit`` / ``actividad`` / ``partida``.

    El cruce se hace por ``nombre_completo`` usando
    :func:`utils.transform_data.normalize_name_for_match` como clave
    normalizada (tolera comas, prefijos ``(JUBILADO)``/``[LP]``,
    mayúsculas distintas, etc.), igual que en la migración.

    Args:
        df_informe: Salida de :func:`process_informe_por_destino`.
        df_precarizados: Padrón de la colección ``factureros``
            (columnas ``nombre_completo``, ``cuit``, ``actividad``,
            ``partida``).

    Returns:
        Tupla ``(merged, sin_match, incompletos)``:

        - ``merged``: el informe enriquecido con las columnas del
          padrón (``_match_key`` eliminada).
        - ``sin_match``: nombres ordenados y sin duplicados de
          agentes **ausentes** en el padrón. Deben darse de alta
          manualmente.
        - ``incompletos``: nombres ordenados y sin duplicados de
          agentes **presentes** pero sin ``cuit``/``actividad``/
          ``partida``. Deben completarse en el padrón (el ``cuit``
          es obligatorio en ``HonorarioReport``).

        Ambas listas vacías => se puede continuar sin obstáculos.
    """
    if df_informe.empty:
        return pd.DataFrame(), [], []

    df_inf: pd.DataFrame = df_informe.copy()
    df_inf["_match_key"] = df_inf["nombre_completo"].apply(normalize_name_for_match)

    # Padrón vacío: ningún agente puede resolverse.
    if df_precarizados.empty:
        sin_match = sorted(
            set(df_informe["nombre_completo"].astype(str).str.strip()) - {""}
        )
        return df_inf.drop(columns=["_match_key"]), sin_match, []

    # Sólo las columnas útiles del padrón: evita la colisión de
    # ``nombre_completo`` al hacer merge sobre ``_match_key``.
    columnas_padron: list[str] = [
        columna
        for columna in ("nombre_completo", "cuit", "actividad", "partida")
        if columna in df_precarizados.columns
    ]
    df_pad: pd.DataFrame = df_precarizados[columnas_padron].copy()
    # Defensa: si la API no trajo alguna columna, se crea vacía para
    # que la clasificación la detecte como "incompleto".
    for columna in ("cuit", "actividad", "partida"):
        if columna not in df_pad.columns:
            df_pad[columna] = pd.NA

    df_pad["_match_key"] = df_pad["nombre_completo"].apply(normalize_name_for_match)
    # Un agente repetido en el padrón: nos quedamos con el primero.
    df_pad = df_pad.drop_duplicates(subset=["_match_key"], keep="first")

    lookup: pd.DataFrame = df_pad[["_match_key", "cuit", "actividad", "partida"]]
    merged: pd.DataFrame = df_inf.merge(lookup, on="_match_key", how="left")

    # ── Clasificación de agentes ──
    # "Existe" se determina por actividad/partida (obligatorios en
    # FactureroReport): si traen nulo, el merge no encontró fila.
    existe = merged["actividad"].notna() & merged["partida"].notna()

    def _falta(columna: str) -> pd.Series:
        serie = merged[columna]
        return serie.isna() | serie.astype(str).str.strip().isin(
            ["", "nan", "None", "<NA>"]
        )

    incompleto = _falta("cuit") | _falta("actividad") | _falta("partida")

    sin_match = sorted(
        set(merged.loc[~existe, "nombre_completo"].astype(str)) - {"", "nan"}
    )
    incompletos = sorted(
        set(merged.loc[existe & incompleto, "nombre_completo"].astype(str))
        - {"", "nan"}
    )

    merged = merged.drop(columns=["_match_key"])
    return merged, sin_match, incompletos


# --------------------------------------------------
def process_informe_por_destino(
    dataframe: pd.DataFrame | str | Path | BytesIO,
) -> pd.DataFrame:
    """
    Lee y convierte el reporte "Resumen de Pagos por Destino" en un
    ``DataFrame`` con las columnas del modelo ``InformePorDestino``.

    Diseñada para ser usada como ``uploader_func`` de
    ``views/aux_tables.report_template()``, que invoca
    ``read_csv_file(uploaded_file)`` y luego pasa el ``DataFrame``
    crudo (columnas ``"0".."99"``) a esta función.

    Args:
        dataframe: Una de las siguientes entradas:

            - ``pd.DataFrame``: DataFrame crudo leído con
              ``read_csv_file`` (caso principal, desde
              ``report_template()`` con ``uploaded_file``).
            - ``str | Path``: Ruta a un CSV, que se lee con
              ``read_csv_file``.
            - ``BytesIO``: buffer en memoria (p.ej. ``BytesIO(f.getvalue())``
              con el archivo de ``st.file_uploader``, cuyo
              ``UploadedFile`` hereda de ``BytesIO``).

    Returns:
        DataFrame con las columnas de ``InformePorDestino`` en el
        orden exacto del modelo (``nombre_completo: str`` y montos
        ``float``). Vacío si la entrada no es un reporte válido
        (título incorrecto, columnas faltantes o sin registros).

    Raises:
        Ninguna. Los casos inválidos devuelven ``pd.DataFrame()``
        vacío para que el caller (``report_template()``) muestre el
        mensaje de "CSV Vacío o Incorrecto".
    """
    # ── 1. Resolver la entrada a un DataFrame crudo ──────────
    if isinstance(dataframe, (str, Path, BytesIO)):
        # Ruta a un CSV **o** buffer en memoria (``st.file_uploader``
        # devuelve un ``UploadedFile`` que hereda de ``BytesIO``).
        # Sin esta rama, un ``BytesIO`` caería en el ``isinstance``
        # de más abajo y se devolvería un DataFrame vacío.
        dataframe = read_csv_file(dataframe)

    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
        return pd.DataFrame()

    if dataframe.shape[1] < 2:
        # No hay ni siquiera la columna del título (posición 1).
        return pd.DataFrame()

    df: pd.DataFrame = dataframe.copy()

    # ── 2. Validar que sea el reporte esperado ───────────────
    titulo_reporte: str = str(df.iloc[0, 1]).strip()
    if not titulo_reporte.startswith(_TITULO_ESPERADO):
        print(
            f"⚠️ Título de reporte inesperado: '{titulo_reporte}'. "
            f"Se esperaba '{_TITULO_ESPERADO}'."
        )
        return pd.DataFrame()

    # ── 3. Validar que existan las columnas requeridas ───────
    columnas_requeridas: list[str] = [str(pos) for pos in _MAPEO_COLUMNAS.values()]
    faltantes: list[str] = [
        columna for columna in columnas_requeridas if columna not in df.columns
    ]
    if faltantes:
        print(
            f"⚠️ Faltan columnas {faltantes} en el DataFrame crudo "
            f"(se esperan posiciones numéricas '0'..'99' provenientes "
            f"de read_csv_file)."
        )
        return pd.DataFrame()

    # ── 4. Extraer y convertir los campos del modelo ─────────
    resultado: pd.DataFrame = pd.DataFrame()

    # nombre_completo: se limpia y normaliza a str.
    posicion_nombre: int = _MAPEO_COLUMNAS["nombre_completo"]
    resultado["nombre_completo"] = df[str(posicion_nombre)].astype(str).str.strip()

    # Montos: de string "1,770,025.00" a float.
    for campo, posicion in _MAPEO_COLUMNAS.items():
        if campo == "nombre_completo":
            continue
        resultado[campo] = df[str(posicion)].apply(_parse_moneda)

    # Campos sin contraparte en el reporte -> 0.0 (modelo no-Optional).
    for campo in _CAMPOS_SIN_DATO:
        resultado[campo] = 0.0

    # ── 5. Filtrar filas sin proveedor ───────────────────────
    resultado = resultado.loc[
        (resultado["nombre_completo"] != "")
        & (resultado["nombre_completo"] != "nan")
        & (resultado["nombre_completo"] != "None")
    ].copy()

    if resultado.empty:
        print("⚠️ No se encontraron registros válidos en el reporte.")
        return pd.DataFrame()

    # ── 6. Reordenar según el orden exacto del modelo ────────
    orden_modelo: list[str] = list(InformePorDestino.model_fields.keys())
    resultado = resultado.loc[:, orden_modelo].reset_index(drop=True)

    # ── 7. Asegurar tipos compatibles con el modelo ──────────
    resultado["nombre_completo"] = resultado["nombre_completo"].astype(str)
    for campo in orden_modelo:
        if campo != "nombre_completo":
            resultado[campo] = resultado[campo].astype(float)

    return resultado


# --------------------------------------------------
def construir_payload_honorarios(
    df_merged: pd.DataFrame,
    *,
    ejercicio: int,
    mes: str,
    fecha: datetime,
    nro_comprobante: str,
    cta_cte: str,
    tipo: str,
) -> list[dict[str, Any]]:
    """
    Construye la lista de registros lista para
    ``POST /slave/honorarios/add_many/{nro_comprobante}``.

    Cada registro se valida contra :class:`HonorarioReport` antes de
    retornarse, de modo que un esquema incompleto se detecta en el
    cliente y no como un error 4xx de la API.

    Args:
        df_merged: Salida de :func:`merge_informe_con_precarizados`
            ya sin filas sin match/incompletas.
        ejercicio: Ejercicio derivado del año de la fecha.
        mes: Mes en formato ``"%m/%Y"``.
        fecha: Fecha del comprobante (se envía como ``datetime``).
        nro_comprobante: Comprobante completo ``"00000/yy"``.
        cta_cte: Cuenta corriente (e.g. ``"130832-05"``).
        tipo: Tipo de comprobante.

    Returns:
        Lista de dicts compatibles con ``HonorarioReport``.

    Raises:
        pydantic.ValidationError: Si alguna fila no cumple el
            esquema. El llamador debe informarlo y NO enviar nada.
    """
    registros: list[dict[str, Any]] = []
    for fila in df_merged.to_dict(orient="records"):
        registro = _montar_registro(
            fila,
            ejercicio=ejercicio,
            mes=mes,
            fecha=fecha,
            nro_comprobante=nro_comprobante,
            cta_cte=cta_cte,
            tipo=tipo,
        )
        # Validación estricta contra el esquema del modelo.
        HonorarioReport.model_validate(registro)
        registros.append(registro)

    return registros


# --------------------------------------------------
def componer_nro_comprobante(base: str, anio: int) -> str:
    """
    Compone el comprobante completo ``"00000/aa"``.

    ``("123", 2026)`` -> ``"00123/26"``. La parte numérica se rellena
    con ceros a la izquierda hasta 5 dígitos y el sufijo son los dos
    últimos dígitos del año.

    Args:
        base: Parte numérica (puede traer ceros a la izquierda).
        anio: Año del comprobante (de donde salen los dos últimos
            dígitos).

    Returns:
        ``"00000/aa"`` o ``""`` si ``base`` no es numérica.
    """
    texto: str = (base or "").strip()
    if not texto.isdigit():
        return ""
    return f"{texto.zfill(5)}/{str(int(anio))[-2:]}"


# --------------------------------------------------
def separar_nro_comprobante(nro: object) -> str:
    """
    Extrae la parte numérica de un comprobante ``"00000/aa"``.

    ``"00123/26"`` -> ``"123"`` (sin ceros a la izquierda), para
    pre-cargar el ``text_input`` del modal de edición.

    Args:
        nro: Comprobante crudo (puede ser ``None``/``NaN``).

    Returns:
        La parte numérica como ``str``, o ``""`` si el formato no es
        reconocido (para que el usuario deba tipearlo).
    """
    if nro is None or (isinstance(nro, float) and pd.isna(nro)):
        return ""
    texto: str = str(nro).strip()
    if not texto:
        return ""
    base: str = texto.split("/")[0].strip()
    return str(int(base)) if base.isdigit() else ""


# --------------------------------------------------
def construir_payload_actualizacion_caratula(
    *,
    nro_comprobante: str,
    ejercicio: int,
    mes: str,
    fecha: datetime,
    tipo: str,
    cta_cte: str,
) -> dict[str, Any]:
    """
    Construye el payload único para ``PUT .../update_many/{nro_viejo}``.

    Actualiza en bloque la **carátula** de todas las líneas de un
    comprobante. Sólo se envían campos de carátula: los de línea
    (``cuit``, ``nombre_completo``, ``actividad``, ``partida`` e
    importes) **se conservan tal cual** porque el servidor no los toca.

    Notas de diseño:

    - **``nro_comprobante`` es el NUEVO número**: el comprobante se
      identifica por el nro de la *path* (el número original) y éste
      es el valor de reemplazo. Es ``None`` cuando no cambia, y el
      servidor entonces conserva el actual.
    - **No se envía ``partida``**: es un campo de **línea** y varía
      entre líneas del mismo comprobante; enviarlo en bloque
      sobrescribiría la partida de todas las líneas con un único
      valor. Se omite para que el servidor lo deje intacto.
    - **No se envía ``updated_at``**: lo asigna el servidor.

    Args:
        nro_comprobante: Nuevo número ``"00000/aa"`` (puede coincidir
            con el actual si el usuario no lo cambió).
        ejercicio: Ejercicio derivado del año de la fecha.
        mes: Mes en formato ``"%m/%Y"``.
        fecha: Fecha del comprobante.
        tipo: Tipo de comprobante (obligatorio en ``HonorariosUpdate``).
        cta_cte: Cuenta corriente.

    Returns:
        Dict listo para enviar como cuerpo del ``PUT``.

    Raises:
        pydantic.ValidationError: Si el payload no cumple
            ``HonorariosUpdate`` (el llamador NO debe enviar nada).
    """
    payload: dict[str, Any] = {
        "nro_comprobante": str(nro_comprobante),
        "ejercicio": int(ejercicio),
        "mes": str(mes),
        "fecha": fecha,
        "tipo": str(tipo),
        "cta_cte": str(cta_cte),
    }
    # Validación estricta contra el esquema del Back antes de enviar.
    HonorariosUpdate.model_validate(payload)
    return payload


# --------------------------------------------------
def construir_payload_reescritura(
    df_lineas: pd.DataFrame,
    df_precarizados: pd.DataFrame,
    *,
    ejercicio: int,
    mes: str,
    fecha: datetime,
    nro_comprobante: str,
    cta_cte: str,
    tipo: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Reconstruye las líneas de un comprobante para reescribirlo vía
    ``DELETE .../delete_many`` + ``POST .../add_many``.

    Se usa al editar un comprobante pasándolo de un tipo distinto de
    ``"Honorarios"`` a ``"Honorarios"``: el Back fuerza la partida
    ``"399"`` a todo tipo no-Honorarios y, al volver a Honorarios, no
    puede saber qué partida corresponde a cada agente. Aquí la
    ``partida`` de cada línea se resuelve contra el padrón de
    Precarizados (``slave_precarizados``) cruzando ``nombre_completo``
    con :func:`utils.transform_data.normalize_name_for_match`, el
    mismo criterio que :func:`merge_informe_con_precarizados`.

    Args:
        df_lineas: Líneas actuales del comprobante (``df_docs``), con
            los campos de línea (``cuit``, ``nombre_completo``,
            ``actividad``, ``partida`` e importes).
        df_precarizados: Padrón de la colección ``factureros``.
        ejercicio: Ejercicio de la carátula (puede ser el nuevo).
        mes: Mes en formato ``"%m/%Y"``.
        fecha: Fecha de la carátula.
        nro_comprobante: Comprobante completo ``"00000/aa"`` (el
            nuevo, si se renumera).
        cta_cte: Cuenta corriente.
        tipo: Tipo de comprobante (``"Honorarios"``).

    Returns:
        Tupla ``(registros, sin_partida)``:

        - ``registros``: lista de dicts compatibles con
          ``HonorarioReport`` con la ``partida`` corregida, **sólo**
          si TODAS las líneas resolvieron partida; vacía en caso
          contrario.
        - ``sin_partida``: agentes (nombre) cuya partida no pudo
          resolverse porque no figuran en el padrón o figuran sin
          partida. Vacía si todo matcheó.

        Si ``sin_partida`` no está vacía, el llamador **NO** debe
        tocar la API.

    Raises:
        pydantic.ValidationError: Si alguna fila no cumple el esquema
            ``HonorarioReport``. El llamador debe informarlo y NO
            enviar nada.
    """
    registros: list[dict[str, Any]] = []
    if df_lineas.empty:
        return registros, []

    # Lookup ``_match_key -> partida`` del padrón (primer valor no
    # vacío por clave, igual que merge_informe_con_precarizados).
    lookup: dict[str, str] = {}
    if not df_precarizados.empty and "nombre_completo" in df_precarizados.columns:
        df_pad: pd.DataFrame = df_precarizados.copy()
        if "partida" not in df_pad.columns:
            df_pad["partida"] = pd.NA
        df_pad = df_pad[["nombre_completo", "partida"]].copy()
        df_pad["_match_key"] = df_pad["nombre_completo"].apply(
            normalize_name_for_match
        )
        for clave, partida in zip(df_pad["_match_key"], df_pad["partida"]):
            partida_limpia: str = _texto_limpio(partida)
            if clave and partida_limpia and clave not in lookup:
                lookup[clave] = partida_limpia

    sin_partida: set[str] = set()
    for fila in df_lineas.to_dict(orient="records"):
        nombre_agente: str = _texto_limpio(fila.get("nombre_completo"))
        partida_correcta: str = lookup.get(
            normalize_name_for_match(nombre_agente), ""
        )
        if not partida_correcta:
            sin_partida.add(nombre_agente or "(sin nombre)")
            continue
        fila_corregida: dict[str, Any] = {**fila, "partida": partida_correcta}
        registro = _montar_registro(
            fila_corregida,
            ejercicio=ejercicio,
            mes=mes,
            fecha=fecha,
            nro_comprobante=nro_comprobante,
            cta_cte=cta_cte,
            tipo=tipo,
        )
        # Validación estricta contra el esquema del modelo.
        HonorarioReport.model_validate(registro)
        registros.append(registro)

    if sin_partida:
        # Algún agente sin partida: no hay payload utilizable.
        return [], sorted(sin_partida)
    return registros, []


