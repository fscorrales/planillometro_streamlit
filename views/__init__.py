"""Módulo de páginas de la aplicación Streamlit."""

from views.aux_tables import (
    ReportState,
    dataframe_with_buttons,
    params_preparation,
    report_data_version_key,
    report_filter_key,
    report_header,
    report_selections_key,
    report_template,
)
from views.modals import modal_delete_registro_gral, modal_honorarios, modal_precarizado

__all__ = [
    "ReportState",
    "report_header",
    "report_template",
    "report_filter_key",
    "report_selections_key",
    "report_data_version_key",
    "dataframe_with_buttons",
    "params_preparation",
    "modal_delete_registro_gral",
    "modal_honorarios",
    "modal_precarizado",
]
