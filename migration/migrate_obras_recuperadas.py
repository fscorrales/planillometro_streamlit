#!/usr/bin/env python3
"""Migración: Google Sheet "Obras Recuperadas" -> MongoDB vía API Koyeb.

Lee la hoja "Obras Recuperadas" del Google Sheet
(https://docs.google.com/spreadsheets/d/1Hmb7xmzhZBoicnL5_tN7mr1kOj-r3gw8lCkPErR8Xd4)
usando las credenciales de servicio de ``GOOGLE_CREDENTIALS`` (.env), valida
cada fila contra ``models.schemas.ObrasRecuperadasReport`` y sube los documentos
a la colección ``sgv_obras_recuperadas`` agrupados por ``ejercicio``.

Importante:
    El endpoint ``POST /sgv/obrasRecuperadas`` reemplaza automáticamente todos
    los documentos existentes del ``ejercicio`` del grupo recibido, por lo que
    se emite un POST por cada grupo de documentos del mismo ejercicio.

Uso:
    python migration/migrate_obras_recuperadas.py --dry-run
    python migration/migrate_obras_recuperadas.py
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# Permite ejecutar el script desde cualquier directorio sin depender de
# la variable de entorno PYTHONPATH=.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gspread  # noqa: E402

from models.schemas import ObrasRecuperadasReport  # noqa: E402
from services.api import fetch_data, post_request  # noqa: E402
from services.auth_service import login  # noqa: E402
from utils.config import settings  # noqa: E402
from utils.exceptions import (  # noqa: E402
    APIConnectionError,
    APIResponseError,
    AppBaseException,
    AuthenticationError,
    ValidationError,
)
from utils.google_sheets import GoogleSheets  # noqa: E402
from utils.transform_data import parse_moneda_ar  # noqa: E402

SPREADSHEET_KEY: str = "1Hmb7xmzhZBoicnL5_tN7mr1kOj-r3gw8lCkPErR8Xd4"
WORKSHEET_NAME: str = "Obras Recuperadas"
ENDPOINT: str = "/sgv/obrasRecuperadas"

# Campos obligatorios del documento que espera la API.
REQUIRED_FIELDS: tuple[str, ...] = (
    "ejercicio",
    "cod_barrio",
    "estructura",
    "importe",
    "notas",
)

# Alias normalizados (sin acentos, minúsculas, snake_case) aceptados para
# cada campo del modelo. Se comparan contra los headers normalizados de la
# hoja para tolerar diferencias de formato ("Cód. Barrio", "CÓD BARRIO"...).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "ejercicio": ("ejercicio", "anio", "ano", "ejercicios"),
    "cod_barrio": (
        "cod_barrio",
        "codigo_barrio",
        "cod_bar",
        "codbarrio",
        "barrio_cod",
        "codigo",
        "cod",
    ),
    "estructura": ("estructura", "est_estructura", "estructuras", "imputacion"),
    "importe": ("importe", "monto", "total", "valor"),
    "notas": ("notas", "nota", "observaciones", "obs", "comentarios"),
}


# Campos mínimos que debe traer el JSON de la service account en
# GOOGLE_CREDENTIALS (además de "type" y "private_key_id").
REQUIRED_CREDENTIAL_KEYS: tuple[str, ...] = (
    "client_email",
    "token_uri",
    "private_key",
)


# --------------------------------------------------
def validate_google_credentials() -> None:
    """Valida que GOOGLE_CREDENTIALS sea un JSON de service account completo.

    Raises:
        ValidationError: Si falta la variable, no es JSON válido o no
            tiene los campos mínimos requeridos por Google Auth.
    """
    credentials_json: Optional[str] = settings.GOOGLE_CREDENTIALS
    if not credentials_json:
        raise ValidationError(
            "Falta GOOGLE_CREDENTIALS en el archivo .env "
            "(credenciales de la service account de Google)."
        )
    try:
        credentials: dict[str, Any] = json.loads(credentials_json)
    except ValueError as exc:
        raise ValidationError(
            "GOOGLE_CREDENTIALS no es un JSON válido. Pegue el contenido "
            "completo del archivo JSON de la service account."
        ) from exc
    missing: list[str] = [
        key for key in REQUIRED_CREDENTIAL_KEYS if key not in credentials
    ]
    if missing:
        raise ValidationError(
            f"GOOGLE_CREDENTIALS incompleto: faltan los campos "
            f"{', '.join(missing)}. Pegue el JSON completo de la service "
            f"account (descargado desde Google Cloud -> IAM -> Service "
            f"Accounts -> Keys)."
        )


# --------------------------------------------------
def normalize_header(header: object) -> str:
    """Normaliza un header de columna para compararlo con los alias.

    Convierte a minúsculas, quita acentos y reemplaza espacios y
    puntos por guiones bajos.

    Args:
        header: Nombre original de la columna (cualquier tipo).

    Returns:
        Clave normalizada en ``snake_case``.
    """
    text: str = str(header).strip().lower()
    # Quitar tildes: "Ejercicio" -> "ejercicio", "código" -> "codigo"
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    text = text.replace("ñ", "n")
    text = "".join("_" if char in " .-" else char for char in text)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


# --------------------------------------------------
def map_columns(df: pd.DataFrame) -> dict[str, str]:
    """Mapea cada campo del modelo a la columna real de la hoja.

    Args:
        df: DataFrame leído desde Google Sheets.

    Returns:
        Diccionario ``{campo_modelo: columna_origen}``.

    Raises:
        ValidationError: Si alguna columna obligatoria no pudo resolverse.
            El mensaje incluye los headers reales de la hoja para poder
            ajustar los alias.
    """
    normalized_headers: dict[str, str] = {
        normalize_header(column): column for column in df.columns
    }
    column_map: dict[str, str] = {}
    missing_fields: list[str] = []

    for field, aliases in FIELD_ALIASES.items():
        matched_column: Optional[str] = None
        for alias in aliases:
            if alias in normalized_headers:
                matched_column = normalized_headers[alias]
                break
        if matched_column is None:
            # Fallback: coincidencia por prefijo (ej. "cod_barrio (sgv)")
            for normalized, original in normalized_headers.items():
                if any(normalized.startswith(alias) for alias in aliases):
                    matched_column = original
                    break
        if matched_column is None:
            missing_fields.append(field)
        else:
            column_map[field] = matched_column

    if missing_fields:
        available: str = ", ".join(repr(column) for column in df.columns)
        raise ValidationError(
            f"No se encontraron columnas para los campos: "
            f"{', '.join(missing_fields)}. Headers disponibles en la hoja: "
            f"{available}. Agregue los alias faltantes en FIELD_ALIASES."
        )
    return column_map


# --------------------------------------------------
def clean_text(value: Any) -> str:
    """Convierte un valor de celda a ``str`` sin ``NaN``/``None``.

    Args:
        value: Valor crudo de la celda.

    Returns:
        Texto recortado; cadena vacía para valores nulos.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        # pd.isna puede fallar con listas/dicts; se trata como texto.
        pass
    return str(value).strip()


# --------------------------------------------------
def format_cod_barrio(value: Any) -> str:
    """Normaliza el código de barrio a ``str`` de 4 dígitos con ``zeros``.

    Google Sheets/pandas suele traer códigos numéricos como ``884.0`` o
    ``"884.0"``; se convierten a entero y se rellenan con ceros a la
    izquierda hasta 4 dígitos (``"884"`` -> ``"0884"``).

    Args:
        value: Valor crudo de la celda.

    Returns:
        Cadena de exactamente 4 dígitos con leading zeros; cadena vacía
        para valores nulos. Los valores no numéricos se devuelven tal
        cual (recortados) y los mayores a 4 dígitos no se truncan.
    """
    text: str = clean_text(value)
    if not text:
        return ""
    # pandas convierte columnas numéricas a float: "884.0" -> "884".
    try:
        number: float = float(text.replace(",", "."))
    except ValueError:
        # Valor no numérico: se respeta tal cual (la validación del
        # modelo/UI se encarga de rechazarlo si aplica).
        return text
    if not number.is_integer() or number < 0:
        return text
    return str(int(number)).zfill(4)


# --------------------------------------------------
def parse_ejercicio(value: object) -> int:
    """Convierte la celda de ejercicio a ``int``.

    Args:
        value: Valor crudo (``2024``, ``"2024"``, ``2024.0``...).

    Returns:
        Ejercicio como entero.

    Raises:
        ValidationError: Si el valor no es numérico.
    """
    text: str = clean_text(value)
    try:
        return int(float(text.replace(",", ".")))
    except ValueError as exc:
        raise ValidationError(f"Ejercicio inválido: {value!r}") from exc


# --------------------------------------------------
def build_documents(
    df: pd.DataFrame, column_map: dict[str, str]
) -> list[dict[str, Any]]:
    """Valida y construye los documentos a enviar a la API.

    Args:
        df: DataFrame crudo de la hoja.
        column_map: Mapeo ``campo_modelo -> columna_origen``.

    Returns:
        Lista de documentos (dicts) listos para ``POST``.

    Raises:
        ValidationError: Si hay filas inválidas; el mensaje detalla
            fila y motivo de cada una (todo-o-nada, no se envía nada).
    """
    documents: list[dict[str, Any]] = []
    errors: list[str] = []
    skipped_empty: int = 0

    for position, (_, row) in enumerate(df.iterrows(), start=2):
        # La fila 1 de la hoja son los headers (start=2 = fila real).
        raw_values: dict[str, Any] = {
            field: row[column] for field, column in column_map.items()
        }
        # Descartar filas sin datos de negocio: vacías o con valores
        # ajenos al modelo (ej. una celda "$0,00" residual al final de
        # la hoja). Sin ejercicio/identificador/estructura/notas la fila
        # no puede convertirse en un documento atribuible.
        if all(
            clean_text(raw_values[field]) == ""
            for field in REQUIRED_FIELDS
            if field != "importe"
        ):
            skipped_empty += 1
            continue

        try:
            report = ObrasRecuperadasReport(
                ejercicio=parse_ejercicio(raw_values["ejercicio"]),
                cod_barrio=format_cod_barrio(raw_values["cod_barrio"]),
                estructura=clean_text(raw_values["estructura"]),
                importe=parse_moneda_ar(raw_values["importe"]),
                notas=clean_text(raw_values["notas"]),
            )
        except ValidationError as exc:
            errors.append(f"  Fila {position}: {exc}")
            continue
        except AppBaseException as exc:
            errors.append(f"  Fila {position}: {exc}")
            continue
        except Exception as exc:  # pydantic.ValidationError u otros
            errors.append(f"  Fila {position}: {exc}")
            continue

        document: dict[str, Any] = report.model_dump()
        # El endpoint add_many no requiere id: MongoDB lo genera al
        # insertar el documento en la colección.
        documents.append(document)

    if skipped_empty:
        print(
            f"⚠️  {skipped_empty} fila(s) descartadas por estar vacías o sin "
            f"datos de negocio (ejercicio/identificador/estructura/notas "
            f"en blanco)."
        )
    if errors:
        details: str = "\n".join(errors[:20])
        extra: str = (
            f"\n  ... y {len(errors) - 20} errores más" if len(errors) > 20 else ""
        )
        raise ValidationError(
            f"{len(errors)} fila(s) inválidas; no se envió nada:\n{details}{extra}"
        )
    if not documents:
        raise ValidationError("La hoja no contiene filas con datos.")
    return documents


# --------------------------------------------------
def group_by_ejercicio(
    documents: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Agrupa los documentos por ``ejercicio``.

    El endpoint ``POST /sgv/obrasRecuperadas`` borra/reemplaza por
    ejercicio, por lo que cada grupo debe enviarse en un POST propio.

    Args:
        documents: Documentos validados.

    Returns:
        Diccionario ``{ejercicio: [documentos]}``.
    """
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        groups[int(document["ejercicio"])].append(document)
    return dict(groups)


# --------------------------------------------------
def upload_groups(
    groups: dict[int, list[dict[str, Any]]], token: str
) -> list[dict[str, Any]]:
    """Emit un POST por grupo de ejercicio contra la API.

    Args:
        groups: Documentos agrupados por ejercicio.
        token: JWT de autenticación.

    Returns:
        Lista de respuestas de la API (una por grupo).

    Raises:
        APIConnectionError: Sin conexión con la API.
        APIResponseError: Si la API responde con error.
    """
    responses: list[dict[str, Any]] = []
    for ejercicio in sorted(groups):
        payload: list[dict[str, Any]] = groups[ejercicio]
        print(
            f"⬆️  POST {ENDPOINT} -> ejercicio {ejercicio} "
            f"({len(payload)} documentos)..."
        )
        response = post_request(ENDPOINT, json_body=payload, token=token)
        responses.append(response)
        print(f"   Respuesta: {response}")
    return responses


# --------------------------------------------------
def verify_upload(token: str) -> None:
    """Consulta la colección y muestra el conteo por ejercicio.

    Args:
        token: JWT de autenticación.
    """
    records: list[dict[str, Any]] = fetch_data(ENDPOINT, token=token)
    counts: dict[int, int] = defaultdict(int)
    for record in records:
        counts[int(record.get("ejercicio", 0))] += 1
    print(f"\n🔍 Verificación: {len(records)} documento(s) en la colección")
    for ejercicio in sorted(counts):
        print(f"   - ejercicio {ejercicio}: {counts[ejercicio]} documento(s)")


# --------------------------------------------------
def get_args() -> Any:
    """Parsea los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description=(
            "Importa la hoja 'Obras Recuperadas' del Google Sheet a "
            "MongoDB (/sgv/obrasRecuperadas) agrupando por ejercicio."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "spreadsheet_key",
        nargs="?",
        default=SPREADSHEET_KEY,
        help="Clave del Google Sheet (URL entre /d/ y /edit)",
    )
    parser.add_argument(
        "-w",
        "--wks_name",
        default=WORKSHEET_NAME,
        help="Nombre de la hoja (worksheet)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lee y valida sin enviar nada a la API",
    )
    return parser.parse_args()


# --------------------------------------------------
def main() -> None:
    """Flujo completo: leer hoja -> validar -> agrupar -> subir -> verificar."""
    args = get_args()

    validate_google_credentials()

    print(f"📄 Leyendo hoja '{args.wks_name}' del Google Sheet...")
    try:
        gs = GoogleSheets()
        df: pd.DataFrame = gs.from_google_sheets(
            spreadsheet_key=args.spreadsheet_key, wks_name=args.wks_name
        )
    except gspread.exceptions.GSpreadException as exc:
        raise ValidationError(
            f"No se pudo leer la hoja de Google: {exc}. Verifique que la "
            f"service account tenga la hoja compartida (permiso Lector/Editor)."
        ) from exc
    if df.empty:
        raise ValidationError("La hoja está vacía.")

    column_map: dict[str, str] = map_columns(df)
    print(f"🧭 Mapeo de columnas: {column_map}")

    documents: list[dict[str, Any]] = build_documents(df, column_map)
    groups: dict[int, list[dict[str, Any]]] = group_by_ejercicio(documents)
    print(
        f"✅ {len(documents)} documento(s) válidos agrupados en "
        f"{len(groups)} ejercicio(s): "
        f"{', '.join(str(ej) for ej in sorted(groups))}"
    )

    if args.dry_run:
        print("\n--- DRY RUN (no se envió nada) ---")
        for ejercicio in sorted(groups):
            print(f"\nEjercicio {ejercicio} ({len(groups[ejercicio])} docs):")
            for document in groups[ejercicio][:3]:
                print(f"  {document}")
            if len(groups[ejercicio]) > 3:
                print(f"  ... y {len(groups[ejercicio]) - 3} más")
        return

    print("🔐 Autenticando contra la API...")
    token: str = login(settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD)

    upload_groups(groups, token)
    try:
        verify_upload(token)
    except APIResponseError as exc:
        # No se silencia el error: se informa, pero la carga ya se
        # completó (el endpoint GET de esta colección puede estar
        # fallando del lado del servidor con 500).
        print(
            f"⚠️  No se pudo verificar el conteo final: {exc}",
            file=sys.stderr,
        )
    print("\n🎉 Migración completada.")


# --------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except AuthenticationError as exc:
        print(f"❌ Autenticación fallida: {exc}", file=sys.stderr)
        sys.exit(1)
    except (APIConnectionError, APIResponseError) as exc:
        print(f"❌ Error de API: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValidationError as exc:
        print(f"❌ Error de validación: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"❌ Error de configuración: {exc}", file=sys.stderr)
        sys.exit(1)
    except AppBaseException as exc:
        print(f"❌ Error inesperado de la aplicación: {exc}", file=sys.stderr)
        sys.exit(1)

# poetry run python -m migration.migrate_obras_recuperadas --dry-run
# poetry run python -m migration.migrate_obras_recuperadas
