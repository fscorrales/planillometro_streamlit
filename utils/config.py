"""Módulo de configuración general de la aplicación."""

import os
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL: str = os.getenv(
    "API_BASE_URL", os.getenv("BASE_URL", "https://fixed-marita-invico-d13e43fa.koyeb.app")
)
DEFAULT_TIMEOUT: float = float(os.getenv("DEFAULT_TIMEOUT", "60.0"))
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")


class Settings:
    """Configuraciones del sistema."""

    BASE_URL: str = API_BASE_URL
    DEFAULT_TIMEOUT: float = DEFAULT_TIMEOUT
    ADMIN_USERNAME: str = ADMIN_USERNAME
    ADMIN_PASSWORD: str = ADMIN_PASSWORD


settings = Settings()
