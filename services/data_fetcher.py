"""Servicio de fetching de datos para la UI.

Aplica ``@st.cache_data`` directamente sobre las funciones de servicio
(tal como autoriza ``AGENTS.md`` §1: *"Se autoriza el uso de
``@st.cache_data`` / ``@st.cache_resource`` para optimizar peticiones"*),
de modo que la capa de ``views/`` no necesita wrappers intermedios.

Mantiene un fallback a caché Parquet local cuando la API no está
disponible (modo degradado); el padrón de precarizados y
la colección de honorarios se sirven sólo desde la API con
``@st.cache_data`` (sin Parquet en disco). El módulo **no** contiene
widgets interactivos de entrada de datos (``st.button``,
``st.text_input``, ``st.file_uploader``), los cuales pertenecen a la
capa de UI (``AGENTS.md`` §1).
"""

__all__ = [
    "get_obras_recuperadas",
    "get_referencias_factureros",
    "get_referencias_honorarios",
    "get_ejercicios_list",
    "get_honorarios",
    "sincronizar_caches",
]

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

import utils.exceptions as ex
from services.api import fetch_data, fetch_dataframe
from utils.endpoints import Endpoints
from utils.handling_path import get_cache_path

logger = logging.getLogger(__name__)

# Archivos Parquet del caché en disco de las listas de referencia
# (lectura rápida cuando ``update_trigger == 0`` y fallback degradado
# si la API falla). Precarizados y honorarios NO persisten en Parquet:
# se sirven sólo desde la API con ``@st.cache_data``.
_PARQUET_ACTIVIDADES: str = "factureros_actividades_cache.parquet"
_PARQUET_PARTIDAS: str = "factureros_partidas_cache.parquet"
_PARQUET_CTAS_CTES: str = "honorarios_ctas_ctes_cache.parquet"
_PARQUET_TIPOS_COMPROBANTES: str = "honorarios_tipos_comprobantes_cache.parquet"

# Columna única de los DataFrames de referencia persistidos en Parquet.
_COLUMNA_REFERENCIA: str = "valor"


# --------------------------------------------------
def _valores_unicos(df: pd.DataFrame, columna: str) -> list[str]:
    """
    Extrae los valores únicos y ordenados de una columna del DataFrame.

    Descarta nulos (``NaN``/``NA``/``NaT``), normaliza a ``str`` con
    ``strip()`` y elimina cadenas vacías.

    Args:
        df: DataFrame fuente.
        columna: Nombre de la columna a extraer.

    Returns:
        Lista ordenada de valores únicos; vacía si la columna no existe
        o no tiene valores utilizables.
    """
    if columna not in df.columns:
        return []
    serie = df[columna].dropna()
    valores: set[str] = set()
    for valor in serie:
        # Un float entero (p.ej. 354.0 al tener la columna nulos) pierde
        # la parte decimal para coincidir con el valor canónico "354".
        if isinstance(valor, float) and valor.is_integer():
            valores.add(str(int(valor)))
        else:
            valores.add(str(valor).strip())
    return sorted(valores - {""})


# --------------------------------------------------
def _normalizar_referencia(datos: Any) -> list[str]:
    """
    Normaliza la respuesta JSON de un endpoint de referencia a una
    lista ordenada de strings únicos.

    Se espera una lista plana de valores (p.ej. ``["354", "AC"]``), la
    forma que devuelven ``/slave/factureros/partidas``,
    ``/slave/factureros/actividades``, ``/slave/honorarios/ctasCtes``
    y ``/slave/honorarios/tiposComprobantes``. Un float entero pierde
    la parte decimal (``354.0`` -> ``"354"``) y los nulos se descartan.

    Args:
        datos: Cuerpo JSON devuelto por la API.

    Returns:
        Lista ordenada de valores únicos; vacía si no hay valores.

    Raises:
        APIResponseError: Si la respuesta no es una lista (la API no
            cumple el contrato esperado).
    """
    if not isinstance(datos, list):
        raise ex.APIResponseError(
            "Respuesta inesperada del endpoint de referencia: se esperaba "
            f"una lista y se recibió {type(datos).__name__}."
        )
    valores: set[str] = set()
    for item in datos:
        if item is None:
            continue
        if isinstance(item, float) and item.is_integer():
            valores.add(str(int(item)))
        else:
            valores.add(str(item).strip())
    return sorted(valores - {""})


# --------------------------------------------------
def _leer_referencia_parquet(ruta: str) -> list[str]:
    """
    Lee una lista de referencia desde su Parquet de caché en disco.

    Args:
        ruta: Ruta al archivo Parquet.

    Returns:
        Lista ordenada de valores únicos; vacía si el archivo está
        vacío o no tiene la columna de referencia.

    Raises:
        OSError: Si el archivo no se puede leer.
        ValueError: Si el archivo no es un Parquet válido.
    """
    df: pd.DataFrame = pd.read_parquet(ruta)
    return _valores_unicos(df, _COLUMNA_REFERENCIA)


# --------------------------------------------------
def _fetch_referencia(
    endpoint: str,
    parquet_name: str,
    update_trigger: int = 0,
) -> list[str]:
    """
    Obtiene una lista de referencia desde la API con caché Parquet.

    Flujo de prioridad (el mismo que tenía :func:`get_precarizados`
    antes de perder su Parquet en disco):

        1. Si ``update_trigger == 0`` y existe un caché vigente
           (< 24h), se retorna desde disco sin tocar la API.
        2. Si no, se consulta la API.
        3. Si la API falla y existe un caché (cualquier antigüedad), se
           usa como fallback degradado.
        4. Si la API falla y no hay caché, se re-lanza la excepción.

    Args:
        endpoint: Ruta relativa del endpoint de referencia.
        parquet_name: Nombre del archivo Parquet de caché (se resuelve
            contra ``utils.handling_path.get_cache_path``).
        update_trigger: Incrementar para forzar la consulta a la API.

    Returns:
        Lista ordenada de valores únicos.

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error o una forma
            inesperada y no hay caché disponible.
    """
    cache_path: str = os.path.join(get_cache_path(), parquet_name)

    # 1. Lectura rápida desde el caché vigente
    if update_trigger == 0 and os.path.exists(cache_path):
        mtime: datetime = datetime.fromtimestamp(os.path.getmtime(cache_path))
        if datetime.now() - mtime < timedelta(hours=24):
            try:
                return _leer_referencia_parquet(cache_path)
            except (OSError, ValueError) as read_exc:
                logger.warning(
                    "No se pudo leer el caché local (%s): %s",
                    type(read_exc).__name__,
                    read_exc,
                )

    # 2. Consultar la API
    try:
        datos: Any = fetch_data(endpoint)
        valores: list[str] = _normalizar_referencia(datos)
    except (ex.APIConnectionError, ex.APIResponseError) as api_exc:
        # 3. Fallback best-effort: usar caché viejo si existe
        if os.path.exists(cache_path):
            try:
                logger.warning("API no disponible, usando caché local: %s", api_exc)
                return _leer_referencia_parquet(cache_path)
            except (OSError, ValueError) as read_exc:
                logger.error(
                    "No se pudo leer el caché local de fallback: %s",
                    read_exc,
                )
        # 4. Sin fallback: propagar la excepción original
        raise

    # API exitosa: persistir el snapshot. Una lista vacía NO pisa el
    # Parquet para no perder el fallback vigente.
    if valores:
        try:
            pd.DataFrame({_COLUMNA_REFERENCIA: valores}).to_parquet(cache_path)
        except (OSError, ValueError) as write_exc:
            # Best-effort: los datos de la API ya están resueltos; el
            # caché en disco se loguea pero no corta la respuesta.
            logger.warning(
                "No se pudo escribir el caché Parquet (%s): %s",
                type(write_exc).__name__,
                write_exc,
            )

    return valores


# --------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_referencias_factureros(update_trigger: int = 0) -> tuple[list[str], list[str]]:
    """
    Retorna las listas únicas y ordenadas de ``actividad`` y ``partida``
    del padrón de factureros, para poblar los ``selectbox`` de los modales.

    Consulta los endpoints ligeros dedicados
    (``/slave/factureros/actividades`` y ``/slave/factureros/partidas``)
    vía :func:`_fetch_referencia`, en vez de descargar el padrón
    completo. Cada lista tiene su propio Parquet (lectura rápida < 24h
    + fallback degradado) y el ``@st.cache_data`` agrega encima una
    capa de memoria por re-render.

    Args:
        update_trigger: Incrementar para invalidar el caché. Se usa
            ``st.session_state[session_state_update_key]``.

    Returns:
        Tupla ``(actividades, partidas)``; ambas vacías si el padrón
        está vacío.

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error y no hay caché.
    """
    actividades: list[str] = _fetch_referencia(
        Endpoints.SLAVE_FACTUREROS_ACTIVIDADES.value,
        _PARQUET_ACTIVIDADES,
        update_trigger,
    )
    partidas: list[str] = _fetch_referencia(
        Endpoints.SLAVE_FACTUREROS_PARTIDAS.value,
        _PARQUET_PARTIDAS,
        update_trigger,
    )
    return actividades, partidas


# --------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_referencias_honorarios(update_trigger: int = 0) -> tuple[list[str], list[str]]:
    """
    Retorna las listas únicas y ordenadas de tipo de comprobante y de
    cuentas corrientes de honorarios, para poblar los ``selectbox`` de
    ``views.modals.modal_honorarios``.

    Es el equivalente a :func:`get_referencias_factureros` para la
    colección de honorarios: usa los endpoints ligeros dedicados
    (``/slave/honorarios/tiposComprobantes`` y
    ``/slave/honorarios/ctasCtes``) vía :func:`_fetch_referencia`, en
    vez de descargar la colección completa. Cada lista tiene su propio
    Parquet (lectura rápida < 24h + fallback degradado).

    Args:
        update_trigger: Incrementar para invalidar el caché. Se usa
            ``st.session_state["honorarios_dataframes_iteration"]``.

    Returns:
        Tupla ``(tipos, ctas_ctes)``; ambas vacías si la
        colección está vacía (el ``selectbox`` del modal queda en
        modo escritura libre).

    Raises:
        APIConnectionError: Si la API falla y no hay caché disponible.
        APIResponseError: Si la API retorna un error y no hay caché.
    """
    tipos: list[str] = _fetch_referencia(
        Endpoints.SLAVE_HONORARIOS_TIPOS_COMPROBANTES.value,
        _PARQUET_TIPOS_COMPROBANTES,
        update_trigger,
    )
    ctas_ctes: list[str] = _fetch_referencia(
        Endpoints.SLAVE_HONORARIOS_CTAS_CTES.value,
        _PARQUET_CTAS_CTES,
        update_trigger,
    )
    return tipos, ctas_ctes


# --------------------------------------------------
@st.cache_data(ttl=3600)
def get_obras_recuperadas(
    filtro_avanzado: str = "",
    update_trigger: int = 0,
    selections: list[tuple[str, list[Any]]] | None = None,
) -> pd.DataFrame:
    """
    Obtiene el padrón de obras recuperadas desde la API.

    No persiste en Parquet (igual que :func:`get_honorarios`): el
    ``@st.cache_data`` (TTL de 1 hora) es la única capa de caché, que
    evita llamadas repetidas a la API dentro del mismo TTL. Las
    excepciones no se cachean: se re-lanzan en cada invocación para que
    la UI pueda notificarlas.

    Args:
        filtro_avanzado: Filtro dinámico (e.g. ``ejercicio=2024``).
        update_trigger: Incrementar para forzar la actualización de caché.
        selections: Tuplas ``(query_param, valores)`` de los multiselects
            server-side (``filters_config`` de ``report_header``). Cada
            valor se serializa como string separado por comas
            (e.g. ``ejercicio=2026,2025``). Lista vacía o ``None`` no
            agrega parámetros (sin filtro).

    Returns:
        DataFrame con las obras recuperadas.

    Raises:
        APIConnectionError: Si la API falla.
        APIResponseError: Si la API retorna un error.
    """
    params_peticion: dict[str, Any] = {
        "limit": 0,
        "queryFilter": filtro_avanzado,
    }
    if selections:
        for nombre_param, valores in selections:
            if valores:
                params_peticion[nombre_param] = ",".join(map(str, valores))
    df: pd.DataFrame = fetch_dataframe(
        Endpoints.OBRAS_RECUPERADAS.value, params=params_peticion
    )
    if not df.empty:
        df = df.sort_values(
            ["ejercicio", "cod_barrio", "estructura"], ascending=[False, True, True]
        )

    return df


@st.cache_data
# --------------------------------------------------
def get_ejercicios_list() -> list[int]:
    return list(range(2010, date.today().year + 1))


# --------------------------------------------------
@st.cache_data(ttl=3600)
def get_honorarios(
    selections: list, filtro_avanzado: str = "", update_trigger: int = 0
) -> pd.DataFrame:

    params_peticion = {
        "limit": 0,
        "queryFilter": filtro_avanzado,
    }
    for nombre_param, valores in selections:
        if valores:
            params_peticion[nombre_param] = ",".join(map(str, valores))

    df: pd.DataFrame = fetch_dataframe(
        Endpoints.SLAVE_HONORARIOS.value, params=params_peticion
    )
    if not df.empty:
        df = df.sort_values(
            ["ejercicio", "fecha", "nro_comprobante"], ascending=[False, False, True]
        )

    return df


# --------------------------------------------------
def _mtime_parquet(ruta: str) -> float | None:
    """
    Retorna el ``mtime`` del archivo o ``None`` si no existe.

    Se usa para detectar si una sincronización re-escribió el Parquet
    (API disponible) o si se sirvió el fallback sin actualizar.

    Args:
        ruta: Ruta absoluta al archivo Parquet.

    Returns:
        Segundos desde la época o ``None`` si el archivo no existe.
    """
    try:
        return os.path.getmtime(ruta)
    except OSError:
        return None


# --------------------------------------------------
def sincronizar_caches(
    trigger_precarizados: int = 0,
) -> tuple[dict[str, int], dict[str, str]]:
    """
    Sincronización ligera del caché: memoria + API + Parquet de
    referencias.

    Pasos:

    1. Limpia el caché en memoria (``st.cache_data`` y
       ``st.cache_resource``): invalida TODAS las funciones con caché,
       incluidas las de honorarios.
    2. Re-consulta el padrón de precarizados a la API, lo que repuebla
       la memoria (ya sin Parquet en disco, igual que honorarios).
    3. Re-consulta las cuatro listas de referencia (actividades,
       partidas, tipos de comprobante y ctas. ctes.) y **re-escribe**
       sus cuatro Parquet.

    **Honorarios NO se descarga aquí**: cada vista sólo necesita el
    ejercicio que está viendo (lo trae ella misma con el trigger ya
    invalidado por el caller). Así el sync no baja decenas de miles de
    documentos que nadie va a mirar.

    Si la API falla para un recurso, su Parquet previo **se conserva a
    propósito** como fallback degradado y el recurso queda en
    ``errores`` informando que no se actualizó: nada se silencia.

    Args:
        trigger_precarizados: Valor de
            ``st.session_state[report_data_version_key("precarizados")]``
            ya incrementado. El caller también debe incrementar
            ``honorarios_dataframes_iteration`` para invalidar las
            vistas de honorarios.

    Returns:
        Tupla ``(actualizados, errores)``:

        - ``actualizados``: recurso -> cantidad de registros/valores
          traídos desde la API.
        - ``errores``: recurso -> mensaje del fallo. Vacío si todo
          resultó OK.
    """
    # 1) Memoria: purga total (el fetch siguiente la repuebla).
    st.cache_data.clear()
    st.cache_resource.clear()

    actualizados: dict[str, int] = {}
    errores: dict[str, str] = {}
    # Con trigger 0 las referencias leerían su Parquet vigente sin
    # tocar la API: se fuerza al menos a 1 para ir siempre a la red.
    trigger_referencias: int = trigger_precarizados or 1

    # ── Precarizados: sólo memoria + API (sin Parquet) ──
    try:
        df_precarizados: pd.DataFrame = get_obras_recuperadas(
            update_trigger=trigger_precarizados
        )
    except ex.AppBaseException as api_exc:
        errores["Precarizados"] = str(api_exc)
    except Exception as exc:  # fallo inesperado, se informa igual
        errores["Precarizados"] = f"{type(exc).__name__}: {exc}"
    else:
        actualizados["Precarizados"] = len(df_precarizados)

    # ── Listas de referencia: reescribe sus cuatro Parquet ──
    referencias: dict[str, tuple[str, str]] = {
        "Factureros · Actividades": (
            Endpoints.SLAVE_FACTUREROS_ACTIVIDADES.value,
            _PARQUET_ACTIVIDADES,
        ),
        "Factureros · Partidas": (
            Endpoints.SLAVE_FACTUREROS_PARTIDAS.value,
            _PARQUET_PARTIDAS,
        ),
        "Honorarios · Tipos de Comprobante": (
            Endpoints.SLAVE_HONORARIOS_TIPOS_COMPROBANTES.value,
            _PARQUET_TIPOS_COMPROBANTES,
        ),
        "Honorarios · Ctas. Ctes.": (
            Endpoints.SLAVE_HONORARIOS_CTAS_CTES.value,
            _PARQUET_CTAS_CTES,
        ),
    }
    for recurso, (endpoint, parquet_name) in referencias.items():
        ruta: str = os.path.join(get_cache_path(), parquet_name)
        mtime_previo: float | None = _mtime_parquet(ruta)
        try:
            valores: list[str] = _fetch_referencia(
                endpoint, parquet_name, update_trigger=trigger_referencias
            )
        except ex.AppBaseException as api_exc:
            errores[recurso] = str(api_exc)
        except Exception as exc:  # fallo inesperado, se informa igual
            errores[recurso] = f"{type(exc).__name__}: {exc}"
        else:
            sin_cambios: bool = (
                bool(valores)
                and mtime_previo is not None
                and _mtime_parquet(ruta) == mtime_previo
            )
            if sin_cambios:
                # El Parquet no se re-escribió: la API falló y se sirvió
                # el fallback, o devolvió datos vacíos.
                errores[recurso] = (
                    "el caché Parquet local no fue re-escrito (API vacía "
                    "o no disponible); los datos NO se actualizaron."
                )
            else:
                actualizados[recurso] = len(valores)

    return actualizados, errores
