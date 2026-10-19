"""Modales (``st.dialog``) reutilizables de la capa de vistas."""

import re
import time
from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from components.buttons import button_cancel, button_submit
from models.schemas import ObrasRecuperadasReport
from services.api import delete_request, post_request, put_request
from services.data_fetcher import get_ejercicios_list, get_obras_recuperadas
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


# --- MODAL: AGREGAR / EDITAR OBRA RECUPERADA ---
@st.dialog("Agregar / Editar OBRA RECUPERADA", width="medium")
def modal_obras_recuperadas(
    key_prefix: str,
    datos_carga: dict[str, Any] | None = None,
    es_edicion: bool = False,
    session_state_update_key: str = report_data_version_key("obras_recuperadas"),
) -> None:
    """
    Modal para dar de alta o editar una obra recuperada.

    Opera sobre la colección ``sgv_obras_recuperadas`` con los campos
    de ``models.schemas.ObrasRecuperadasReport``:

    - **Alta** (``es_edicion=False``): ``POST .../add_one`` (el Back
      genera el ``id``).
    - **Edición** (``es_edicion=True``): ``PUT .../update_one/{id}``.

    Los ``selectbox`` de Cód. Barrio y Estructura se poblan con los
    valores únicos de la propia colección
    (:func:`get_obras_recuperadas`) y aceptan opciones nuevas
    (``accept_new_options=True``). Si esa lectura falla se informa con
    ``st.warning`` y los combos quedan en modo escritura libre.

    Args:
        key_prefix: Prefijo único para las keys de los widgets (con
            timestamp con microsegundos, igual que el resto de modales).
        datos_carga: Fila a editar (``df.iloc[i].to_dict()``); ``None``
            en modo alta.
        es_edicion: ``True`` envía ``PUT .../update_one/{id}`` en vez de
            ``POST .../add_one``.
        session_state_update_key: Clave de ``st.session_state`` a
            incrementar tras guardar, para refrescar la grilla.
    """
    # CRÍTICO: Streamlit ejecuta ``@st.dialog`` en un contexto de script
    # separado donde los ``ContextVar`` (usados por ``utils.context`` para
    # propagar el token) NO se heredan automáticamente del script principal.
    # Sin esta sincronización, ``get_obras_recuperadas``/``post_request``
    # recibirían ``None`` y lanzarían ``APIConnectionError("No hay token...")``.
    token = sync_session_token(st.session_state.get("token"))

    # pandas NaN/NA/NaT -> None (JSON-compliant; igual que modal_precarizado).
    form_data: dict[str, Any] = {}
    if datos_carga:
        form_data = {
            campo: (None if pd.isna(valor) else valor)
            for campo, valor in datos_carga.items()
        }

    # ── Referencias: valores únicos de la propia colección ──
    update_trigger = int(st.session_state.get(session_state_update_key, 0))
    try:
        df_referencia = get_obras_recuperadas(update_trigger=update_trigger)
    except AppBaseException as exc:
        # No silenciamos: informamos y dejamos los selectbox en modo
        # escritura libre (accept_new_options=True) como fallback.
        st.warning(f"⚠️ No se pudieron cargar las referencias: {exc}")
        df_referencia = pd.DataFrame()

    cod_barrios: list[str] = []
    estructuras: list[str] = []
    if not df_referencia.empty:
        if "cod_barrio" in df_referencia.columns:
            cod_barrios = sorted(
                {_a_texto(v).strip() for v in df_referencia["cod_barrio"]} - {""}
            )
        if "estructura" in df_referencia.columns:
            estructuras = sorted(
                {_a_texto(v).strip() for v in df_referencia["estructura"]} - {""}
            )

    # En edición, el valor previo debe estar siempre entre las opciones.
    cod_barrio_previo = _a_texto(form_data.get("cod_barrio")).strip()
    estructura_previa = _a_texto(form_data.get("estructura")).strip()
    if cod_barrio_previo and cod_barrio_previo not in cod_barrios:
        cod_barrios = [cod_barrio_previo, *cod_barrios]
    if estructura_previa and estructura_previa not in estructuras:
        estructuras = [estructura_previa, *estructuras]

    # Ejercicios: lista local (sin API); alta = último (año en curso).
    ejercicios: list[int] = get_ejercicios_list()
    ejercicio_inicial: int = ejercicios[-1]
    if es_edicion and form_data.get("ejercicio") is not None:
        ejercicio_inicial = int(form_data["ejercicio"])
    if ejercicio_inicial not in ejercicios:
        ejercicios = [ejercicio_inicial, *ejercicios]

    importe_inicial: float = 0.0
    if es_edicion and form_data.get("importe") is not None:
        importe_inicial = float(form_data["importe"])

    # Estado inicial de los widgets ANTES de crearlos (patrón setdefault
    # recomendado por Streamlit: evita el warning "value + session state").
    st.session_state.setdefault(f"{key_prefix}_ejercicio", ejercicio_inicial)
    st.session_state.setdefault(f"{key_prefix}_cod_barrio", cod_barrio_previo or None)
    st.session_state.setdefault(f"{key_prefix}_estructura", estructura_previa or None)
    st.session_state.setdefault(f"{key_prefix}_importe", importe_inicial)
    st.session_state.setdefault(f"{key_prefix}_notas", _a_texto(form_data.get("notas")))

    col_ejercicio, col_barrio = st.columns(2)
    ejercicio = col_ejercicio.selectbox(
        "Ejercicio",
        options=ejercicios,
        key=f"{key_prefix}_ejercicio",
        help="Ejercicio (año) al que pertenece la obra recuperada.",
    )
    # accept_new_options=True: sugiere valores ya cargados pero permite
    # ingresar códigos de barrio nuevos.
    cod_barrio = col_barrio.selectbox(
        "Cód. Barrio",
        options=cod_barrios,
        key=f"{key_prefix}_cod_barrio",
        placeholder="Escriba o elija un Cód. de Barrio.",
        accept_new_options=True,
        help="Código de barrio del padrón (ej: 884).",
    )

    col_estructura, col_importe = st.columns([2, 1])
    estructura = col_estructura.selectbox(
        "Estructura",
        options=estructuras,
        key=f"{key_prefix}_estructura",
        placeholder="Escriba o elija una Estructura.",
        accept_new_options=True,
        help="Formato requerido: 00-00-00-00-000 (ej: 11-00-02-79-421).",
    )
    importe = col_importe.number_input(
        "Importe",
        key=f"{key_prefix}_importe",
        step=0.01,
        format="%.2f",
        help="Importe de la recuperación (acepta negativos).",
    )

    notas = st.text_area(
        "Notas",
        key=f"{key_prefix}_notas",
        height=100,
        help="Observaciones u otra información relevante (opcional).",
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
            ejercicio_sel = ejercicio  # selectbox: siempre un int válido
            cod_barrio_limpio = _a_texto(cod_barrio).strip()
            estructura_limpia = _a_texto(estructura).strip()
            notas_limpia = _a_texto(notas).strip()
            importe_limpio = float(importe)  # number_input: numérico

            if not cod_barrio_limpio:
                errores.append("Debe indicar el Cód. de Barrio.")
            elif not re.fullmatch(r"\d{1,4}", cod_barrio_limpio):
                errores.append(
                    "El Cód. de Barrio debe contener de 1 a 4 dígitos (ej: 884)."
                )
            if not estructura_limpia:
                errores.append("Debe indicar la Estructura.")
            elif not re.fullmatch(r"\d{2}-\d{2}-\d{2}-\d{2}-\d{3}", estructura_limpia):
                errores.append(
                    "La Estructura debe tener el formato 00-00-00-00-000 "
                    "(ej: 11-00-02-79-421)."
                )

            registro_id = _a_texto(form_data.get("id"))
            if es_edicion and not registro_id:
                errores.append("El registro a editar no tiene un ID válido.")

            if errores:
                for err in errores:
                    st.toast(err, icon="⚠️")
                return

            # 2. Payload ajustado al esquema de la colección
            # ``sgv_obras_recuperadas`` (models.schemas.ObrasRecuperadasReport).
            payload: dict[str, Any] = {
                "ejercicio": int(ejercicio_sel),
                "cod_barrio": cod_barrio_limpio,
                "estructura": estructura_limpia,
                "importe": importe_limpio,
                "notas": notas_limpia,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            # Validación estricta: si algo falla, NO se envía nada.
            try:
                ObrasRecuperadasReport(**payload)
            except ValidationError as exc:
                st.error(f"⚠️ Los datos no cumplen ObrasRecuperadasReport: {exc}")
                return

            with st.spinner("Guardando obra recuperada..."):
                # 3. Alta: POST /add_one - Edición: PUT /update_one/{id}
                # token explícito: el ContextVar no se propaga en diálogos.
                try:
                    if es_edicion:
                        res = put_request(
                            endpoint=(
                                f"{Endpoints.OBRAS_RECUPERADAS.value}"
                                f"/update_one/{registro_id}"
                            ),
                            json_body=payload,
                            token=token,
                        )
                    else:
                        res = post_request(
                            endpoint=(f"{Endpoints.OBRAS_RECUPERADAS.value}/add_one"),
                            json_body=payload,
                            token=token,
                        )
                except AppBaseException as exc:
                    st.error(f"⚠️ {exc}")
                    return
                except Exception as exc:
                    st.error(f"❌ Ocurrió un error inesperado: {exc}")
                    return

                if not res:
                    st.error(
                        "La API no confirmó la operación. "
                        "Verifique e intente nuevamente."
                    )
                    return

                st.snow()
                st.toast(
                    f"✅ Obra Recuperada {estructura_limpia} "
                    f"{'editada' if es_edicion else 'agregada'} con éxito",
                    icon="📈",
                )

                # Invalida el caché de la grilla (@st.cache_data).
                st.session_state[session_state_update_key] = (
                    int(st.session_state.get(session_state_update_key, 0)) + 1
                )
                time.sleep(2)
                # Cierra el modal y recarga la página principal.
                st.rerun()
