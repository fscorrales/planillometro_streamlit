"""Módulo centralizado de excepciones para la aplicación INVICO.

Este módulo define la jerarquía de errores personalizados para asegurar un
manejo de errores coherente en toda la aplicación (servicios, views y pages).
"""

__all__ = [
    "AppBaseException",
    "APIConnectionError",
    "APIResponseError",
    "AuthenticationError",
    "ValidationError",
]


# --------------------------------------------------
class AppBaseException(Exception):
    """Clase base para todas las excepciones de la aplicación."""

    pass


# --------------------------------------------------
class APIConnectionError(AppBaseException):
    """Error de conexión con el servidor (timeout, DNS, etc.)."""

    pass


# --------------------------------------------------
class APIResponseError(AppBaseException):
    """Error en la respuesta del servidor (status codes no exitosos)."""

    pass


# --------------------------------------------------
class AuthenticationError(AppBaseException):
    """Error relacionado con la autenticación o permisos (401, 403, 404)."""

    pass


# --------------------------------------------------
class ValidationError(AppBaseException):
    """Error de validación de datos en el cliente o respuesta inesperada."""

    pass
