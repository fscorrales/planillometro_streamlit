"""Endpoints de la API de INVICO Slave."""

__all__ = ["Endpoints"]

from enum import Enum


# --------------------------------------------------
class Endpoints(str, Enum):
    """URLs de los endpoints disponibles en la API de Koyeb."""

    SLAVE_FACTUREROS = "/slave/factureros"
    SLAVE_FACTUREROS_ACTIVIDADES = "/slave/factureros/actividades"
    SLAVE_FACTUREROS_PARTIDAS = "/slave/factureros/partidas"
    SLAVE_HONORARIOS = "/slave/honorarios"
    SLAVE_HONORARIOS_CTAS_CTES = "/slave/honorarios/ctasCtes"
    SLAVE_HONORARIOS_TIPOS_COMPROBANTES = "/slave/honorarios/tiposComprobantes"
