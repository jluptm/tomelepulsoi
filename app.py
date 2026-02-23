import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import uuid
from datetime import datetime, timedelta
import os
import streamlit_antd_components as sac
import random
import asyncio
import urllib.parse

from db_manager import (
    get_churches, add_church, update_church, 
    register_respondent, authenticate_respondent, save_responses, get_respondent_responses,
    get_church_results, add_campaign, get_campaign_by_token, 
    get_church_stats, get_campaigns_by_church, get_all_users_summary, get_all_detailed_responses,
    get_username_by_whatsapp, generate_recovery_code, verify_recovery_code, reset_password_with_code,
    get_church_comments, update_user_extension
)
from survey_config import SURVEY_QUESTIONS
from whatsapp_service import WhatsAppService
from whatsapp_sender import send_whatsapp_message_async

st.set_page_config(page_title="Tómale el pulso a la iglesia", layout="wide", page_icon="assets/favicon.png")

# --- UI Styles ---
st.markdown("""
<style>
    .stTextArea textarea { height: 100px; }
    .main-header { font-size: 2.8rem; font-weight: bold; color: #1E88E5; margin-bottom: 10px; }
    .sub-header { font-size: 1.5rem; color: #555; margin-bottom: 20px; }
    .admin-key { color: #f44336; font-family: monospace; }
    .stat-card {
        background-color: #f8f9fa;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #1E88E5;
        margin-bottom: 20px;
    }
    .logo-img { display: block; margin-left: auto; margin-right: auto; width: 120px; border-radius: 20px; }
    .stImage img { border-radius: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); border: 2px solid #1E88E5; }
    .plus-button-col { display: flex; align-items: flex-end; padding-bottom: 5px; }
    .auth-container { padding: 20px; background-color: #f0f2f6; border-radius: 10px; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

LOGO_PATH = "assets/logo.png"

# --- Routing Logic ---
query_params = st.query_params
token = query_params.get("t")
current_church_name = ""
campaign_data = None
church_info = None

if token:
    campaign_data = get_campaign_by_token(token)
    if campaign_data:
        all_churches = get_churches()
        # campaign_data: id, church_id, token, scenario, deadline, is_active
        church_info = next((c for c in all_churches if c[0] == campaign_data[1]), None)
        if church_info:
            current_church_name = church_info[1]

# --- Session State ---
if 'custom_ministries_count' not in st.session_state:
    st.session_state.custom_ministries_count = 1
if 'user' not in st.session_state:
    st.session_state.user = None # Holds the user row tuple
if 'responses_loaded' not in st.session_state:
    st.session_state.responses_loaded = False
if 'response_cache' not in st.session_state:
    st.session_state.response_cache = {} # Map (area_id, q_id) -> (score, comment)
if 'recovery_mode' not in st.session_state:
    st.session_state.recovery_mode = None # 'username' or 'password'
if 'recovery_step' not in st.session_state:
    st.session_state.recovery_step = 1

# --- Services ---
wa_token = st.secrets["wasender"]["API_KEY"]
wa_service = WhatsAppService(wa_token)

# --- Header ---
col1, col2 = st.columns([1.5, 5])
with col1:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=220)
with col2:
    st.markdown("<div class='main-header'>Tómale el pulso a la iglesia</div>", unsafe_allow_html=True)
    if current_church_name:
        user_header = ""
        if st.session_state.user:
            # st.session_state.user index 4 is the name
            u_name = st.session_state.user[4]
            user_header = f" &nbsp; | &nbsp; 👤 {u_name}"
        st.markdown(f"<div class='sub-header'>🏛️ {current_church_name}{user_header}</div>", unsafe_allow_html=True)

# --- Helper Functions ---
def is_admin():
    return st.session_state.get('admin_authenticated', False)

def check_deadline(deadline_str):
    if not deadline_str: return True
    try:
        deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
        return datetime.now() <= deadline + timedelta(days=1)
    except:
        return True

def format_db_date(date_str):
    if not date_str: return "N/A"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m/%d/%Y")
    except:
        return date_str

def format_whatsapp(phone):
    if not phone: return ""
    # Dejar solo los dígitos
    digits = "".join(filter(str.isdigit, str(phone)))
    # Eliminar el 0 inicial del código de área si detectamos patrón de móvil después del país
    # Ejem Argentina: 54 9 011 -> 54 9 11
    if digits.startswith("5490"):
        digits = "549" + digits[4:]
    elif digits.startswith("0"): # Caso número local ingresado con 0
        digits = digits[1:]
    
    return "+" + digits

def render_report_visuals(results, title):
    if not results:
        st.info(f"No hay suficientes datos para: {title}")
        return
    
    area_names_map = {id: SURVEY_QUESTIONS[id]["title"] for id in SURVEY_QUESTIONS}
    df = pd.DataFrame(results, columns=["area_id", "avg_score"])
    df["area_name"] = df["area_id"].map(area_names_map).sort_index()
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Radar Chart
        fig_radar = px.line_polar(df, r='avg_score', theta='area_name', line_close=True, range_r=[0,10])
        levels = [2, 4, 6, 8, 10]
        ring_colors = ['red', 'orange', 'yellow', 'green', 'blue']
        theta_closed = list(df['area_name']) + [df['area_name'].iloc[0]]
        
        for r_lvl, color in zip(levels, ring_colors):
            fig_radar.add_trace(go.Scatterpolar(
                r=[r_lvl] * len(theta_closed),
                theta=theta_closed,
                mode='lines',
                line=dict(color=color, width=1.5, dash='solid'),
                showlegend=False,
                hoverinfo='none'
            ))

        fig_radar.data[0].update(fill='toself', fillcolor='rgba(31, 119, 180, 0.3)')
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 10], showgrid=False, tickmode='array', tickvals=levels, gridcolor='rgba(0,0,0,0)'),
                angularaxis=dict(showgrid=True, gridcolor='lightgrey')
            ),
            showlegend=False,
            title=f"Radial: {title}",
            height=500
        )
        st.plotly_chart(fig_radar, width='stretch')
    
    with col2:
        # Horizontal Bar Chart
        df_sorted = df.sort_values(by="avg_score", ascending=True)
        fig_bar = px.bar(df_sorted, x='avg_score', y='area_name', orientation='h',
                         range_x=[0, 10], color='avg_score',
                         color_continuous_scale='RdYlGn',
                         labels={'avg_score': 'Puntaje Promedio', 'area_name': 'Área'})
        fig_bar.update_layout(
            title=f"Barras: {title}",
            height=500,
            coloraxis_showscale=False
        )
        st.plotly_chart(fig_bar, width='stretch')
    
    with st.expander("📋 Ver Tabla de Datos", expanded=False):
        st.table(df[["area_name", "avg_score"]].rename(columns={"area_name": "Área", "avg_score": "Promedio"}))

def show_enhanced_reports(church_id, church_name):
    st.header(f"📈 Reporte de Diagnóstico: {church_name}")
    stats = get_church_stats(church_id)
    
    col1, col2 = st.columns([2, 3])
    with col1:
        st.markdown("<div class='stat-card'>", unsafe_allow_html=True)
        st.subheader("👥 Participación por Rol")
        if stats['roles']:
            role_df = pd.DataFrame(list(stats['roles'].items()), columns=["Rol", "Cantidad"])
            fig_roles = px.pie(role_df, values="Cantidad", names="Rol", hole=0.4,
                               color_discrete_sequence=px.colors.qualitative.Safe)
            fig_roles.update_layout(showlegend=True, margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_roles, width='stretch')
        else:
            st.info("Sin datos de participación")
        st.markdown("</div>", unsafe_allow_html=True)
        
    with col2:
        st.markdown("<div class='stat-card'>", unsafe_allow_html=True)
        st.subheader("📅 Meta-Data")
        if stats['date_range'][0]:
            st.write(f"**Inicio:** {format_db_date(stats['date_range'][0])}")
            st.write(f"**Fin:** {format_db_date(stats['date_range'][1])}")
            st.metric("Total de encuestas", sum(stats['roles'].values()))
        else:
            st.info("No hay fechas registradas")
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("🛡️ Visión de Pastores", expanded=False):
        render_report_visuals(get_church_results(church_id, 'pastor'), "Solo Pastores")
    with st.expander("👥 Visión de Liderazgo y Membresía", expanded=False):
        render_report_visuals(get_church_results(church_id, 'non-pastor'), "Líderes y Miembros")
    with st.expander("🌐 Visión Consolidada (Global)", expanded=True):
        render_report_visuals(get_church_results(church_id, 'all'), "Total Iglesia")

    # --- Area Comments Section ---
    st.markdown("---")
    st.subheader("💬 Comentarios por Área")
    all_comments = get_church_comments(church_id)
    
    for a_id in sorted(SURVEY_QUESTIONS.keys()):
        area = SURVEY_QUESTIONS[a_id]
        area_comments = [c for c in all_comments if c[0] == a_id]
        
        with st.expander(f"{area.get('icon','')} {area['title']} ({len(area_comments)})", expanded=False):
            if area_comments:
                comment_data = []
                for c in area_comments:
                    try:
                        # Defensive check: indices 0:area_id, 1:question_id, 2:user_name, 3:role, 4:score, 5:comment
                        if isinstance(c[1], (int, float)) or (isinstance(c[1], str) and str(c[1]).isdigit()):
                            rel_q = int(c[1])
                            score_val = c[4]
                            comment_val = c[5]
                        else:
                            # Old structure fallback: 0:area_id, 1:user_name, 2:role, 3:score, 4:comment
                            rel_q = "N/A"
                            score_val = c[3]
                            comment_val = c[4]

                        comment_data.append({
                            "# Q": rel_q,
                            "Puntaje": score_val,
                            "Comentario": comment_val
                        })
                    except:
                        continue
                
                if comment_data:
                    df = pd.DataFrame(comment_data)
                    # Sort by question number. Handle 'N/A' by placing them at the end.
                    df['# Q_numeric'] = pd.to_numeric(df['# Q'], errors='coerce')
                    df = df.sort_values(by='# Q_numeric').drop(columns=['# Q_numeric'])
                    
                    def style_odd_rows(row):
                        try:
                            # Use row name (index) if needed, but here we check the # Q value
                            q_val = row["# Q"]
                            if isinstance(q_val, (int, float)) and int(q_val) % 2 != 0:
                                return ['background-color: rgba(30, 136, 229, 0.05)'] * len(row)
                        except:
                            pass
                        return [''] * len(row)
                    
                    st.dataframe(df.style.apply(style_odd_rows, axis=1), width='stretch')
                else:
                    st.info("No hay comentarios válidos para esta área.")
            else:
                st.info("No hay comentarios para esta área.")

def login_form():
    st.subheader("Iniciar Sesión")
    with st.form("login"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary", width='stretch'):
            user = authenticate_respondent(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos")
    
    col_u, col_p = st.columns(2)
    with col_u:
        if st.button("Olvidé mi usuario", key="btn_forgot_user"):
            st.session_state.recovery_mode = 'username'
            st.session_state.recovery_step = 1
            st.rerun()
    with col_p:
        if st.button("Olvidé mi clave", key="btn_forgot_pwd"):
            st.session_state.recovery_mode = 'password'
            st.session_state.recovery_step = 1
            st.rerun()

def recovery_flow():
    st.subheader("Recuperación de Acceso")
    
    if st.session_state.recovery_mode == 'username':
        st.info("Paso 1: Ingrese su número de WhatsApp registrado para recibir su nombre de usuario.")
        whatsapp = st.text_input("Número de WhatsApp", placeholder="Ej: +54911...")
        if st.button("Enviar Usuario por WhatsApp", type="primary"):
            username = get_username_by_whatsapp(whatsapp)
            if username:
                if asyncio.run(wa_service.send_forgotten_username(whatsapp, username)):
                    st.success(f"Se ha enviado su nombre de usuario al WhatsApp {whatsapp}")
                else:
                    st.error("Error al enviar el mensaje. Intente más tarde.")
            else:
                st.error("No se encontró ningún usuario asociado a este número.")
        
    elif st.session_state.recovery_mode == 'password':
        if st.session_state.recovery_step == 1:
            st.info("Paso 1: Ingrese su usuario y WhatsApp para recibir un código de verificación.")
            user_rec = st.text_input("Usuario")
            whatsapp_rec = st.text_input("WhatsApp")
            if st.button("Generar Código", type="primary"):
                code = generate_recovery_code(user_rec, whatsapp_rec)
                if code:
                    if asyncio.run(wa_service.send_recovery_code(whatsapp_rec, code)):
                        st.session_state.temp_user = user_rec
                        st.session_state.recovery_step = 2
                        st.success("Código enviado. Revise su WhatsApp.")
                        st.rerun()
                    else:
                        st.error("Error al enviar el código.")
                else:
                    st.error("Los datos no coinciden con nuestros registros.")
                    
        elif st.session_state.recovery_step == 2:
            st.info(f"Paso 2: Ingrese el código enviado a su WhatsApp y su nueva clave para el usuario **{st.session_state.get('temp_user')}**.")
            code_in = st.text_input("Código de 6 dígitos")
            new_pass = st.text_input("Nueva Contraseña", type="password")
            if st.button("Restablecer Contraseña", type="primary"):
                if reset_password_with_code(st.session_state.temp_user, code_in, new_pass):
                    st.success("Contraseña actualizada exitosamente. Ya puede iniciar sesión.")
                    st.session_state.recovery_mode = None
                    st.session_state.recovery_step = 1
                    # No rerun yet, let them see success
                else:
                    st.error("Código inválido, expirado o ya utilizado.")

    if st.button("Volver al Login"):
        st.session_state.recovery_mode = None
        st.session_state.recovery_step = 1
        st.rerun()

def register_form():
    st.subheader("Registro de Nuevo Usuario")
    if current_church_name:
        st.info(f"Registrándose para: **{current_church_name}**")
    
    with st.form("register"):
        col_u, col_p = st.columns(2)
        with col_u: username = st.text_input("Crear Usuario (Único)", placeholder="Ej: juan.perez")
        with col_p: password = st.text_input("Crear Contraseña", type="password")
        
        st.markdown("---")
        st.markdown("**Datos del Perfil**")
        name = st.text_input("Nombre Completo")
        whatsapp = st.text_input("Número de WhatsApp")
        
        col_r, col_g, col_a = st.columns(3)
        with col_r: role = st.selectbox("Rol", ["Pastor", "Líder", "Miembro"])
        with col_g: gender = st.selectbox("Género", ["Masculino", "Femenino", "Otro"])
        with col_a: age_range = st.selectbox("Rango de Edad", ["< 18", "18-30", "31-50", "> 50"])

        # Limited ministries for register form simplicity (or full?)
        # Let's keep it simple here, maybe comma separated or multi-select?
        # Re-using the logic from main app is slightly complex inside a form.
        # Simplification: specific main ministries + text for others.
        basic_mins = st.multiselect("Ministerios principales", 
                                    ["Alabanza", "Damas", "Jóvenes", "Niños", "Cocina", "Protocolo", "Diáconos", "Familia", "Matrimonios", "Células"])
        other_mins = st.text_input("Otros Ministerios (separados por coma)")
        
        if st.form_submit_button("Registrarse y Entrar", type="primary", width='stretch'):
            if not username or not password or not name:
                st.error("Por favor complete los campos obligatorios")
            else:
                mins_combined = ", ".join(basic_mins)
                if other_mins: mins_combined += f", {other_mins}"
                
                church_id_val = campaign_data[1] if campaign_data else None
                
                # Call DB
                uid = register_respondent(church_id_val, username, password, name, whatsapp, gender, age_range, role, mins_combined)
                if uid:
                    st.success("¡Registro exitoso!")
                    # Auto-login
                    user = authenticate_respondent(username, password)
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("El nombre de usuario ya existe. Intente con otro.")

# --- ADMIN SECTION ---
#with st.sidebar:
#    st.title("🛡️ Panel")
    # Admin login removed from sidebar as requested
             
if is_admin():
    # ... (Admin code similar to before, summarized)
    st.header("⚙️ Panel Admin")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🏛️ Iglesias", "🔗 Campañas", "📊 Reportes", "👥 Usuarios", "📝 Respuestas", "🔔 Notificaciones"])
    with tab1:
        st.subheader("Gestión de Iglesias")
        churches = get_churches()
        c_list = ["+ Crear Nueva"] + [f"{c[1]} (ID: {c[0]}, {c[2]})" for c in churches]
        sel_idx = st.selectbox("Seleccione Iglesia para editar o crear:", range(len(c_list)), format_func=lambda x: c_list[x])
        
        # Determine if we are editing or creating
        if sel_idx == 0:
            default_nm = ""
            default_lc = ""
            default_ky = ""
            btn_label = "Guardar Nueva Iglesia"
            editing_id = None
        else:
            selected_church = churches[sel_idx - 1]
            editing_id = selected_church[0]
            default_nm = selected_church[1]
            default_lc = selected_church[2]
            default_ky = selected_church[3]
            btn_label = f"Actualizar Iglesia (ID: {editing_id})"

        with st.form("cf"):
            nm = st.text_input("Nombre", value=default_nm)
            lc = st.text_input("Ubicación", value=default_lc)
            ky = st.text_input("Key (Acceso)", value=default_ky)
            if st.form_submit_button(btn_label):
                if not nm:
                    st.error("El nombre es obligatorio.")
                elif editing_id:
                    update_church(editing_id, nm, lc, ky)
                    st.success(f"Iglesia '{nm}' actualizada.")
                    st.rerun()
                else:
                    add_church(nm, lc, ky)
                    st.success(f"Iglesia '{nm}' creada.")
                    st.rerun()
    with tab2:
        st.subheader("Gestión de Campañas (Magic Links)")
        
        churches = get_churches()
        if not churches:
            st.warning("Primero registre una iglesia.")
        else:
            # Church Selector
            c_map = {c[0]: c[1] for c in churches}
            selected_church_id = st.selectbox("Seleccione Iglesia para gestionar campañas:", options=list(c_map.keys()), format_func=lambda x: c_map[x])
            
            # Show existing
            st.markdown("#### Campañas Activas")
            existing_campaigns = get_campaigns_by_church(selected_church_id)
            if existing_campaigns:
                # campaigns: id, church_id, token, scenario, deadline, is_active
                camp_data = []
                base_url = st.secrets.get("BASE_URL", "http://localhost:8501")
                for c in existing_campaigns:
                    link = f"{base_url}/?t={c[2]}"
                    camp_data.append({
                        "Scenario": c[3],
                        "Deadline": c[4],
                        "Token": c[2],
                        "Link": link
                    })
                st.dataframe(camp_data, column_config={"Link": st.column_config.LinkColumn("Magic Link")}, width='stretch')
            else:
                st.info("No hay campañas creadas para esta iglesia.")

            st.markdown("---")
            st.markdown("#### Generar Nueva Campaña")
            with st.form("new_camp"):
                scen = st.selectbox("Escenario", ["Presencial", "Híbrido", "Online"])
                days = st.number_input("Días de validez", min_value=1, value=30)
                if st.form_submit_button("Generar Link Único"):
                    new_token = str(uuid.uuid4())[:8]
                    deadline = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
                    add_campaign(selected_church_id, new_token, scen, deadline)
                    st.success("¡Campaña creada!")
                    st.rerun()

    with tab3:
        st.subheader("Reportes y Estadísticas")
        churches = get_churches()
        if not churches:
            st.warning("No hay iglesias.")
        else:
            # Map for display including ID and Location to avoid ambiguity
            c_display_map = {c[0]: f"{c[1]} (ID: {c[0]}, {c[2]})" for c in churches}
            selected_church_id = st.selectbox("Ver Reporte de:", options=list(c_display_map.keys()), format_func=lambda x: c_display_map[x], key="adm_rep_sel")
            
            # Show full report (reusing the function used for public view with key)
            if st.button("Cargar Reporte", type="primary"):
                show_enhanced_reports(selected_church_id, c_display_map[selected_church_id])

    with tab4:
        st.subheader("Lista Maestra de Usuarios")
        users_summary = get_all_users_summary()
        if users_summary:
            summary_data = []
            for row in users_summary:
                # row: church_name(0), user_name(1), whatsapp(2), created_at(3), response_count(4), comment_count(5), user_id(6), extension_deadline(7), first_saved_at(8)
                created_at_str = row[3]
                first_save_str = row[8]
                ext_deadline_str = row[7]
                
                # Active days calculation (for general table display)
                active_days = 0
                if created_at_str:
                    try:
                        if " " in created_at_str:
                            dt_created = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
                        else:
                            dt_created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        
                        active_days = (datetime.now().replace(tzinfo=None) - dt_created.replace(tzinfo=None)).days
                    except:
                        pass
                
                # Expiration calculation for the table (Prórroga column)
                ext_str = "No"
                if ext_deadline_str:
                    try:
                        ext_dt = datetime.fromisoformat(ext_deadline_str.replace("Z", "+00:00"))
                        if datetime.now(ext_dt.tzinfo) <= ext_dt:
                             ext_str = f"Sí (hasta {ext_dt.strftime('%d/%m')})"
                    except:
                        pass

                summary_data.append({
                    "Iglesia": row[0] or "N/A",
                    "Usuario": row[1] or "N/A",
                    "WhatsApp": row[2] or "N/A",
                    "Días Activos": active_days,
                    "Respuestas": row[4],
                    "Comentarios": row[5],
                    "Prórroga": ext_str
                })
            
            st.dataframe(pd.DataFrame(summary_data), width='stretch')

            st.markdown("---")
            st.subheader("⏳ Gestionar Prórrogas (Extensiones)")
            from db_manager import update_user_extension
            
            # Create a selector for users: Only those who are "expired"
            u_options = {}
            for r in users_summary:
                if len(r) > 8:
                    uid = r[6]
                    uname = r[1]
                    church = r[0]
                    # Start date for 20-day limit: use first_saved_at, fallback to created_at for legacy users
                    start_date_str = r[8] or r[3]
                    ext_str_val = r[7]
                    
                    is_expired = False
                    if start_date_str:
                        try:
                            # Parse start date
                            if " " in start_date_str:
                                start_dt = datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S")
                            else:
                                start_dt = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
                            
                            # Ensure aware for comparison if needed, or naive
                            now_for_cmp = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now()
                            elapsed = now_for_cmp - start_dt
                            if elapsed > timedelta(days=20):
                                is_expired = True
                        except:
                             pass
                    
                    if is_expired:
                        # If expired, check if they already have a future extension
                        if ext_str_val:
                            try:
                                e_dt = datetime.fromisoformat(ext_str_val.replace("Z", "+00:00"))
                                if datetime.now(e_dt.tzinfo) <= e_dt:
                                    is_expired = False # Extension already making them "active"
                            except:
                                pass
                    
                    if is_expired:
                        u_options[uid] = f"{uname} ({church})"

            if u_options:
                with st.form("ext_form"):
                    sel_user_id = st.selectbox("Seleccionar Usuario Expirado:", options=list(u_options.keys()), format_func=lambda x: u_options[x])
                    ext_days = st.number_input("Días de extensión (máximo 7):", min_value=1, max_value=7, value=7)
                    if st.form_submit_button("Conceder Prórroga"):
                        from datetime import timezone
                        new_deadline = (datetime.now(timezone.utc) + timedelta(days=ext_days)).isoformat()
                        update_user_extension(sel_user_id, new_deadline)
                        st.success(f"Prórroga de {ext_days} días concedida.")
                        st.rerun()
            else:
                st.info("No hay usuarios con encuesta expirada actualmente.")
    with tab5:
        st.subheader("Respuestas Detalladas")
        all_responses = get_all_detailed_responses()
        if all_responses:
            df_resp = pd.DataFrame(all_responses, columns=[
                "Iglesia", "Usuario", "WhatsApp", "Área ID", "Pregunta ID", "Puntaje", "Comentario"
            ])
            st.dataframe(df_resp, width="stretch")
        else:
            st.info("No hay respuestas registradas aún.")

    with tab6:
        st.subheader("🔔 Envío de Notificaciones WhatsApp")
        churches = get_churches()
        if not churches:
            st.warning("No hay iglesias registradas.")
        else:
            c_map = {c[0]: c[1] for c in churches}
            
            def clear_notification_list():
                if 'lista_notificaciones' in st.session_state:
                    del st.session_state.lista_notificaciones

            selected_church_name = st.selectbox(
                "Seleccione Iglesia para enviar notificaciones:", 
                options=[c[1] for c in churches],
                on_change=clear_notification_list
            )
            
            # Message Templates from sendws6.py
            textos_base = [
                "Bendiciones, 👋😊 estimad@ *Usuario*\n\nGracias ✨por tu participación en el 📝cuestionario: \n*_“Tómele el 🩺pulso a su iglesia⛪”_* \n\nHan pasado *dia_activo* 🌓días, \ndesde que te matriculaste✍️ para realizar esta encuesta \ncomo _integrante fundamental_ de la iglesia : \n ⛪︎ *_Iglesia_* \ny llevas registradas \n*respuestas_reg* 📨respuestas de \n 7️⃣0️⃣ preguntas❓, \njunto con *comentarios_reg* 🤔💭comentarios. \n\nTen en cuenta que \n⚠️te faltan *(d_faltan)* 🌓días, \npara ✅ _*completar y editar*_ \ntus respuestas en la encuesta y \nque se espera que escribas✍️ _al menos 30_ comentarios a las respuestas.\n\n\n🎯 *Consolidando el legado ministerial Brethren* 🎯", 
                "Bendiciones querid@ *Usuario* 🙏✨\n\n¡Qué _alegría_ verte participando en el cuestionario “Tómele el 🩺pulso a su iglesia⛪” 😊\n\nYa han pasado *dia_activo* días desde que te inscribiste como miembro tan valioso de  querida iglesia\n ⛪ _*Iglesia*_\n\nHasta ahora has registrado: *respuestas_reg* respuestas de las 70 preguntas y *comentarios_reg* comentarios muy apreciados 💭\n\n⚠️ Solo te quedan *d_faltan* días para _finalizar y editar_ lo que necesites. Recuerda que el objetivo es llegar al menos a 30 comentarios.\n\n_¡Tu voz es importante para fortalecer el trabajo en tu congregación\n\n\n *Consolidando el legado Brethren! ¡Vamos con todo!* 💪❤️", 
                "Hola _*Usuario*_, \nbendiciones 🙌\n\nGracias por tu compromiso con el cuestionario\n _*“Tómele el 🩺pulso a su iglesia⛪”*_\n\nHan transcurrido *dia_activo* días desde tu registro como parte de la congregación \n⛪ *Iglesia*\n\nLlevas: *respuestas_reg* _respuestas_ + *comentarios_reg* _comentarios_\n\n⚠️ Te faltan solo *d_faltan* días para completar todo.\n *Ideal*: _mínimo 30 comentarios_ ✍️\n\n\n_*¡Tu aporte cuenta mucho!*_\n 🎯 Consolidando juntos el legado ministerial Brethren 🎯", 
                "¡Bendiciones *Usuario*! 🌟\n\nGracias de corazón por ser parte activa del cuestionario\n *_“Tómele el 🩺pulso a su iglesia⛪”_*\n\nYa llevamos *_dia_activo_* días desde que te matriculaste como pieza clave de la iglesia:\n *⛪ Iglesia*\n\nTus números hasta ahora:\n ✅ *_respuestas_reg_* respuestas de 70 preguntas\n ✅ *_comentarios_reg_* comentarios valiosísimos\n\n⏳ ¡Quedan *d_faltan días!*\n Es el momento de completar y llegar mínimo a 30 comentarios.\n\n\nJuntos estamos consolidando un legado ministerial fuerte y bendecido.\n* ¡Tú eres parte esencial!* 💙🙏", 
                "Bendiciones en el Señor, estimad@ _*Usuario_* 🙏\n\nAgradecemos mucho tu participación en la encuesta \n*“Tómele el 🩺pulso a su iglesia⛪”*\n\nHan transcurrido _dia_activo_ días desde tu inscripción como integrante valioso de la iglesia ⛪ _*Iglesia*_\n\nHasta el momento has registrado:\n *respuestas_reg* respuestas (de un total de 70 preguntas) \ny *comentarios_reg* comentarios\n\nQuedan _d_faltan_ días para que puedas completar y editar tus respuestas. \nSe espera que alcances al menos 30 comentarios reflexivos.\n\n\nTu aporte contribuirá grandemente a consolidar el trabajo de tu iglesia.\n* Dios te bendiga abundantemente.*",
                "¡Hola _*Usuario*_! Bendiciones ✝️😊\n\nUn recordatorio cariñoso sobre el cuestionario\n *“Tómele el 🩺pulso a su iglesia⛪”*\n\nYa pasaron *dia_activo* días desde que te registraste como integrante de la congregación\n ⛪ _Iglesia_\n\nTus avances: \n*respuestas_reg* respuestas registradas\n *comentarios_reg* comentarios\n\n⚠️* ¡Importante!* Solo faltan *d_faltan* días para cerrar la ventana.\nPor favor completa lo que falta y trata de llegar mínimo a 30 comentarios.\n\n\n_Tu opinión es clave para el futuro de nuestra iglesia._\n ¡Gracias por tu tiempo y compromiso! \n\n\nConsolidando el legado Brethren juntos 🎯🙌", 
                "¡Ey *Usuario*! \nBendiciones 🔥🙌\n\n¡Gracias mil por meterle ganas al cuestionario\n*_ “Tómele el 🩺pulso a su iglesia⛪” !_*\n\nYa van _dia_activo días_ desde que te apuntaste como crack de la iglesia\n* ⛪ Iglesia*\n\nTus _stats_ hasta ahora:\n *respuestas_reg* respuestas de las 70 ❓\n *comentarios_reg* comentarios geniales 💭\n\n🚨 ¡Alerta! Te quedan solo *d_faltan* días para _terminar y editar_.\n *Meta*: mínimo _30_ comentarios ✍️✨\n\n\n¡Tu voz importa muchísimo para construir el legado Brethren! \n*Dale con todo, que Dios te está usando fuerte* 💪❤️"]

            # Images from sendws6.py
            images_urls = [
                "https://drive.google.com/uc?export=download&id=1F0nh_UumRd7Lt4zrXDZ3WK6lmtxsvMIn",
                "https://drive.google.com/uc?export=download&id=1LNfKT2yFGvzEDdYlHs81f4K6XM3lNkMc",
                "https://drive.google.com/uc?export=download&id=1G-V2c0lGdDKk2euRsko6ZnWsaUvHm083",
                "https://drive.google.com/uc?export=download&id=12uemXwntERf_vpVP6Fh_TOwgWFM1ycw_",
                "https://drive.google.com/uc?export=download&id=1mgw_9fFZ9RYZu9lhvGKtwoOF7FJ8M-g-",
                "https://drive.google.com/uc?export=download&id=1Reg4qSm0LnyTACvKp0uY55xO2wRX2bmz",
                "https://drive.google.com/uc?export=download&id=1vrHigahAdhYwRNfoMGguZcGhJaP0aLA1",
                "https://drive.google.com/uc?export=download&id=1FoU1x7NZ-FTERdNX0iE7Wlgc-SfeWRLf",
                "https://drive.google.com/uc?export=download&id=1ME1BY5AjfT4iL2qymxFjY5fyBUOFdP_f",
                "https://drive.google.com/uc?export=download&id=1R0uptjV_KtkGKx1gH5PCnGe1myEcPUyn",
                "https://drive.google.com/uc?export=download&id=15TjYstbVrP8nedoAF_l04vscIozpkPaH",
                "https://drive.google.com/uc?export=download&id=1FEspYhe2kJRBnZp2r6afQ2H9CGoMI8CO",
                "https://drive.google.com/uc?export=download&id=13OkS-KFZ4XEyeyyrudmOp3uGiE8lyAA7",
                "https://drive.google.com/uc?export=download&id=1ezeThKZVnJUtZFpsjPLd4WSc1sQZBPrL",
                "https://drive.google.com/uc?export=download&id=1g8mmNeCXgx6qwQD0JsfoHpg3hVXPvB5j",
                "https://drive.google.com/uc?export=download&id=1961vEYM-obxz0xlUJAPn_zSky145hGze",
                "https://drive.google.com/uc?export=download&id=19VAYv5dbFciURpTUFJPRquhftxN9Yter",
                "https://drive.google.com/uc?export=download&id=1_7VwuCfrysSKB8GMF8FqOqDb4afxyfYB",
                "https://drive.google.com/uc?export=download&id=1K4SyUO1NgUGkW-PwqNvtOHw0H_NnxaKc",
                "https://drive.google.com/uc?export=download&id=1NnLSsRanB8sSeMrXsTg6h6x_uQUgEQIB",
                "https://drive.google.com/uc?export=download&id=144ISCdbniw8_OLhCi5gps2M807SAyDig",
                "https://drive.google.com/uc?export=download&id=11qU5xYDf2t76UI1lDbsHDbAo1Ze9WZS1"
            ]

            if st.button("🔄 Generar Lista de Envíos", type="secondary"):
                users_summary = get_all_users_summary()
                # Filter by selected church
                filtered_users = [u for u in users_summary if u[0] == selected_church_name]
                
                if not filtered_users:
                    st.info(f"No hay usuarios registrados para la iglesia: {selected_church_name}")
                else:
                    now = datetime.now()
                    lista_preparada = []
                    texto_base = random.choice(textos_base)
                    
                    for row in filtered_users:
                        # row: church_name(0), user_name(1), whatsapp(2), created_at(3), response_count(4), comment_count(5)
                        u_church = row[0]
                        u_name = row[1]
                        u_whatsapp = row[2]
                        u_created_at = row[3]
                        u_responses = row[4]
                        u_comments = row[5]
                        
                        active_days = 0
                        if u_created_at:
                            try:
                                dt_created = datetime.strptime(u_created_at, "%Y-%m-%d %H:%M:%S")
                                active_days = (now - dt_created).days
                            except: pass
                        
                        days_left = 20 - active_days
                        
                        # Personalize message logic from sendws6.py
                        msg = texto_base.replace("Usuario", u_name)
                        msg = msg.replace("dia_activo", str(active_days))
                        msg = msg.replace("Iglesia", u_church)
                        msg = msg.replace("respuestas_reg", str(u_responses))
                        msg = msg.replace("comentarios_reg", str(u_comments))
                        msg = msg.replace("d_faltan", str(days_left))
                        
                        lista_preparada.append({
                            "Enviar": False,
                            "Nombre": u_name,
                            "WhatsApp": format_whatsapp(u_whatsapp),
                            "Mensaje": msg
                        })
                    
                    st.session_state.lista_notificaciones = lista_preparada
                    st.success(f"Se han preparado {len(lista_preparada)} notificaciones.")

            if 'lista_notificaciones' in st.session_state and st.session_state.lista_notificaciones:
                st.markdown("#### Vista Previa de Envíos")
                # Use data_editor to allow checkbox interaction
                st.session_state.lista_notificaciones = st.data_editor(
                    st.session_state.lista_notificaciones,
                    column_config={
                        "Enviar": st.column_config.CheckboxColumn("Enviar", default=False)
                    },
                    disabled=["Nombre", "WhatsApp", "Mensaje"],
                    hide_index=True,
                    width='stretch'
                )
                
                if st.button("🚀 Enviar Notificaciones", type="primary"):
                    lista_a_enviar = [item for item in st.session_state.lista_notificaciones if item.get("Enviar")]
                    
                    if not lista_a_enviar:
                        st.warning("Seleccione al menos un destinatario marcando la columna 'Enviar'.")
                    else:
                        progress_text = "Enviando mensajes... Por favor espere."
                        my_bar = st.progress(0, text=progress_text)
                        
                        total = len(lista_a_enviar)
                        for idx, item in enumerate(lista_a_enviar):
                            phone = item["WhatsApp"]
                            message = item["Mensaje"]
                            img = random.choice(images_urls)
                            
                            try:
                                # Using the async function with asyncio.run (Streamlit is synchronous here)
                                asyncio.run(send_whatsapp_message_async(
                                    recipient_phone_number=phone,
                                    text_body=message,
                                    image_url=img
                                ))
                            except Exception as e:
                                st.error(f"Error enviando a {phone}: {e}")
                            
                            # Update progress
                            perc = int(((idx + 1) / total) * 100)
                            my_bar.progress(perc, text=f"Enviado {idx+1}/{total}: {item['Nombre']}")
                            
                            # Delay as in sendws6.py
                            import time
                            time.sleep(10)
                    
                    st.success("¡Proceso de envío finalizado!")
                    del st.session_state.lista_notificaciones

# --- MAIN LOGIC ---
if not is_admin():
    if token:
        if not campaign_data:
            st.error("Token Inválido")
        else:
            church_id = campaign_data[1]
            scenario = campaign_data[3]
            
            # --- AUTH CHECK ---
            if st.session_state.user is None:
                st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
                if st.session_state.recovery_mode:
                    recovery_flow()
                else:
                    tab_login, tab_register = st.tabs(["🔓 Iniciar Sesión", "📝 Registrarse"])
                    with tab_login: login_form()
                    with tab_register: register_form()
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                # --- SURVEY LOGIC for Logged In User ---
                user = st.session_state.user
                # User tuple: id(0), church_id(1), username(2), pass(3), name(4)... last is first_saved_at(11)
                user_id = user[0]
                user_name = user[4]
                first_save_str = user[11] if len(user) > 11 else None
                
                can_edit = True
                days_left = 20
                if first_save_str:
                    try:
                        # SQLite CURRENT_TIMESTAMP ends with 'Z' sometimes, or just no TZ
                        first_save_dt = datetime.fromisoformat(first_save_str.replace("Z", "+00:00"))
                        elapsed = datetime.now(first_save_dt.tzinfo) - first_save_dt
                        if elapsed > timedelta(days=20):
                            can_edit = False
                        else:
                            days_left = 20 - elapsed.days
                    except:
                        pass
                
                # Check for administrator extension (index 14)
                ext_deadline_str = user[14] if len(user) > 14 else None
                if ext_deadline_str:
                    try:
                        ext_dt = datetime.fromisoformat(ext_deadline_str.replace("Z", "+00:00"))
                        if datetime.now(ext_dt.tzinfo) <= ext_dt:
                            can_edit = True
                            st.success(f"🎫 Tienes una prórroga activa hasta el **{ext_dt.strftime('%d/%m/%Y %H:%M')}**")
                    except:
                        pass

                if not can_edit:
                    st.warning("⚠️ El periodo de edición ha finalizado. Sus respuestas ahora son de solo lectura.")
                elif first_save_str:
                    st.info(f"Periodo de edición activo. Le quedan aproximadamente **{max(0, days_left)} días**.")
                else:
                    st.info(f"Bienvenido, **{user_name}**. Una vez que guarde la encuesta por primera vez, tendrá 20 días para realizar cambios.")

                # Load existing responses ONCE
                if not st.session_state.responses_loaded:
                    existing = get_respondent_responses(user_id)
                    # existing is list of tuples: (area_id, q_id, score, comment)
                    cache = {}
                    for row in existing:
                        # row: (area, q, score, comment)
                        # questions are 1-indexed in DB? "question_id"
                        # My UI loop is enumerate i (0-index).
                        # Let's assume question_id stored is 1-based index from loop.
                        cache[(row[0], row[1])] = (row[2], row[3])
                    st.session_state.response_cache = cache
                    st.session_state.responses_loaded = True
                
                st.subheader("📋 Cuestionario")

                new_survey_data = [] # To save
                
                for area_id in sorted(SURVEY_QUESTIONS.keys()):
                    area = SURVEY_QUESTIONS[area_id]
                    with st.expander(f"{area.get('icon','')} {area['title']}", expanded=False):
                        with st.expander(f"ℹ️ Ayuda: {area['title']}", expanded=False):
                            st.markdown(area.get('help_text', ''))
                        
                        for i, q_text in enumerate(area["questions"]):
                            q_idx = i + 1
                            # Get existing values
                            defaults = st.session_state.response_cache.get((area_id, q_idx), (0, ""))
                            
                            st.write(f"**{q_idx}. {q_text}**")
                            score = st.slider(f"Puntaje Q{q_idx}", 0, 10, value=defaults[0], key=f"s_{area_id}_{i}", disabled=not can_edit)
                            comment = st.text_area("Comentario", value=defaults[1], height=60, key=f"c_{area_id}_{i}", disabled=not can_edit)
                            
                            new_survey_data.append((area_id, q_idx, score, comment))

                if can_edit:
                    if st.button("💾 Guardar / Actualizar Encuesta", type="primary", width='stretch'):
                        save_responses(user_id, new_survey_data)
                        st.success("¡Respuestas guardadas exitosamente!")
                        # Update cache so it persists on reload
                        new_cache = {}
                        for item in new_survey_data:
                            new_cache[(item[0], item[1])] = (item[2], item[3])
                        st.session_state.response_cache = new_cache
                        
                        # Refresh user state to get first_saved_at if it was just set
                        # This avoids the "can save multiple times" bug in the same session
                        # Actually, better to just tell the user to refresh if they want to see the "days left"
                        # or update session state manually. 
                        # For simplicity, we just notify success.
                        st.balloons()
                        st.rerun()

                if st.button("Cerrar Sesión"):
                    st.session_state.user = None
                    st.session_state.responses_loaded = False
                    st.session_state.response_cache = {}
                    st.rerun()

    else:
        # No token -> Portal
        st.write("Bienvenido. Por favor use su Magic Link.")
        with st.expander("Resultados (Requiere Clave de Iglesia)"):
             # (Simplified existing logic for viewing reports)
             churches = get_churches()
             if churches:
                  c_map = {c[0]: c[1] for c in churches}
                  cid = st.selectbox("Iglesia", list(c_map.keys()), format_func=lambda x: c_map[x])
                  ckey = st.text_input("Clave", type="password")
                  if st.button("Ver"):
                      c_info = next(c for c in churches if c[0] == cid)
                      if ckey == c_info[3]:
                          show_enhanced_reports(cid, c_info[1])
                      else: st.error("Error")

# --- Footer / Admin Access ---
st.markdown("---")
if not is_admin() and token is None:
    with st.expander("🔐 Acceso Administrativo"):
        pass_in = st.text_input("Contraseña Admin", type="password")
        if st.button("Ingresar Panel Admin"):
            if pass_in == st.secrets["admin"]["PASSWORD"]:
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta")
else:
    if st.button("Cerrar Sesión Admin", type="secondary"):
        st.session_state.admin_authenticated = False
        st.rerun()
