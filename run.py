import importlib
import os
import sys

from streamlit.web import cli as stcli

# --------------------------------------------------
def get_resource_path(relative_path):
    try:
        # Ruta temporal de PyInstaller
        base_path = sys._MEIPASS
    except Exception:
        # Ruta en modo desarrollo
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# --------------------------------------------------
def run_streamlit_app():
    # --- TRUCO PARA EL CONFIG.TOML ---
    # Si detectamos que estamos en el entorno compilado de PyInstaller,
    # forzamos a Streamlit a leer la carpeta de configuración interna.
    if hasattr(sys, "_MEIPASS"):
        prod_config_dir = get_resource_path(".streamlit")
        os.environ["STREAMLIT_CONFIG_DIR"] = prod_config_dir
    # Buscamos app.py dentro de la carpeta temporal del ejecutable
    app_path = get_resource_path("app.py")

    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",  # <-- Esto desactiva el envío de estadísticas
    ]

    # TRUCO EXTRA: Forzar el modo "headless" en la configuración
    from streamlit import config

    config.set_option("browser.gatherUsageStats", False)

    sys.exit(stcli.main())

# --------------------------------------------------
if __name__ == "__main__":
    # 🔥 INTERCEPCIÓN GENÉRICA PARA MÚLTIPLES RUNNERS
    if len(sys.argv) > 1 and sys.argv[1] == "--automation":
        # 1. Removemos el flag '--automation' de su posición original (índice 1)
        sys.argv.pop(1)

        # Ahora sys.argv es: [0: "INVICO.exe", 1: "src.automation.sscc...", 2: "username", ...]
        # 2. El nombre del módulo real quedó en el índice 1
        if len(sys.argv) > 1:
            target_module = sys.argv.pop(
                1
            )  # 🚀 EXTRAEMOS EL ÍNDICE 1 (El string del módulo)

            try:
                print(f"📦 Cargando de forma dinámica el módulo: {target_module}")
                modulo_runner = importlib.import_module(target_module)

                # Ejecuta la función run() de ese runner
                modulo_runner.run()
                sys.exit(0)
            except Exception as e:
                print(f"\n❌ ERROR CRÍTICO EN EL ARRANQUE DEL RUNNER:\n{e}")
                import traceback

                traceback.print_exc()
                input("\nPresioná Enter para cerrar la ventana...")
                sys.exit(1)
        else:
            print(
                "❌ Error: Se especificó '--automation' pero no se indicó qué módulo ejecutar."
            )
            sys.exit(1)

    # Si no tiene el flag, arranca Streamlit normalmente
    run_streamlit_app()