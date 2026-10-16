"""Modales (``st.dialog``) reutilizables de la capa de vistas."""

import re
import time
from datetime import date, datetime
from io import BytesIO
from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from components.buttons import button_cancel, button_submit
from services.api import delete_request, post_request, put_request
from services.data_fetcher import (
    get_precarizados,
    get_referencias_factureros,
    get_referencias_honorarios,
)
from services.process_df import (
    componer_nro_comprobante,
    construir_payload_actualizacion_caratula,
    construir_payload_honorarios,
    construir_payload_reescritura,
    merge_informe_con_precarizados,
    process_informe_por_destino,
    separar_nro_comprobante,
)
from utils.context import sync_session_token
from utils.endpoints import Endpoints
from utils.exceptions import AppBaseException
from views.aux_tables import report_data_version_key

# Tipo de comprobante que exige la partida real del padrón de
# Precarizados. El Back fuerza la partida "399" a todo tipo distinto
# de este al agregar o editar (ver modal_honorarios).
TIPO_HONORARIOS: str = "Honorarios"


# --- MODAL: ELIMINAR COMPROBANTE GENERICO ---
@st.dialog("Confirmar Eliminación PERMANENTE", width="small")
def modal_delete_registro_gral(
    endpoint: str,
    desc_registro: str,
    session_state_update_key: str = None,
    key_prefix: str = "",
):
    # CRÍTICO: Streamlit ejecuta ``@st.dialog`` en un contexto de script
    # separado donde los ``ContextVar`` (usados por ``utils.context`` para
    # propagar el token) NO se heredan automáticamente del script principal.
    # Sin esta sincronización, ``delete_request`` recibiría ``None`` y
    # lanzaría ``APIConnectionError("No hay token de sesión...")``.
    token = sync_session_token(st.session_state.get("token"))

    st.warning(
        f"⚠️ ¿Estás seguro de que deseás eliminar el registro **{desc_registro}**?"
    )
    st.write(
        "Esta acción es permanente y también eliminará todas las retenciones asociadas."
    )

    st.markdown("---")
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel("Cancelar", key=f"{key_prefix}_btn_cancel", type="secondary"):
            st.rerun()

        if button_submit("Si, Eliminar", key=f"{key_prefix}_btn_eliminar"):
            with st.spinner("Eliminando registro..."):
                try:
                    # Pasamos el token explícitamente como defensa adicional
                    # (no dependemos solo del ContextVar, que es frágil).
                    res = delete_request(endpoint, token=token)

                    if res:
                        st.success("Registro eliminado correctamente.")
                        if session_state_update_key:
                            if session_state_update_key not in st.session_state:
                                st.session_state[session_state_update_key] = 0
                            else:
                                st.session_state[session_state_update_key] += 1

                    else:
                        st.error(
                            "Error al eliminar el registro. Por favor, intenta nuevamente."
                        )

                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"Error al eliminar: {e}")


# --------------------------------------------------
def _a_texto(valor: Any) -> str:
    """
    Convierte escalares de ``pandas``/``numpy`` a ``str`` saneado.

    Normaliza ``None``, ``numpy.nan``, ``pd.NA`` y ``pd.NaT`` a cadena
    vacía. Necesario porque ``DataFrame.to_dict()``
    (usado por la grilla para pasar ``datos_carga``) puede traer ``NaN``
    en campos opcionales como ``cuit``, y ``NaN`` no es JSON válido.

    Args:
        valor: Cualquier escalar proveniente de una fila del DataFrame.

    Returns:
        Cadena limpia (vacía si el valor era nulo).
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if pd.isna(valor):  # numpy.nan, pd.NA, pd.NaT
        return ""
    if isinstance(valor, float) and valor.is_integer():
        # Float entero (p.ej. 354.0): pierde la parte decimal para
        # coincidir con el valor canónico "354" de las referencias.
        return str(int(valor))
    return str(valor)


# --------------------------------------------------
def _a_fecha(valor: Any) -> date | None:
    """
    Convierte un escalar de fecha a ``datetime.date``.

    Acepta ``datetime``, ``date``, ``pd.Timestamp``/``NaT`` y strings
    en los formatos habituales de la API (``"2026-09-23"``,
    ``"2026-09-23T00:00:00"``, ``"23/09/2026"``).

    Args:
        valor: Cualquier escalar proveniente de una fila.

    Returns:
        ``date`` o ``None`` si el valor es nulo o no reconocido (para
        que el widget caiga en su default).
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if pd.isna(valor):
        return None
    texto: str = str(valor).strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


# --- MODAL: AGREGAR / EDITAR FACTURERO (AGENTE) ---
@st.dialog("Agregar / Editar FACTURERO", width="medium")
def modal_precarizado(
    key_prefix: str,
    datos_carga: dict[str, Any] | None = None,
    es_edicion: bool = False,
    es_autocarga: bool = False,
    session_state_update_key: str = report_data_version_key("precarizados"),
) -> None:
    """
    Modal para dar de alta o editar un agente de la colección
    ``factureros`` (padrón de Precarizados).

    Args:
        key_prefix: Prefijo único para las keys de los widgets. Debe
            incluir timestamp con microsegundos para evitar que dos
            aperturas seguidas compartan el estado de los inputs.
        datos_carga: Fila a editar (``df.iloc[i].to_dict()``); ``None``
            en modo alta.
        es_edicion: ``True`` envía ``PUT .../update_one/{id}`` en vez de
            ``POST .../add_one``.
        es_autocarga: ``True`` deshabilita los campos de identidad
            (nombre y CUIT) y solo deja asignar actividad/partida.
        session_state_update_key: Clave de ``st.session_state`` a
            incrementar tras guardar, para refrescar la grilla.
    """
    # CRÍTICO: Streamlit ejecuta ``@st.dialog`` en un contexto de script
    # separado donde los ``ContextVar`` (usados por ``utils.context`` para
    # propagar el token) NO se heredan automáticamente del script principal.
    # Sin esta sincronización, ``post_request``/``put_request`` recibirían
    # ``None`` y lanzarían ``APIConnectionError("No hay token...")``.
    token = sync_session_token(st.session_state.get("token"))

    # pandas NaN/NA/NaT -> None (JSON-compliant; igual que migration/planillometro.py)
    form_data: dict[str, Any] = {}
    if datos_carga:
        form_data = {
            campo: (None if pd.isna(valor) else valor)
            for campo, valor in datos_carga.items()
        }

    # Referencias del padrón para los selectbox de actividad/partida.
    update_trigger = int(st.session_state.get(session_state_update_key, 0))
    try:
        actividades, partidas = get_referencias_factureros(update_trigger)
    except AppBaseException as exc:
        # No silenciamos: informamos y dejamos los selectbox en modo
        # escritura libre (accept_new_options=True) como fallback.
        st.warning(f"⚠️ No se pudieron cargar las referencias del padrón: {exc}")
        actividades, partidas = [], []

    # En edición, el valor previo debe estar siempre entre las opciones.
    actividad_previa = _a_texto(form_data.get("actividad"))
    partida_previa = _a_texto(form_data.get("partida"))
    if actividad_previa and actividad_previa not in actividades:
        actividades = [actividad_previa, *actividades]
    if partida_previa and partida_previa not in partidas:
        partidas = [partida_previa, *partidas]

    # Estado inicial de los widgets ANTES de crearlos (patrón recomendado
    # por Streamlit: setdefault evita el warning "value + session state").
    st.session_state.setdefault(
        f"{key_prefix}_nombre_completo",
        _a_texto(form_data.get("nombre_completo")),
    )
    st.session_state.setdefault(f"{key_prefix}_cuit", _a_texto(form_data.get("cuit")))
    st.session_state.setdefault(f"{key_prefix}_actividad", actividad_previa or None)
    st.session_state.setdefault(f"{key_prefix}_partida", partida_previa or None)

    # FILA 1: Nombre del Agente (ancho completo)
    nombre_completo = st.text_input(
        "Nombre del Agente",
        key=f"{key_prefix}_nombre_completo",
        disabled=es_autocarga,
        help="Nombre completo del agente tal como figura en el padrón.",
    )

    # FILA 2: CUIT (opcional, ancho completo)
    cuit = st.text_input(
        "CUIT",
        key=f"{key_prefix}_cuit",
        max_chars=11,
        disabled=es_autocarga,
        help="11 dígitos sin guiones. Dejar vacío si el agente no posee CUIT.",
    )

    # FILA 3: Actividad + Partida presupuestaria
    col_actividad, col_partida = st.columns([2, 1])

    # accept_new_options=True: sugiere valores existentes del padrón
    # pero permite cargar actividades/partidas nuevas.
    actividad = col_actividad.selectbox(
        "Actividad",
        options=actividades,
        key=f"{key_prefix}_actividad",
        placeholder="Escriba o elija una Actividad.",
        accept_new_options=True,
        help=(
            "Actividad/estructura presupuestaria del agente. "
            "Formato requerido: 00-00-00-00 (ej: 01-00-00-04)."
        ),
    )

    partida = col_partida.selectbox(
        "Partida Presupuestaria",
        options=partidas,
        key=f"{key_prefix}_partida",
        placeholder="Escriba o elija una Partida.",
        accept_new_options=True,
    )

    if es_edicion:
        st.caption(
            f"Registro ID: `{form_data.get('id')}` | "
            f"Última actualización: {form_data.get('updated_at') or '—'}"
        )

    st.markdown("---")

    # BOTONES (Cancelar / Agregar o Editar)
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel("Cancelar", type="secondary", key=f"{key_prefix}_btn_cancel"):
            st.rerun()  # Cierra el modal de forma segura

        if button_submit(
            "Editar" if es_edicion else "Agregar",
            key=f"{key_prefix}_btn_add",
        ):
            # 1. Validación de datos
            errores: list[str] = []
            nombre_limpio = _a_texto(nombre_completo)
            actividad_limpia = _a_texto(actividad).strip()
            partida_limpia = _a_texto(partida).strip()
            cuit_limpio = _a_texto(cuit).strip()

            if not nombre_limpio:
                errores.append("Debe ingresar el Nombre del Agente.")
            if not actividad_limpia:
                errores.append("Debe indicar la Actividad.")
            elif not re.fullmatch(r"\d{2}-\d{2}-\d{2}-\d{2}", actividad_limpia):
                errores.append(
                    "La Actividad debe tener el formato 00-00-00-00 "
                    "(4 grupos de 2 dígitos separados por guiones)."
                )
            if not partida_limpia:
                errores.append("Debe indicar la Partida Presupuestaria.")
            elif not re.fullmatch(r"\d{3}", partida_limpia):
                errores.append(
                    "La Partida Presupuestaria debe contener exactamente 3 dígitos."
                )
            if cuit_limpio and not re.fullmatch(r"\d{11}", cuit_limpio):
                errores.append(
                    "El CUIT debe contener exactamente 11 dígitos (sin guiones)."
                )

            registro_id = _a_texto(form_data.get("id"))
            if es_edicion and not registro_id:
                errores.append("El registro a editar no tiene un ID válido.")

            if errores:
                for err in errores:
                    st.toast(err, icon="⚠️")
            else:
                # 2. Payload ajustado al esquema de la colección
                # ``factureros`` (models.schemas.FactureroReport).
                payload: dict[str, Any] = {
                    "nombre_completo": nombre_limpio,
                    "cuit": cuit_limpio or None,
                    "actividad": actividad_limpia,
                    "partida": partida_limpia,
                    "updated_at": form_data.get(
                        "updated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ),
                }

                with st.spinner("Guardando agente..."):
                    # 3. Alta: POST /add_one - Edición: PUT /update_one/{id}
                    # token explícito: el ContextVar no se propaga en diálogos.
                    try:
                        if es_edicion:
                            res = put_request(
                                endpoint=(
                                    f"{Endpoints.SLAVE_FACTUREROS.value}"
                                    f"/update_one/{registro_id}"
                                ),
                                json_body=payload,
                                token=token,
                            )
                        else:
                            res = post_request(
                                endpoint=f"{Endpoints.SLAVE_FACTUREROS.value}/add_one",
                                json_body=payload,
                                token=token,
                            )

                        if res:
                            st.snow()
                            st.toast(
                                f"✅ Agente {nombre_limpio} "
                                f"{'editado' if es_edicion else 'agregado'} con éxito",
                                icon="📈",
                            )

                            # Invalida el caché de la grilla y de las referencias
                            st.session_state[session_state_update_key] = (
                                int(st.session_state.get(session_state_update_key, 0))
                                + 1
                            )
                            time.sleep(2)
                            # Cierra el modal y recarga la página principal
                            st.rerun()
                        else:
                            st.error(
                                "La API no confirmó la operación. "
                                "Verifique e intente nuevamente."
                            )

                    except AppBaseException as exc:
                        st.error(f"⚠️ {exc}")
                    except Exception as exc:
                        st.error(f"❌ Ocurrió un error inesperado: {exc}")


# --- MODAL: AGREGAR / EDITAR COMPROBANTE DE HONORARIOS ---
@st.dialog("Comprobante de HONORARIOS", width="large")
def modal_honorarios(
    key_prefix: str,
    datos_carga: dict[str, Any] | None = None,
    es_edicion: bool = False,
    df_honorarios: pd.DataFrame | None = None,
    session_state_update_key: str = "honorarios_dataframes_iteration",
) -> None:
    """
    Modal para dar de alta **o editar** un comprobante de honorarios
    y sus líneas en la colección ``slave_honorarios``.

    **Dos modos:**

    - **Alta** (``es_edicion=False``): ``POST /slave/honorarios/
      add_many/{nro_comprobante}``.
    - **Edición** (``es_edicion=True``): sólo se modifica la
      **carátula** de un comprobante existente (fecha, nro de
      comprobante, cta_cte y tipo) mediante **un único**
      ``PUT .../update_many/{nro_actual}`` validado contra
      ``HonorariosUpdate``. La *path* lleva el nro **actual** (es el
      identificador) y el payload el nro **nuevo**, de modo que el
      comprobante se puede renumerar. Los campos de línea (importes,
      CUIT, actividad, partida) **se conservan sin cambios**: para
      reemplazarlos hay que eliminar el comprobante y volver a
      cargarlo.
      **Excepción — paso a tipo Honorarios:** si el comprobante era
      de un tipo distinto y el nuevo tipo es ``"Honorarios"``, el
      Back mantendría las partidas ``"399"`` forzadas. En ese caso
      el modal **reescribe** las líneas con
      ``DELETE .../delete_many`` + ``POST .../add_many`` y resuelve
      cada ``partida`` contra el padrón de Precarizados (merge por
      nombre normalizado). Si algún agente no matchea se aborta
      **antes** de tocar la API; si el POST falla tras el DELETE se
      intenta restaurar el comprobante original.

    Flujo de **alta**, secuencial y **sin tabs** (las pestañas no se
    pueden bloquear y el usuario podría saltarse el gate):

        1. **Paso 1 (gate):** upload del CSV *Resumen de Pagos por
           Destino* -> ``process_informe_por_destino()`` -> merge con
           ``get_precarizados()``. Si algún agente no matchea o viene
           incompleto, el proceso **se corta ahí**: el Paso 2 nunca se
           renderiza y **no se pierde ningún dato**.
        2. **Paso 2:** fecha, nro de comprobante, cta_cte y tipo. De
           la fecha se derivan ``ejercicio`` y ``mes``; del año, los
           dos últimos dígitos para armar ``"00000/aa"``.
        3. **Confirmación:** envío del payload validado contra
           ``HonorarioReport``.

    **Duplicados:** se hace un *pre-check* en el front usando los
    honorarios ya cargados en la vista (sin llamada extra a la API).
    Es *best-effort* — sólo ve lo que está filtrado — por lo que la
    autoridad final sigue siendo el Back, cuyo error se muestra si
    rechaza la carga.

    Args:
        key_prefix: Prefijo único para las keys de los widgets (con
            timestamp con microsegundos, igual que ``modal_precarizado``).
        datos_carga: Fila a editar (``df.iloc[i].to_dict()`` de la
            grilla agrupada); ``None`` en modo alta.
        es_edicion: ``True`` habilita el modo edición (carátula) y
            deshabilita el Paso 1 de carga de CSV.
        df_honorarios: DataFrame **sin agrupar** de la colección
            (con los ``id`` de cada línea). Sólo es necesario en modo
            edición; de ``None`` el modal informa y no permite
            continuar.
        session_state_update_key: Clave de ``st.session_state`` a
            incrementar tras guardar, para refrescar la grilla de
            honorarios (y las referencias de ``tipo``/``cta_cte``).
    """
    # CRÍTICO: ``@st.dialog`` corre en un contexto de script separado
    # donde los ``ContextVar`` del token NO se heredan.
    token = sync_session_token(st.session_state.get("token"))

    def _barra_cancelar() -> None:
        with st.container(
            horizontal=True, border=False, horizontal_alignment="center", gap="large"
        ):
            if button_cancel(
                "Cancelar", key=f"{key_prefix}_btn_cancel", type="secondary"
            ):
                st.rerun()

    # ═══════════ PREPARACIÓN COMÚN (ambos modos) ═══════════
    update_trigger = int(st.session_state.get(session_state_update_key, 0))

    # El padrón de Precarizados se invalida con SU propio trigger (no
    # con el de honorarios): así comparte caché con el sync y con la
    # vista de Precarizados en vez de forzar una llamada a la API.
    trigger_precarizados = int(
        st.session_state.get(report_data_version_key("precarizados"), 0)
    )

    # NOTA: get_referencias_honorarios (tipos / ctas. ctes.) se resuelve
    # RECIÉN antes de los widgets de carátula: sólo la necesitan los
    # selectbox de la carátula, así que en el modo alta el Paso 1
    # (uploader) se dibuja sin tocar la API.

    # Pre-check de duplicados: usa los honorarios ya cargados en la
    # vista (gratis, sin llamada extra). Es best-effort porque sólo ve
    # lo que está filtrado; la autoridad final es el Back.
    existentes: set[str] = set()
    if (
        df_honorarios is not None
        and not df_honorarios.empty
        and "nro_comprobante" in df_honorarios.columns
    ):
        existentes = {
            _a_texto(v) for v in df_honorarios["nro_comprobante"].unique()
        } - {""}

    # ── MODO EDICIÓN: resolver las líneas del comprobante ──
    nro_original: str = ""
    tipo_original: str = ""
    df_docs = pd.DataFrame()
    if es_edicion:
        if df_honorarios is None or df_honorarios.empty:
            st.error("No hay datos de honorarios disponibles para editar.")
            _barra_cancelar()
            return
        nro_original = _a_texto((datos_carga or {}).get("nro_comprobante"))
        if "nro_comprobante" in df_honorarios.columns:
            df_docs = df_honorarios[
                df_honorarios["nro_comprobante"].astype(str).str.strip() == nro_original
            ].copy()
        if df_docs.empty:
            st.error(f"No se encontraron las líneas del comprobante `{nro_original}`.")
            _barra_cancelar()
            return
        # Tipo previo del comprobante: define si al guardar hay que
        # reescribir las líneas (paso a Honorarios con partidas "399").
        tipo_original = _a_texto((datos_carga or {}).get("tipo")).strip()
        if not tipo_original and "tipo" in df_docs.columns:
            tipo_original = _a_texto(df_docs["tipo"].iloc[0]).strip()

    # ═══════════ BLOQUE SUPERIOR (según modo) ═══════════
    df_merged = pd.DataFrame()
    if es_edicion:
        st.markdown("#### Comprobante a editar")
        st.caption(
            f"Se actualizará la **carátula** del comprobante "
            f"`{nro_original}` (**{len(df_docs)}** líneas) en una sola "
            "operación. Puede cambiar fecha, nro de comprobante, "
            "cta_cte y tipo; los importes, CUIT, actividad y partida "
            "se conservan sin cambios.\n\n"
            "⚠️ Si cambia el tipo a **Honorarios** viniendo de otro "
            "tipo, el comprobante se **reescribirá** (DELETE + ADD) y "
            "las partidas se resolverán contra el padrón de "
            "Precarizados.\n\n"
            "ℹ️ Para **reemplazar las líneas** del comprobante, "
            "elimínelo con *Borrar* y vuélvalo a cargar."
        )
        with st.expander("Líneas actuales del comprobante"):
            st.dataframe(df_docs, width="stretch")
        st.markdown("#### Carátula")
    else:
        # ═══════════════ PASO 1 · INFORME (GATE) ═══════════════
        st.markdown("#### Paso 1 · Informe por Destino")
        st.caption(
            "Cargue el CSV del *Informe por Destino* del *Sistema de Gestión Financiera*. El "
            "formulario se habilita únicamente si **todos** los agentes "
            "figuran en el padrón de Precarizados con CUIT, Actividad y "
            "Partida."
        )

        uploaded_file = st.file_uploader(
            "Archivo CSV",
            type=["csv"],
            key=f"{key_prefix}_upload_informe",
            help="Exportado del Sistema de Gestión Financiera en el menú 'Informes / Por Destino'.",
        )

        if uploaded_file is None:
            st.info("⏳ Cargue el archivo CSV para continuar.")
            _barra_cancelar()
            return

        # ``getvalue()`` no consume el stream: re-leer en cada rerun.
        df_informe = process_informe_por_destino(BytesIO(uploaded_file.getvalue()))
        if df_informe.empty:
            st.error(
                "❌ No se pudo interpretar el CSV. Verifique que sea el "
                "reporte 'Resumen de Pagos por Destino' y que no esté vacío."
            )
            _barra_cancelar()
            return

        try:
            df_precarizados = get_precarizados(update_trigger=trigger_precarizados)
        except AppBaseException as exc:
            st.error(f"⚠️ No se pudo obtener el padrón de Precarizados: {exc}")
            _barra_cancelar()
            return

        df_merged, sin_match, incompletos = merge_informe_con_precarizados(
            df_informe, df_precarizados
        )

        # ── GATE: agentes faltantes => se corta el proceso aquí ──
        if sin_match or incompletos:
            if sin_match:
                st.error(
                    f"🚫 **{len(sin_match)} agente(s) NO figuran en el "
                    "padrón de Precarizados.** Deben darse de alta antes "
                    "de continuar:"
                )
                for nombre in sin_match:
                    st.markdown(f"- `{nombre}`")
            if incompletos:
                st.error(
                    f"🚫 **{len(incompletos)} agente(s) figuran con datos "
                    "incompletos** (falta CUIT, Actividad o Partida). "
                    "Deben completarse antes de continuar:"
                )
                for nombre in incompletos:
                    st.markdown(f"- `{nombre}`")

            st.warning(
                "**El proceso se detiene aquí.** Cancele, cargue esos "
                "agentes desde la vista *Precarizados* y vuelva a "
                "intentarlo. Al reabrir este modal sólo deberá volver a "
                "subir el CSV."
            )
            _barra_cancelar()
            return

        st.success(
            f"✅ **{len(df_merged)}** registros leídos · todos con "
            "CUIT / Actividad / Partida resueltos."
        )
        with st.expander("Vista previa de los registros a cargar"):
            st.dataframe(df_merged.head(15), width="stretch")

        st.markdown("#### Paso 2 · Datos del Comprobante")
    # ═══════════ REFERENCIAS · TIPOS / CTAS. CTES. ═══════════
    # Se resuelven recién acá -y no al abrir el modal- porque sólo las
    # necesitan los selectbox de la carátula: en el modo alta, el Paso 1
    # (uploader) se dibuja sin tocar la API, así que la primera apertura
    # del botón "Agregar" es inmediata. Son endpoints ligeros con su
    # propio Parquet; la vista de Honorarios precalienta el caché al
    # cargar la página.
    try:
        tipos, ctas_ctes = get_referencias_honorarios(update_trigger)
    except AppBaseException as exc:
        # No silenciamos: informamos y dejamos los selectbox en modo
        # escritura libre (accept_new_options=True) como fallback.
        st.warning(
            f"⚠️ No se pudieron cargar los tipos de comprobante y/o las "
            f"cuentas corrientes: {exc}"
        )
        tipos, ctas_ctes = [], []

    # ═══════════ WIDGETS DE CARÁTULA (compartidos) ═══════════
    # Valores iniciales según modo. Usamos ``setdefault`` (patrón de
    # ``modal_precarizado``) para poder pre-cargar la carátula en
    # edición sin pisar la sesión.
    if es_edicion:
        fecha_inicial = _a_fecha((datos_carga or {}).get("fecha")) or date.today()
        nro_inicial = separar_nro_comprobante(nro_original)
        cta_inicial = ""
        if not df_docs.empty and "cta_cte" in df_docs.columns:
            cta_inicial = _a_texto(df_docs["cta_cte"].iloc[0])
        tipo_inicial = tipo_original or None
        # El valor previo debe estar siempre entre las opciones.
        if cta_inicial and cta_inicial not in ctas_ctes:
            ctas_ctes = [cta_inicial, *ctas_ctes]
        if tipo_inicial and tipo_inicial not in tipos:
            tipos = [tipo_inicial, *tipos]
    else:
        # Alta: conservamos el comportamiento previo del modal.
        fecha_inicial = date.today()
        nro_inicial = ""
        cta_inicial = ctas_ctes[0] if ctas_ctes else None
        tipo_inicial = tipos[0] if tipos else None

    st.session_state.setdefault(f"{key_prefix}_fecha", fecha_inicial)
    st.session_state.setdefault(f"{key_prefix}_nro", nro_inicial)
    st.session_state.setdefault(f"{key_prefix}_cta_cte", cta_inicial)
    st.session_state.setdefault(f"{key_prefix}_tipo", tipo_inicial)

    col_fecha, col_nro = st.columns(2)
    fecha = col_fecha.date_input(
        "Fecha del comprobante",
        key=f"{key_prefix}_fecha",
        format="DD/MM/YYYY",
    )
    nro_base = col_nro.text_input(
        "Nro. de comprobante",
        key=f"{key_prefix}_nro",
        placeholder="Ej: 123",
        help="Sólo dígitos (hasta 5). Se completa con el año: 00000/aa.",
    )

    col_cta, col_tipo = st.columns(2)
    cta_cte = col_cta.selectbox(
        "Cuenta Corriente",
        options=ctas_ctes,
        key=f"{key_prefix}_cta_cte",
        placeholder="Escriba o elija una Cuenta Corriente.",
        accept_new_options=True,
    )
    tipo = col_tipo.selectbox(
        "Tipo de Comprobante",
        options=tipos,
        key=f"{key_prefix}_tipo",
        placeholder="Escriba o elija un Tipo.",
        accept_new_options=True,
    )

    # ── Datos derivados de la fecha ──
    # Mismos cálculos en alta y edición: el nro se arma con el año de
    # la fecha. En edición, ``nro_comprobante`` es el NUEVO número que
    # viaja en el payload, mientras la path de ``update_many`` lleva
    # ``nro_original`` (el actual, identificador del comprobante).
    ejercicio: int = fecha.year
    mes: str = fecha.strftime("%m/%Y")
    nro_limpio: str = (nro_base or "").strip()
    nro_valido: bool = bool(re.fullmatch(r"\d{1,5}", nro_limpio))
    nro_comprobante: str = componer_nro_comprobante(nro_limpio, ejercicio)
    # selectbox sin selección devuelve None; ``str(None)`` sería
    # "None" (truthy), por eso se normaliza ANTES de validar.
    tipo_limpio: str = "" if tipo is None else str(tipo).strip()
    cta_limpia: str = "" if cta_cte is None else str(cta_cte).strip()

    # ¿La edición pasa un comprobante NO-Honorarios a Honorarios? En
    # ese caso el Back mantendría las partidas "399" forzadas y hay
    # que reescribir las líneas con las partidas reales del padrón.
    cambio_a_honorarios: bool = (
        es_edicion
        and tipo_limpio == TIPO_HONORARIOS
        and tipo_original != TIPO_HONORARIOS
    )

    st.caption(
        f"**Ejercicio:** `{ejercicio}` · **Mes:** `{mes}` · "
        f"**Nro. comprobante:** `{nro_comprobante or '—'}`"
        + (
            f" · *(actual: `{nro_original}`)*"
            if es_edicion and nro_comprobante != nro_original
            else ""
        )
    )

    # ═══════════ CONFIRMACIÓN ═══════════
    st.markdown("#### Confirmación")
    if es_edicion:
        nuevo_txt: str = (
            f" y **renumerará** a `{nro_comprobante}`"
            if nro_comprobante != nro_original
            else ""
        )
        if cambio_a_honorarios:
            st.caption(
                f"Al pasar a tipo **Honorarios**, se **reescribirán** "
                f"las **{len(df_docs)}** línea(s) del comprobante "
                f"`{nro_original}` con `DELETE .../delete_many` + "
                f"`POST .../add_many`: cada partida se resolverá "
                f"contra el padrón de Precarizados{nuevo_txt}."
            )
        else:
            endpoint_desc: str = (
                f"`{Endpoints.SLAVE_HONORARIOS.value}/update_many/"
                f"{quote(nro_original, safe='')}`"
            )
            st.caption(
                f"Se actualizará la carátula de **{len(df_docs)}** línea(s) "
                f"del comprobante `{nro_original}` con **un solo `PUT`** a "
                f"{endpoint_desc}{nuevo_txt}."
            )
    else:
        endpoint_desc = (
            f"`{Endpoints.SLAVE_HONORARIOS.value}/add_many/"
            f"{quote(nro_comprobante, safe='') if nro_comprobante else '...'}"
        )
        st.caption(f"Se enviarán **{len(df_merged)}** documentos a {endpoint_desc}.")

    st.markdown("---")
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel(
            "Cancelar", key=f"{key_prefix}_btn_cancel_final", type="secondary"
        ):
            st.rerun()

        etiqueta = "Guardar Cambios" if es_edicion else "Cargar Comprobante"
        if button_submit(etiqueta, key=f"{key_prefix}_btn_submit"):
            errores: list[str] = []
            if not nro_valido:
                errores.append("El Nro. de comprobante debe tener entre 1 y 5 dígitos.")
            if not fecha:
                errores.append("Debe indicar la Fecha.")
            if not cta_limpia:
                errores.append("Debe indicar la Cuenta Corriente.")
            if not tipo_limpio:
                errores.append("Debe indicar el Tipo de comprobante.")

            # Pre-check de duplicados. En edición excluimos el nro
            # original para no bloquear un guardado sin cambios.
            if (
                nro_valido
                and nro_comprobante in existentes
                and nro_comprobante != nro_original
            ):
                errores.append(
                    f"El comprobante `{nro_comprobante}` ya existe. Si "
                    "necesita corregirlo, edítelo desde la grilla."
                )

            if errores:
                for err in errores:
                    st.toast(err, icon="⚠️")
                return

            fecha_dt = datetime(fecha.year, fecha.month, fecha.day)

            # ══════════ MODO EDICIÓN ══════════
            if es_edicion:
                # ── Caso especial: no-Honorarios → Honorarios ──
                # El Back fuerza la partida "399" a todo tipo distinto
                # de Honorarios y, al volver a Honorarios, no sabe qué
                # partida corresponde a cada agente: hay que reescribir
                # las líneas con las partidas del padrón.
                if cambio_a_honorarios:
                    try:
                        df_precarizados = get_precarizados(
                            update_trigger=trigger_precarizados
                        )
                    except AppBaseException as exc:
                        st.error(
                            f"⚠️ No se pudo obtener el padrón de Precarizados: {exc}"
                        )
                        return

                    try:
                        registros_reescritura: list[dict[str, Any]]
                        sin_partida: list[str]
                        registros_reescritura, sin_partida = (
                            construir_payload_reescritura(
                                df_docs,
                                df_precarizados,
                                ejercicio=ejercicio,
                                mes=mes,
                                fecha=fecha_dt,
                                nro_comprobante=nro_comprobante,
                                cta_cte=cta_limpia,
                                tipo=tipo_limpio,
                            )
                        )
                    except ValidationError as exc:
                        st.error(
                            f"⚠️ Los datos no cumplen el esquema HonorarioReport: {exc}"
                        )
                        return

                    # GATE: si alguna partida no se resuelve, NO se
                    # toca la API (mismo criterio que el Paso 1 del
                    # modo alta).
                    if sin_partida:
                        st.error(
                            "🚫 **No se pudieron resolver las partidas "
                            "correctas** para el tipo *Honorarios*. Estos "
                            "agentes no figuran en el padrón de "
                            "Precarizados (o figuran sin partida):"
                        )
                        for nombre_agente in sin_partida:
                            st.markdown(f"- `{nombre_agente}`")
                        st.warning(
                            "**El proceso se detiene aquí sin realizar "
                            "cambios.** Complete el padrón desde la "
                            "vista *Precarizados* y vuelva a intentarlo."
                        )
                        return

                    # Payload de rollback: líneas originales con la
                    # carátula previa, por si el POST falla después
                    # del DELETE (las partidas "399" ya vienen en
                    # df_docs y el Back las re-aplica al no ser
                    # Honorarios).
                    fila_inicial: pd.Series = df_docs.iloc[0]
                    ejercicio_original: int = ejercicio
                    if "ejercicio" in df_docs.columns and pd.notna(
                        fila_inicial.get("ejercicio")
                    ):
                        ejercicio_original = int(fila_inicial["ejercicio"])
                    mes_original: str = _a_texto(fila_inicial.get("mes")) or mes
                    cta_original: str = (
                        _a_texto(fila_inicial.get("cta_cte")) or cta_limpia
                    )
                    fecha_original: date | None = _a_fecha(fila_inicial.get("fecha"))
                    try:
                        registros_originales: list[dict[str, Any]] = (
                            construir_payload_honorarios(
                                df_docs,
                                ejercicio=ejercicio_original,
                                mes=mes_original,
                                fecha=(
                                    datetime.combine(
                                        fecha_original, datetime.min.time()
                                    )
                                    if fecha_original
                                    else fecha_dt
                                ),
                                nro_comprobante=nro_original,
                                cta_cte=cta_original,
                                tipo=tipo_original,
                            )
                        )
                    except ValidationError as exc:
                        st.error(
                            f"⚠️ Las líneas originales no cumplen el "
                            f"esquema HonorarioReport: {exc}"
                        )
                        return

                    def _restaurar_originales(motivo: str) -> None:
                        """Reintenta cargar las líneas originales del
                        comprobante tras un fallo del POST de
                        reescritura y notifica el resultado."""
                        motivo_restaurado: str = ""
                        try:
                            restaurado = post_request(
                                f"{Endpoints.SLAVE_HONORARIOS.value}"
                                f"/add_many/{quote(nro_original, safe='')}",
                                json_body=registros_originales,
                                token=token,
                            )
                        except AppBaseException as exc:
                            restaurado = None
                            motivo_restaurado = str(exc)

                        if restaurado:
                            st.warning(
                                f"⚠️ La reescritura falló ({motivo}). Se "
                                f"**restauró** el comprobante "
                                f"`{nro_original}` tal como estaba; no se "
                                "realizaron cambios."
                            )
                        else:
                            st.error(
                                f"❌ La reescritura falló ({motivo}) y el "
                                f"restaurado también "
                                f"({motivo_restaurado or 'sin detalle'}). "
                                f"El comprobante `{nro_original}` quedó "
                                "**sin líneas**: vuelva a cargarlo desde "
                                "el CSV."
                            )
                        # Invalida el caché de la grilla para que el
                        # próximo render refleje el estado real.
                        st.session_state[session_state_update_key] = (
                            int(st.session_state.get(session_state_update_key, 0)) + 1
                        )

                    endpoint_borrado: str = (
                        f"{Endpoints.SLAVE_HONORARIOS.value}"
                        f"/delete_many/{quote(nro_original, safe='')}"
                    )
                    endpoint_reescritura: str = (
                        f"{Endpoints.SLAVE_HONORARIOS.value}"
                        f"/add_many/{quote(nro_comprobante, safe='')}"
                    )

                    with st.spinner(
                        f"Reescribiendo {len(registros_reescritura)} "
                        "línea(s) con las partidas del padrón..."
                    ):
                        # 1) Borrar las líneas actuales (partidas
                        #    "399" forzadas por el Back).
                        try:
                            borrado = delete_request(endpoint_borrado, token=token)
                        except AppBaseException as exc:
                            st.error(
                                f"⚠️ No se pudo eliminar el comprobante original: {exc}"
                            )
                            return

                        if not borrado:
                            st.error(
                                "La API no confirmó el borrado. "
                                "No se realizó ningún cambio."
                            )
                            return

                        # 2) Crear las líneas con las partidas
                        #    resueltas contra el padrón.
                        motivo_fallo: str = ""
                        try:
                            res = post_request(
                                endpoint_reescritura,
                                json_body=registros_reescritura,
                                token=token,
                            )
                        except AppBaseException as exc:
                            res = None
                            motivo_fallo = str(exc)

                        if not res:
                            _restaurar_originales(
                                motivo_fallo or "la API no confirmó la operación"
                            )
                            return

                        st.snow()
                        st.toast(
                            f"✅ Comprobante `{nro_comprobante}` reescrito: "
                            f"{len(registros_reescritura)} línea(s) con "
                            "partidas corregidas",
                            icon="📈",
                        )
                        # Invalida el caché de la grilla y referencias.
                        st.session_state[session_state_update_key] = (
                            int(st.session_state.get(session_state_update_key, 0)) + 1
                        )
                        time.sleep(2)
                        st.rerun()
                    return

                # ── Resto de los casos: UN SOLO PUT update_many ──
                # Validación estricta contra HonorariosUpdate: si algo
                # falla, NO se envía nada a la API.
                try:
                    payload: dict[str, Any] = construir_payload_actualizacion_caratula(
                        nro_comprobante=nro_comprobante,
                        ejercicio=ejercicio,
                        mes=mes,
                        fecha=fecha_dt,
                        tipo=tipo_limpio,
                        cta_cte=cta_limpia,
                    )
                except ValidationError as exc:
                    st.error(f"⚠️ Los datos no cumplen HonorariosUpdate: {exc}")
                    return

                # La PATH lleva el nro ACTUAL (identifica el
                # comprobante); el nro nuevo viaja en el payload.
                endpoint_edicion: str = (
                    f"{Endpoints.SLAVE_HONORARIOS.value}/update_many/"
                    f"{quote(nro_original, safe='')}"
                )

                with st.spinner(f"Actualizando carátula de {len(df_docs)} línea(s)..."):
                    try:
                        # token explícito: el ContextVar no se propaga
                        # en diálogos.
                        res = put_request(
                            endpoint=endpoint_edicion,
                            json_body=payload,
                            token=token,
                        )
                    except AppBaseException as exc:
                        st.error(f"⚠️ {exc}")
                        return

                    if not res:
                        st.error(
                            "La API no confirmó la operación. "
                            "Verifique e intente nuevamente."
                        )
                        return

                    st.snow()
                    st.toast(
                        f"✅ Comprobante `{nro_comprobante}` actualizado: "
                        f"carátula de {len(df_docs)} línea(s)",
                        icon="📈",
                    )
                    # Invalida el caché de la grilla y de las referencias.
                    st.session_state[session_state_update_key] = (
                        int(st.session_state.get(session_state_update_key, 0)) + 1
                    )
                    time.sleep(2)
                    st.rerun()
                return

            # ═══════════ MODO ALTA: POST add_many ═══════════
            # Validación estricta contra HonorarioReport: si algo
            # falla, NO se envía nada a la API.
            try:
                registros: list[dict[str, Any]] = construir_payload_honorarios(
                    df_merged,
                    ejercicio=ejercicio,
                    mes=mes,
                    fecha=fecha_dt,
                    nro_comprobante=nro_comprobante,
                    cta_cte=cta_limpia,
                    tipo=tipo_limpio,
                )
            except ValidationError as exc:
                st.error(f"⚠️ Los datos no cumplen el esquema HonorarioReport: {exc}")
                return

            endpoint: str = (
                f"{Endpoints.SLAVE_HONORARIOS.value}/add_many/"
                f"{quote(nro_comprobante, safe='')}"
            )

            with st.spinner(f"Enviando {len(registros)} documentos..."):
                try:
                    # token explícito: el ContextVar no se propaga en diálogos.
                    res = post_request(endpoint, json_body=registros, token=token)
                except AppBaseException as exc:
                    st.error(f"⚠️ {exc}")
                    return

                if res:
                    st.snow()
                    st.toast(
                        f"✅ Comprobante {nro_comprobante}: "
                        f"+{len(registros)} documentos",
                        icon="📈",
                    )
                    # Invalida el caché de la grilla y de las referencias.
                    st.session_state[session_state_update_key] = (
                        int(st.session_state.get(session_state_update_key, 0)) + 1
                    )
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(
                        "La API no confirmó la operación. "
                        "Verifique e intente nuevamente."
                    )
