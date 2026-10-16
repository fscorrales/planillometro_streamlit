import os
import shutil

import PyInstaller.__main__

# --- CONFIGURACIÓN ---
APP_NAME = "Planillometro"
ENTRY_POINT = "run.py"
STREAMLIT_APP = "app.py"
STREAMLIT_CONFIG = ".streamlit"
ICON_FILE = "app_icon.ico"

# Paquetes locales de la app. PyInstaller sólo analiza run.py (app.py entra
# como dato), así que hay que forzar su inclusión: los módulos van al PYZ y,
# de paso, se descubren sus dependencias de terceros (pydantic, dotenv,
# openpyxl, rich...).
LOCAL_PACKAGES = ["views", "components", "models", "services", "utils"]


def build() -> None:
    # 1. Limpiar carpetas de compilaciones previas
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except OSError as exc:
                raise SystemExit(
                    f"No se pudo borrar '{folder}': {exc}. "
                    "¿Seguí el Planillometro.exe de una compilación anterior corriendo?"
                ) from exc
            print(f"Borrando {folder}...")

    # 2. Definir los argumentos de PyInstaller
    args = [
        ENTRY_POINT,
        f"--name={APP_NAME}",
        "--onefile",
        "--clean",
        # "--windowed",  # Requiere consola: run.py usa print/input en --automation
        # Recolección de librerías "rebeldes"
        "--collect-all=streamlit",
        "--collect-all=httpx",
        "--copy-metadata=streamlit",
        # Archivos en disco que se leen en tiempo de ejecución
        f"--add-data={STREAMLIT_APP}{os.pathsep}.",
        f"--add-data={STREAMLIT_CONFIG}{os.pathsep}.streamlit",
        f"--add-data=pyproject.toml{os.pathsep}.",
        f"--icon={ICON_FILE}",
    ]

    # 3. Código local: submódulos al PYZ (analiza sus dependencias 3ª) ...
    for package in LOCAL_PACKAGES:
        args.append(f"--collect-submodules={package}")

    # ... y los .py de views en disco, porque st.Page() los abre y compila
    # desde el disco (streamlit/navigation/page.py is_file() + ScriptCache).
    args.append(f"--add-data=views{os.pathsep}views")

    # 4. Ejecutar PyInstaller
    print(f"Iniciando compilación de {APP_NAME}...")
    PyInstaller.__main__.run(args)
    print("\n¡Compilación finalizada! Revisa la carpeta /dist")


if __name__ == "__main__":
    build()

# poetry run python compile.py
