"""Vista y formulario de inicio de sesión y registro de usuarios."""

import streamlit as st

import utils.exceptions as ex
from services.auth_service import get_current_user, login, register
from services.data_fetcher import get_referencias_factureros, get_referencias_honorarios
from utils.context import set_token
from views.aux_tables import report_data_version_key


# --------------------------------------------------
def render_login() -> None:
    """Renderiza el formulario de login y registro de forma compacta y centrada."""
    # Ocultar la barra lateral completamente durante la pantalla de login
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {
                display: none !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _, col, _ = st.columns([1, 2, 1])

    with col:
        st.title("Acceso a Planillometro INVICO")

        tab_login, tab_register = st.tabs(["🔒 Iniciar Sesión", "📝 Registrarse"])

        with tab_login:
            st.info("Ingrese sus credenciales para continuar.")
            with st.form("login_form"):
                username = st.text_input("Usuario", key="login_username").strip()
                password = st.text_input(
                    "Contraseña", type="password", key="login_password"
                )
                submitted = st.form_submit_button("Ingresar", width="stretch")

                if submitted:
                    if not username or not password:
                        st.error("Por favor complete todos los campos.")
                    else:
                        try:
                            with st.spinner("Autenticando en el Sistema..."):
                                token = login(username, password)

                            st.session_state["token"] = token
                            set_token(token)  # Propagar al contexto de servicios

                            with st.spinner("Cargando perfil de usuario..."):
                                user_data = get_current_user(token)

                            st.session_state["user"] = {
                                "role": user_data.role.value,
                                "username": user_data.username,
                                "id": user_data.id,
                            }

                            with st.status(
                                "Preparando Planillometro ICARO...", expanded=True
                            ) as status:
                                st.write("Sincronizando Referencias de Factureros...")
                                data_version_key = report_data_version_key(
                                    "precarizados"
                                )
                                if data_version_key not in st.session_state:
                                    st.session_state[data_version_key] = 0
                                honorarios_key = "honorarios_dataframes_iteration"
                                if honorarios_key not in st.session_state:
                                    st.session_state[honorarios_key] = 0
                                get_referencias_factureros(
                                    update_trigger=st.session_state[data_version_key]
                                )
                                st.write("Sincronizando Referencias de Honorarios...")
                                get_referencias_honorarios(
                                    update_trigger=st.session_state[honorarios_key]
                                )
                                status.update(
                                    label="Sincronización Completa",
                                    state="complete",
                                    expanded=False,
                                )
                            st.rerun()

                        except ex.AuthenticationError as exc:
                            st.error(f"🔒 {exc}")
                        except ex.APIConnectionError as exc:
                            st.error(f"🌐 {exc}")
                        except ex.AppBaseException as exc:
                            st.error(f"⚠️ {exc}")
                        except Exception as exc:
                            st.error(f"❌ Ocurrió un error inesperado: {exc}")

        with tab_register:
            st.info("Complete los datos para crear una nueva cuenta.")

            st.markdown(
                """
                💡 **Recomendación:** Se sugiere utilizar el **mismo usuario** que utiliza
                en los otros sistemas de **INVICO** (ej. `jperez`). La **contraseña** debe tener
                **al menos 4 caracteres**.
                """
            )
            with st.form("register_form"):
                new_user = st.text_input(
                    "Usuario deseado",
                    key="reg_username",
                    placeholder="Ej: jperez",
                    help="Se recomienda usar tu usuario estándar de INVICO.",
                ).strip()
                new_pass = st.text_input(
                    "Contraseña",
                    type="password",
                    key="reg_password",
                    help="Mínimo 4 caracteres.",
                )
                conf_pass = st.text_input(
                    "Confirmar Contraseña", type="password", key="reg_confirm"
                )
                submitted_reg = st.form_submit_button("Crear Cuenta", width="stretch")

                if submitted_reg:
                    if not new_user or not new_pass:
                        st.error("Todos los campos son obligatorios.")
                    elif len(new_pass) < 4:
                        st.error("⚠️ La contraseña debe tener al menos 4 caracteres.")
                    elif new_pass != conf_pass:
                        st.error("Las contraseñas no coinciden.")
                    else:
                        with st.spinner("Registrando usuario en el servidor..."):
                            try:
                                register(new_user, new_pass)
                                st.success(
                                    "✅ Registro solicitado exitosamente. "
                                    "Ahora puede iniciar sesión con sus credenciales."
                                )
                            except ex.APIConnectionError as exc:
                                st.error(f"🌐 {exc}")
                            except ex.AppBaseException as exc:
                                st.error(f"⚠️ {exc}")
                            except Exception as exc:
                                st.error(f"❌ Error inesperado: {exc}")


if __name__ == "__main__":
    render_login()
