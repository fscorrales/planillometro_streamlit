"""Módulo de utilidades para obtener la versión de la aplicación."""

from pathlib import Path
import sys
import tomllib


def get_version() -> str:
    """
    Obtiene la versión del proyecto definida en pyproject.toml.
    Compatible tanto en desarrollo como en ejecutable empaquetado (PyInstaller).
    """
    if getattr(sys, "frozen", False):
        # Si la app está empaquetada, PyInstaller define _MEIPASS
        base_path = Path(sys._MEIPASS)
    else:
        # En desarrollo: utils/version.py -> utils -> raíz del proyecto (2 niveles)
        base_path = Path(__file__).resolve().parent.parent

    path = base_path / "pyproject.toml"

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
            # Compatible con PEP 621 ([project]) y Poetry clásico ([tool.poetry])
            version = (
                data.get("project", {}).get("version")
                or data.get("tool", {}).get("poetry", {}).get("version")
            )
            if version:
                return str(version)
            return "0.0.0-desconocida"
    except (FileNotFoundError, OSError):
        return "0.0.0-desconocida"


if __name__ == "__main__":
    # Permite ejecutar: poetry run python -m utils.version
    print(get_version())
