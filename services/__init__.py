"""Services module."""

from services.api import (
    delete_request,
    fetch_dataframe,
    fetch_excel_stream,
    post_request,
    put_request,
)
from services.data_fetcher import (
    get_ejercicios_list,
    get_honorarios,
    get_obras_recuperadas,
    get_referencias_factureros,
    get_referencias_honorarios,
    sincronizar_caches,
)

__all__ = [
    "fetch_dataframe",
    "fetch_excel_stream",
    "post_request",
    "put_request",
    "delete_request",
    "get_obras_recuperadas",
    "get_referencias_factureros",
    "get_referencias_honorarios",
    "get_ejercicios_list",
    "get_honorarios",
    "sincronizar_caches",
]
