import streamlit as st
import streamlit.components.v1 as components
import qrcode
import json
import os
import base64
import hashlib
import uuid
import textwrap
import html as html_lib
import urllib.parse as urlparse
import cv2
import numpy as np
import pandas as pd
import random
import string
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Registro de Carnet Estudiantil", layout="wide")

OS_DIR = "datos_carnets"
if not os.path.exists(OS_DIR):
    os.makedirs(OS_DIR)

BASE_URL = "http://localhost:8501"

CREDENCIALES_FILE = "credenciales_admin.json"
ASISTENCIA_FILE = "asistencias.csv"
COLUMNAS_ASISTENCIA = ["codigo", "nombres", "apellidos", "grado", "fecha", "hora"]

# Orden lógico de los grados (debe coincidir con las opciones del selectbox de registro,
# sin las líneas de separador "── ... ──"). Se usa para agrupar y ordenar por grado.
ORDEN_GRADOS = [
    "Prekínder",
    "Kínder",
    "Preprimaria",
    "Primero Primaria",
    "Segundo Primaria",
    "Tercero Primaria",
    "Cuarto Primaria",
    "Quinto Primaria",
    "Sexto Primaria",
    "Primero Básico – Sección A",
    "Primero Básico – Sección B",
    "Segundo Básico – Sección A",
    "Segundo Básico – Sección B",
    "Tercero Básico – Sección A",
    "Tercero Básico – Sección B",
    "Cuarto Bachillerato",
    "Quinto Bachillerato",
    "Cuarto Magisterio",
    "Quinto Magisterio",
    "Sexto Magisterio",
]

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# Niveles educativos y los grados que contiene cada uno. Se usa para el registro
# en dos pasos (nivel -> grado), de forma que los encabezados de nivel nunca
# aparezcan como una opción de grado seleccionable por error.
NIVELES_GRADOS = {
    "Preprimaria": ["Prekínder", "Kínder", "Preprimaria"],
    "Primaria": [
        "Primero Primaria", "Segundo Primaria", "Tercero Primaria",
        "Cuarto Primaria", "Quinto Primaria", "Sexto Primaria",
    ],
    "Básico": [
        "Primero Básico – Sección A", "Primero Básico – Sección B",
        "Segundo Básico – Sección A", "Segundo Básico – Sección B",
        "Tercero Básico – Sección A", "Tercero Básico – Sección B",
    ],
    "Diversificado – Bachillerato": ["Cuarto Bachillerato", "Quinto Bachillerato"],
    "Diversificado – Magisterio": ["Cuarto Magisterio", "Quinto Magisterio", "Sexto Magisterio"],
}


def normalizar_grado(grado):
    """Devuelve el grado tal cual, o 'Sin grado' si viene vacío/None."""
    if isinstance(grado, str) and grado.strip():
        return grado.strip()
    return "Sin grado"


def ordenar_grados_presentes(grados_presentes):
    """Ordena un conjunto de grados según ORDEN_GRADOS; cualquier grado que no
    esté en la lista (por ejemplo 'Sin grado') se agrega al final, alfabéticamente."""
    ordenados = [g for g in ORDEN_GRADOS if g in grados_presentes]
    extras = sorted(g for g in grados_presentes if g not in ORDEN_GRADOS)
    return ordenados + extras


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def cargar_credenciales_admin():
    if not os.path.exists(CREDENCIALES_FILE):
        credenciales_default = {
            "usuario": "admin.nazareno",
            "password_hash": hash_password("Naz@reno2026!"),
        }
        with open(CREDENCIALES_FILE, "w") as f:
            json.dump(credenciales_default, f)
        return credenciales_default
    with open(CREDENCIALES_FILE, "r") as f:
        return json.load(f)


def guardar_credenciales_admin(usuario, password_hash):
    with open(CREDENCIALES_FILE, "w") as f:
        json.dump({"usuario": usuario, "password_hash": password_hash}, f)


def verificar_admin(usuario, password):
    credenciales = cargar_credenciales_admin()
    return (
        usuario == credenciales["usuario"]
        and hash_password(password) == credenciales["password_hash"]
    )


# ================== GENERADOR DE CÓDIGO ALEATORIO ==================
def generar_codigo_aleatorio(longitud=7):
    """Genera un código aleatorio de letras mayúsculas y números de 7 caracteres."""
    caracteres = string.ascii_uppercase + string.digits
    while True:
        codigo = ''.join(random.choices(caracteres, k=longitud))
        if not os.path.exists(os.path.join(OS_DIR, f"{codigo}.json")):
            return codigo


# ================== ESTADO DE SESIÓN ==================
if "pagina" not in st.session_state:
    st.session_state.pagina = "login_admin"
    st.session_state.logged_in = False
    st.session_state.rol = None
    st.session_state.username = None
    st.session_state.ultimo_codigo_registrado = None
    st.session_state.codigo_escaneado = None

if "modo_oscuro" not in st.session_state:
    st.session_state.modo_oscuro = False

# ================== LOGO Y FONDO ==================
LOGO_PATH = None
for ext in ["logo.png", "logo.jpg", "logo.jpeg"]:
    if os.path.exists(ext):
        LOGO_PATH = ext
        break

FONDO_PATH = None
for ext in ["fondo.jpg", "fondo.jpeg", "fondo.png"]:
    if os.path.exists(ext):
        FONDO_PATH = ext
        break


def get_base64(bin_file):
    with open(bin_file, 'rb') as f:
        return base64.b64encode(f.read()).decode()


# ================== UTILIDADES DE DATOS DE CARNETS ==================
def cargar_registro(codigo):
    path = os.path.join(OS_DIR, f"{codigo}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None


def buscar_duplicado_por_dpi(dpi):
    dpi_normalizado = (dpi or "").strip().lower().replace(" ", "")
    if not dpi_normalizado or dpi_normalizado == "noaplica":
        return None
    for fname in os.listdir(OS_DIR):
        if fname.endswith(".json"):
            with open(os.path.join(OS_DIR, fname), "r") as f:
                try:
                    registro = json.load(f)
                except json.JSONDecodeError:
                    continue
            dpi_existente = (registro.get("dpi") or "").strip().lower().replace(" ", "")
            if dpi_existente and dpi_existente != "noaplica" and dpi_existente == dpi_normalizado:
                return registro
    return None


# ================== UTILIDADES DE ASISTENCIA ==================
def cargar_asistencias():
    if not os.path.exists(ASISTENCIA_FILE):
        return pd.DataFrame(columns=COLUMNAS_ASISTENCIA)
    try:
        df = pd.read_csv(ASISTENCIA_FILE, dtype=str)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return pd.DataFrame(columns=COLUMNAS_ASISTENCIA)
    for col in COLUMNAS_ASISTENCIA:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNAS_ASISTENCIA]


def guardar_asistencias(df):
    df.to_csv(ASISTENCIA_FILE, index=False)


def marcar_asistencia(registro):
    """Registra la asistencia de hoy para el estudiante indicado.
    Retorna una tupla (estado, hora) donde estado es 'nueva' o 'duplicada'."""
    ahora = datetime.now()
    fecha_hoy = ahora.strftime("%Y-%m-%d")
    hora_actual = ahora.strftime("%H:%M:%S")

    df = cargar_asistencias()
    codigo = registro.get("codigo", "")

    coincidencia = df[(df["codigo"] == codigo) & (df["fecha"] == fecha_hoy)]
    if not coincidencia.empty:
        return "duplicada", coincidencia.iloc[0]["hora"]

    nueva_fila = {
        "codigo": codigo,
        "nombres": registro.get("nombres", ""),
        "apellidos": registro.get("apellidos", ""),
        "grado": registro.get("grado", ""),
        "fecha": fecha_hoy,
        "hora": hora_actual,
    }
    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    guardar_asistencias(df)
    return "nueva", hora_actual


def generar_excel_bytes(df):
    """Genera el Excel en memoria. Si falta la librería 'openpyxl' instalada,
    retorna None en lugar de tronar la app."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return None
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Asistencia")
    return buffer.getvalue()


# ================== ESCÁNER DE QR CON CÁMARA ==================
def leer_qr_desde_imagen(imagen_bytes):
    file_bytes = np.frombuffer(imagen_bytes, np.uint8)
    frame = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if frame is None:
        return None
    detector = cv2.QRCodeDetector()
    datos, _, _ = detector.detectAndDecode(frame)
    return datos if datos else None


def extraer_codigo_de_texto_qr(texto):
    if not texto:
        return None
    try:
        parsed = urlparse.urlparse(texto)
        query = urlparse.parse_qs(parsed.query)
        if "codigo" in query and query["codigo"]:
            return query["codigo"][0]
    except Exception:
        pass
    return texto.strip()


def escaner_qr_camara(key_camara):
    foto_qr = st.camera_input("Apunta la cámara al código QR del carnet", key=key_camara)
    if foto_qr is None:
        return None

    texto = leer_qr_desde_imagen(foto_qr.getvalue())
    codigo_detectado = extraer_codigo_de_texto_qr(texto)

    if not codigo_detectado:
        st.warning("No se detectó ningún código QR en la imagen. Intenta acercar más la cámara.")
        return None

    if not cargar_registro(codigo_detectado):
        st.warning(f"Se leyó el código '{codigo_detectado}', pero no corresponde a ningún carnet registrado.")
        return None

    return codigo_detectado


def obtener_foto_base64(nombre_foto):
    if not nombre_foto:
        return None
    ruta = os.path.join(OS_DIR, nombre_foto)
    if not os.path.exists(ruta):
        return None
    ext = nombre_foto.split(".")[-1].lower()
    with open(ruta, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/{ext};base64,{b64}"


def renderizar_carnet(datos):
    """Renderiza el carnet de forma aislada dentro de un iframe para evitar problemas de formato."""
    nombres = html_lib.escape(datos.get("nombres", ""))
    apellidos = html_lib.escape(datos.get("apellidos", ""))
    codigo = html_lib.escape(datos.get("codigo", ""))
    grado = html_lib.escape(datos.get("grado", ""))
    
    foto_b64 = obtener_foto_base64(datos.get("foto"))
    
    qr_path = os.path.join(OS_DIR, f"{codigo}_qr.png")
    qr_b64 = get_base64(qr_path) if os.path.exists(qr_path) else ""

    logo_b64 = ""
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        ext_logo = LOGO_PATH.split(".")[-1]
        logo_b64 = f"data:image/{ext_logo};base64,{get_base64(LOGO_PATH)}"

    img_foto = f'<img src="{foto_b64}" style="width:130px;height:150px;object-fit:cover;border-radius:12px;border:3px solid #fff;" />' if foto_b64 else '<div style="width:130px;height:150px;border-radius:12px;background:#e2e8f0;display:flex;align-items:center;justify-content:center;font-size:40px;border:3px solid #fff;">👤</div>'

    img_qr = f'<img src="data:image/png;base64,{qr_b64}" style="width:65px;height:65px;border-radius:6px;background:white;padding:2px;" />' if qr_b64 else ''

    logo_img = f'<img src="{logo_b64}" style="width:40px;height:40px;border-radius:50%;background:white;padding:2px;" />' if logo_b64 else ''

    html_content = textwrap.dedent(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ margin: 0; padding: 0; background: transparent; font-family: sans-serif; display: flex; justify-content: center; }}
                .card {{
                    width: 300px;
                    border-radius: 20px;
                    background: linear-gradient(160deg, #0c2340 0%, #0066ff 100%);
                    padding: 18px;
                    color: #ffffff;
                    box-shadow: 0 8px 20px rgba(0,0,0,0.3);
                    box-sizing: border-box;
                }}
                .header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
                .title {{ text-align: left; font-size: 11px; font-weight: bold; line-height: 1.2; }}
                .subtitle {{ text-align: left; margin-bottom: 10px; }}
                .sub-label {{ font-size: 9px; opacity: 0.8; }}
                .sub-year {{ font-size: 15px; font-weight: bold; }}
                .photo-container {{ display: flex; justify-content: center; margin-bottom: 10px; }}
                .footer {{ display: flex; justify-content: space-between; align-items: flex-end; text-align: left; }}
                .field-label {{ font-size: 8px; opacity: 0.8; }}
                .field-val {{ font-size: 13px; font-weight: bold; margin-bottom: 4px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="header">
                    {logo_img}
                    <div class="title">Colegio Mixto<br>Evangélico Nazareno</div>
                </div>
                <div class="subtitle">
                    <div class="sub-label">Carnet estudiantil</div>
                    <div class="sub-year">Ciclo escolar {datetime.now().year}</div>
                </div>
                <div class="photo-container">
                    {img_foto}
                </div>
                <div class="footer">
                    <div>
                        <div class="field-label">CÓDIGO</div>
                        <div class="field-val">{codigo}</div>
                        <div class="field-label">NOMBRE</div>
                        <div class="field-val">{nombres}<br>{apellidos}</div>
                        <div class="field-label">GRADO</div>
                        <div class="field-val" style="margin-bottom:0;">{grado}</div>
                    </div>
                    <div>
                        {img_qr}
                    </div>
                </div>
            </div>
        </body>
        </html>
    """)

    components.html(html_content, height=440)


def mostrar_tabla_con_carnet(df_tabla, key_tabla):
    """Muestra un dataframe donde se puede tocar una fila (debe tener columna 'codigo')
    para ver el carnet de ese estudiante justo debajo de la tabla."""
    df_tabla = df_tabla.reset_index(drop=True)

    evento_tabla = st.dataframe(
        df_tabla,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=key_tabla,
    )

    filas_seleccionadas = []
    if evento_tabla is not None and getattr(evento_tabla, "selection", None) is not None:
        seleccion = evento_tabla.selection
        filas_seleccionadas = seleccion.get("rows", []) if isinstance(seleccion, dict) else seleccion.rows

    if filas_seleccionadas and "codigo" in df_tabla.columns:
        codigo_tocado = df_tabla.iloc[filas_seleccionadas[0]]["codigo"]
        datos_tocados = cargar_registro(codigo_tocado)
        if datos_tocados:
            st.write("")
            cver1, cver2, cver3 = st.columns([1, 1, 1])
            with cver2:
                renderizar_carnet(datos_tocados)


# ================== INTERRUPTOR DE MODO OSCURO ==================
with st.sidebar:
    st.session_state.modo_oscuro = st.toggle(
        "🌙 Modo oscuro",
        value=st.session_state.modo_oscuro,
        key="toggle_modo_oscuro",
        help="Cambiar entre modo claro y modo oscuro",
    )
    st.markdown("<hr style='margin: 10px 0 18px 0;'>", unsafe_allow_html=True)

MODO_OSCURO = st.session_state.modo_oscuro

# Paleta de colores según el modo
if MODO_OSCURO:
    PALETA = {
        "texto": "#e5e9f0",
        "texto_secundario": "#94a3b8",
        "fondo_gradiente": "linear-gradient(135deg, #0b1120 0%, #111827 50%, #1e2a45 100%)",
        "input_bg": "#1e293b",
        "input_borde": "#475569",
        "placeholder": "#64748b",
        "icono": "#94a3b8",
        "dropzone_bg": "#1e293b",
        "dropzone_boton_bg": "#334155",
        "primario": "#3b82f6",
        "primario_texto": "#ffffff",
        "secundario_bg": "#1e293b",
        "card_bg": "rgba(30, 41, 59, 0.85)",
        "card_borde": "#334155",
        "alerta_bg": "#1e293b",
        "alerta_borde": "#475569",
        "hr_color": "#334155",
        "sidebar_bg": "#111827",
    }
else:
    PALETA = {
        "texto": "#0c2340",
        "texto_secundario": "#475569",
        "fondo_gradiente": "linear-gradient(135deg, #e0f2fe 0%, #bae6fd 50%, #0284c7 100%)",
        "input_bg": "#ffffff",
        "input_borde": "#94a3b8",
        "placeholder": "#94a3b8",
        "icono": "#64748b",
        "dropzone_bg": "#ffffff",
        "dropzone_boton_bg": "#e2e8f0",
        "primario": "#0066ff",
        "primario_texto": "#ffffff",
        "secundario_bg": "#ffffff",
        "card_bg": "rgba(255, 255, 255, 0.9)",
        "card_borde": "#ffffff",
        "alerta_bg": "#ffffff",
        "alerta_borde": "#cbd5e1",
        "hr_color": "#cbd5e1",
        "sidebar_bg": "#ffffff",
    }

bg_css = ""
if FONDO_PATH and not MODO_OSCURO:
    bin_str = get_base64(FONDO_PATH)
    ext_type = FONDO_PATH.split('.')[-1]
    bg_css = f"""
        [data-testid="stAppViewContainer"] {{
            background-image: url("data:image/{ext_type};base64,{bin_str}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}
    """
else:
    bg_css = f"""
        [data-testid="stAppViewContainer"] {{
            background: {PALETA["fondo_gradiente"]};
        }}
    """

st.markdown(
    f"""
    <style>
    {bg_css}

    [data-testid="stHeader"] {{
        background-color: rgba(0,0,0,0);
    }}

    .block-container {{
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        max-width: 1200px !important;
    }}

    h1, h2, h3, h4, label, p, span:not([data-testid="stIconMaterial"]) {{
        color: {PALETA["texto"]} !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
    }}

    [data-testid="stIconMaterial"] {{
        font-family: 'Material Symbols Rounded' !important;
        color: {PALETA["icono"]} !important;
    }}

    div[data-baseweb="input"],
    div[data-baseweb="base-input"],
    div[data-baseweb="select"] > div,
    input[type="text"],
    input[type="password"],
    input[type="date"],
    div[data-baseweb="datepicker"] div {{
        background-color: {PALETA["input_bg"]} !important;
        color: {PALETA["texto"]} !important;
        border-color: {PALETA["input_borde"]} !important;
    }}

    /* Los controles "cerrados" de fecha_nacimiento y de los selectbox
       (nivel/grado, filtros, etc.) a veces traen su propio fondo blanco
       pintado por un div más interno, con más especificidad que la regla
       genérica de arriba. Se repite la regla pero anclada al contenedor
       del widget (stDateInput / stSelectbox / stTextInput) para ganar esa
       pelea de especificidad sin importar cuántos divs haya por dentro. */
    [data-testid="stDateInput"] div,
    [data-testid="stDateInput"] input,
    [data-testid="stSelectbox"] div[data-baseweb],
    [data-testid="stTextInput"] div,
    [data-testid="stTextInput"] input {{
        background-color: {PALETA["input_bg"]} !important;
        color: {PALETA["texto"]} !important;
        border-color: {PALETA["input_borde"]} !important;
    }}
    [data-testid="stDateInput"] svg,
    [data-testid="stSelectbox"] svg {{
        fill: {PALETA["texto"]} !important;
    }}

    input::placeholder {{
        color: {PALETA["placeholder"]} !important;
    }}

    div[data-baseweb="select"] svg,
    div[data-baseweb="datepicker"] svg {{
        fill: {PALETA["texto"]} !important;
    }}

    [data-testid="stFileUploaderDropzone"] {{
        background-color: {PALETA["dropzone_bg"]} !important;
        border: 1.5px dashed {PALETA["input_borde"]} !important;
        border-radius: 10px !important;
    }}

    [data-testid="stFileUploaderDropzone"] button {{
        background-color: {PALETA["dropzone_boton_bg"]} !important;
        border: 1px solid {PALETA["input_borde"]} !important;
        border-radius: 6px !important;
        color: {PALETA["texto"]} !important;
        box-shadow: none !important;
    }}

    [data-testid="stFileUploaderDropzone"] button span *,
    [data-testid="stFileUploaderDropzone"] button small {{
        display: none !important;
    }}

    div.stButton > button[kind="primary"] {{
        background-color: {PALETA["primario"]} !important;
        border: none !important;
        border-radius: 8px !important;
    }}
    div.stButton > button[kind="primary"] p,
    div.stButton > button[kind="primary"] span {{
        color: {PALETA["primario_texto"]} !important;
        font-weight: 700 !important;
        font-size: 16px !important;
    }}

    div.stButton > button:not([kind="primary"]) {{
        background-color: {PALETA["secundario_bg"]} !important;
        border: 2px solid {PALETA["primario"]} !important;
        border-radius: 8px !important;
    }}
    div.stButton > button:not([kind="primary"]) p,
    div.stButton > button:not([kind="primary"]) span {{
        color: {PALETA["primario"]} !important;
        font-weight: 700 !important;
        font-size: 16px !important;
    }}

    .security-card {{
        background-color: {PALETA["card_bg"]};
        backdrop-filter: blur(8px);
        border: 1px solid {PALETA["card_borde"]};
        border-radius: 16px;
        padding: 16px;
        margin-top: 25px;
        display: flex;
        align-items: center;
        gap: 15px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }}

    [data-testid="stAlert"] {{
        background-color: {PALETA["alerta_bg"]} !important;
        border-radius: 10px !important;
        padding: 14px 18px !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15) !important;
        border: 1px solid {PALETA["alerta_borde"]} !important;
    }}
    [data-testid="stAlert"] p {{
        color: {PALETA["texto"]} !important;
        font-weight: 600 !important;
        font-size: 14.5px !important;
    }}

    .login-card {{
        background-color: {PALETA["card_bg"]};
        backdrop-filter: blur(8px);
        border: 1px solid {PALETA["card_borde"]};
        border-radius: 20px;
        padding: 40px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
        margin-top: 10px;
    }}

    [data-testid="stExpander"] {{
        background-color: {PALETA["card_bg"]} !important;
        border: 1px solid {PALETA["card_borde"]} !important;
        border-radius: 12px !important;
    }}

    [data-testid="stDataFrame"] {{
        border-radius: 10px !important;
        overflow: hidden !important;
    }}

    hr {{
        border-top: 1px solid {PALETA["hr_color"]} !important;
    }}

    /* ============ CORRECCIONES DE CONTRASTE (MODO OSCURO) ============ */

    /* Los menús desplegables (selectbox) y el calendario (date_input) se
       dibujan en una capa flotante aparte del resto de la página ("popover").
       Antes heredaban el color de texto claro del modo oscuro pero seguían
       teniendo fondo blanco, por eso el texto se veía invisible. Aquí se
       fuerza fondo blanco + texto oscuro SIEMPRE en esa capa, sin importar
       si el modo oscuro está activo o no. */
    div[data-baseweb="popover"] ul[role="listbox"],
    div[data-baseweb="popover"] div[data-baseweb="calendar"],
    div[data-baseweb="menu"] {{
        background-color: #ffffff !important;
    }}
    div[data-baseweb="popover"] ul[role="listbox"] *,
    div[data-baseweb="popover"] div[data-baseweb="calendar"] *,
    div[data-baseweb="menu"] * {{
        color: #0c2340 !important;
    }}
    div[data-baseweb="popover"] li[aria-selected="true"],
    div[data-baseweb="popover"] div[aria-selected="true"] {{
        background-color: #e0f2fe !important;
    }}

    /* "Usuario" y "Rol" en la barra lateral: se sube la especificidad del
       selector (con el data-testid del sidebar) para ganarle a los estilos
       propios de Streamlit que antes dejaban ese texto casi invisible. */
    /* El fondo de la barra lateral no cambiaba con el modo oscuro (se
       quedaba con el gris claro por defecto de Streamlit), así que el
       texto claro quedaba casi invisible sobre ese fondo claro. Ahora se
       fuerza también el fondo de la barra lateral según el modo. */
    [data-testid="stSidebar"],
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"] {{
        background-color: {PALETA["sidebar_bg"]} !important;
    }}
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] div {{
        color: {PALETA["texto"]} !important;
    }}

    /* Botones de descarga (CSV / Excel): usan un componente distinto al de
       st.button ("stDownloadButton"), así que antes no recibían ningún
       estilo y se quedaban con fondo y texto blancos. */
    [data-testid="stDownloadButton"] button {{
        background-color: {PALETA["secundario_bg"]} !important;
        border: 2px solid {PALETA["primario"]} !important;
        border-radius: 8px !important;
    }}
    [data-testid="stDownloadButton"] button p,
    [data-testid="stDownloadButton"] button span {{
        color: {PALETA["primario"]} !important;
        font-weight: 700 !important;
    }}

    /* Cámara de asistencia: el recuadro de permiso de cámara y el botón
       "Take Photo" también quedaban fuera del estilo general. */
    [data-testid="stCameraInput"] {{
        background-color: {PALETA["dropzone_bg"]} !important;
        border-radius: 10px !important;
    }}
    [data-testid="stCameraInput"] p,
    [data-testid="stCameraInput"] span,
    [data-testid="stCameraInput"] label {{
        color: {PALETA["texto"]} !important;
    }}
    [data-testid="stCameraInput"] button {{
        background-color: {PALETA["dropzone_boton_bg"]} !important;
        color: {PALETA["texto"]} !important;
        border: 1px solid {PALETA["input_borde"]} !important;
    }}

    /* Encabezados de los desplegables por grado / por mes (los "expanders"
       de Carnets registrados e Historial mensual). */
    /* El encabezado (summary) de cada expander pinta su propio fondo por
       encima del que le pusimos al contenedor completo, por eso seguía
       viéndose blanco. Se fuerza el fondo y el color de TODO lo que haya
       dentro del encabezado, sin importar la etiqueta que use. */
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] details > summary {{
        background-color: {PALETA["card_bg"]} !important;
    }}
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary * {{
        color: {PALETA["texto"]} !important;
        font-weight: 600 !important;
    }}

    /* Pestañas del menú principal: se agranda el área táctil de cada
       pestaña para que todo el bloque (ícono + texto) sea clicable, y no
       solo una franja debajo del texto. */
    [data-baseweb="tab-list"] {{
        align-items: stretch !important;
    }}
    [data-baseweb="tab-list"] button[data-baseweb="tab"],
    [data-baseweb="tab-list"] [role="tab"] {{
        height: auto !important;
        min-height: 48px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 12px 16px !important;
        line-height: normal !important;
    }}
    [data-baseweb="tab-list"] button[data-baseweb="tab"] *,
    [data-baseweb="tab-list"] [role="tab"] * {{
        line-height: normal !important;
        vertical-align: middle !important;
        margin: 0 !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)


# ================== PANTALLA DE LOGIN (ADMIN) ==================
def pantalla_login_admin():
    col_a, col_b, col_c = st.columns([1, 1.2, 1])
    with col_b:
        st.markdown("<div class='login-card'>", unsafe_allow_html=True)
        if LOGO_PATH:
            lc1, lc2, lc3 = st.columns([1, 1, 1])
            with lc2:
                st.image(LOGO_PATH, width=110)

        st.markdown(
            "<h2 style='text-align:center; font-size:24px; font-weight:800; margin-top:10px;'>Acceso de administrador</h2>",
            unsafe_allow_html=True
        )
        st.markdown(
            "<p style='text-align:center; color:#334155; margin-bottom:20px;'>Ingresa tus credenciales para continuar</p>",
            unsafe_allow_html=True
        )

        usuario = st.text_input("Usuario", placeholder="Ingrese su usuario", key="login_usuario")
        password = st.text_input("Contraseña", placeholder="Ingrese su contraseña", type="password", key="login_password")

        if st.button("Ingresar", type="primary", use_container_width=True, key="btn_login"):
            if verificar_admin(usuario, password):
                st.session_state.logged_in = True
                st.session_state.rol = "admin"
                st.session_state.username = usuario
                st.session_state.pagina = "app"
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")
        st.markdown("</div>", unsafe_allow_html=True)


# ================== PANTALLA PÚBLICA: VER CARNET DESDE EL QR ==================
def pantalla_ver_carnet_publico(codigo):
    col_a, col_b, col_c = st.columns([1, 1.3, 1])
    with col_b:
        if LOGO_PATH:
            lc1, lc2, lc3 = st.columns([1, 1, 1])
            with lc2:
                st.image(LOGO_PATH, width=100)

        st.markdown(
            "<h2 style='text-align:center; font-size:24px; font-weight:800; margin-top:10px;'>Tu carnet estudiantil</h2>",
            unsafe_allow_html=True
        )

        datos = cargar_registro(codigo)
        if not datos:
            st.error("No se encontró ningún carnet con ese código.")
        else:
            st.write("")
            renderizar_carnet(datos)

        st.write("")
        if st.button("Ir al inicio", use_container_width=True, key="btn_volver_publico"):
            st.query_params.clear()
            st.session_state.codigo_escaneado = None
            st.session_state.pagina = "login_admin"
            st.rerun()


# ================== FORMULARIO DE REGISTRO ==================
def mostrar_confirmacion_registro(codigo):
    col_a, col_b, col_c = st.columns([1, 1.3, 1])
    with col_b:
        st.markdown(
            "<h2 style='text-align:center; font-size:26px; font-weight:800;'>¡Carnet registrado con éxito! ✅</h2>",
            unsafe_allow_html=True
        )
        datos = cargar_registro(codigo)
        if datos:
            st.write("")
            renderizar_carnet(datos)

        st.write("")
        if st.button("Registrar otro carnet", use_container_width=True, key="btn_otro_registro"):
            st.session_state.ultimo_codigo_registrado = None
            st.rerun()


def pantalla_registro():
    if st.session_state.get("ultimo_codigo_registrado"):
        mostrar_confirmacion_registro(st.session_state.ultimo_codigo_registrado)
        return

    col_izq, col_der = st.columns([5, 7], gap="large")

    with col_izq:
        st.write("")
        if LOGO_PATH:
            st.image(LOGO_PATH, width=170)

        st.markdown("<h1 style='font-size: 38px; font-weight: 800; color: #0c2340; margin-top: 15px; margin-bottom: 5px;'>Registro de<br>Carnet estudiantil</h1>", unsafe_allow_html=True)
        st.markdown("<div style='width: 50px; height: 4px; background-color: #0066ff; border-radius: 2px; margin-bottom: 20px;'></div>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 16px; color: #334155; line-height: 1.5;'>Complete el formulario con sus datos personales para solicitar su carnet estudiantil.</p>", unsafe_allow_html=True)

        st.markdown(
            """
            <div class="security-card">
                <div style="background-color: #0066ff; border-radius: 50%; padding: 10px; display: flex; align-items: center; justify-content: center;">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
                </div>
                <div>
                    <strong style="color: #0c2340; font-size: 15px; display: block;">Seguro y confiable</strong>
                    <span style="color: #475569; font-size: 13px; line-height: 1.3; display: block;">Sus datos están protegidos y serán utilizados únicamente para el proceso de registro.</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_der:
        st.markdown("<h3 style='font-size: 20px; font-weight: 700; color: #0c2340;'><span style='background-color: #0066ff; color: white; border-radius: 50%; width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center; font-size: 13px;'>👤</span> Datos personales</h3>", unsafe_allow_html=True)
        st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px; border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            nombres = st.text_input("Nombres *", placeholder="Ingrese sus nombres")
        with c2:
            apellidos = st.text_input("Apellidos *", placeholder="Ingrese sus apellidos")

        c3, c4 = st.columns(2)
        with c3:
            dpi = st.text_input("DPI", placeholder="Ingrese su DPI (opcional)")
        with c4:
            fecha_nac = st.date_input(
                "Fecha de nacimiento *",
                value=None,
                min_value=datetime(1995, 1, 1),
                max_value=datetime.now(),
            )

        st.write("")
        st.markdown("<h3 style='font-size: 20px; font-weight: 700; color: #0c2340;'><span style='background-color: #0066ff; color: white; border-radius: 50%; width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center; font-size: 13px;'>🪪</span> Información adicional</h3>", unsafe_allow_html=True)
        st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px; border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)

        c5, c6 = st.columns(2)
        with c5:
            carnet_actual = st.text_input("No. de carnet actual (si tiene)", placeholder="Ingrese su número de carnet (opcional)")
        with c6:
            nivel_seleccionado = st.selectbox(
                "Nivel educativo *",
                ["Seleccione el nivel"] + list(NIVELES_GRADOS.keys()),
                key="select_nivel_registro",
            )

        grados_disponibles = NIVELES_GRADOS.get(nivel_seleccionado, [])
        if grados_disponibles:
            opciones_grado = ["Seleccione su grado"] + grados_disponibles
        else:
            opciones_grado = ["Seleccione primero el nivel educativo"]

        grado = st.selectbox(
            "Grado actual *",
            opciones_grado,
            disabled=not grados_disponibles,
            key="select_grado_registro",
        )

        foto_estudiante = st.file_uploader("Foto del estudiante *", type=["png", "jpg", "jpeg"])
        if foto_estudiante is not None:
            st.image(foto_estudiante, width=140, caption="Vista previa de la foto")

        st.write("")

        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            if st.button("Cancelar", use_container_width=True, key="btn_cancelar"):
                st.rerun()
        with btn_col2:
            if st.button("Registrar carnet", type="primary", use_container_width=True, key="btn_registrar"):
                # Validaciones de campos obligatorios
                if not nombres or not apellidos:
                    st.error("Por favor ingrese al menos Nombres y Apellidos.")
                elif nivel_seleccionado == "Seleccione el nivel" or grado in ("Seleccione su grado", "Seleccione primero el nivel educativo"):
                    st.error("Por favor seleccione el nivel educativo y el grado actual.")
                elif fecha_nac is None:
                    st.error("Por favor ingrese la fecha de nacimiento.")
                elif foto_estudiante is None:
                    st.error("Por favor suba una foto del estudiante.")
                else:
                    # Si no ingresó DPI, asignamos "No aplica"
                    dpi_final = dpi.strip() if dpi and dpi.strip() else "No aplica"

                    duplicado = buscar_duplicado_por_dpi(dpi_final) if dpi_final != "No aplica" else None
                    if duplicado:
                        st.error(
                            f"Este carnet ya está registrado (código {duplicado.get('codigo', '')}). "
                            "Si crees que es un error, contacta al administrador."
                        )
                    else:
                        codigo = carnet_actual.strip() if carnet_actual and carnet_actual.strip() else generar_codigo_aleatorio()

                        datos = {
                            "nombres": nombres,
                            "apellidos": apellidos,
                            "dpi": dpi_final,
                            "fecha_nacimiento": str(fecha_nac) if fecha_nac else "",
                            "codigo": codigo,
                            "grado": grado,
                        }

                        ext_foto = foto_estudiante.name.split(".")[-1].lower()
                        nombre_foto = f"{codigo}_foto.{ext_foto}"
                        with open(os.path.join(OS_DIR, nombre_foto), "wb") as f:
                            f.write(foto_estudiante.getbuffer())
                        datos["foto"] = nombre_foto

                        # Guardar QR
                        url_destinatario = f"{BASE_URL}/?codigo={codigo}"
                        qr = qrcode.QRCode(box_size=10, border=2)
                        qr.add_data(url_destinatario)
                        qr.make(fit=True)
                        img_qr = qr.make_image(fill_color="black", back_color="white")
                        img_qr.save(os.path.join(OS_DIR, f"{codigo}_qr.png"))

                        # Guardar JSON
                        file_path = os.path.join(OS_DIR, f"{codigo}.json")
                        with open(file_path, "w") as f:
                            json.dump(datos, f)

                        st.session_state.ultimo_codigo_registrado = codigo
                        st.rerun()


# ================== PANEL: DATOS REGISTRADOS ==================
def panel_datos():
    st.markdown(
        "<h3 style='font-size: 22px; font-weight: 800; color: #0c2340;'>📋 Carnets registrados</h3>",
        unsafe_allow_html=True
    )
    st.markdown("<p style='color:#334155;'>Consulta, busca y administra los carnets registrados.</p>", unsafe_allow_html=True)
    st.markdown("<hr style='border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)

    with st.expander("📷 Escanear carnet con cámara"):
        codigo_escaneado_admin = escaner_qr_camara("camara_admin")
        if codigo_escaneado_admin:
            registro_escaneado = cargar_registro(codigo_escaneado_admin)
            st.success(f"Carnet encontrado: {codigo_escaneado_admin}")
            cesc1, cesc2, cesc3 = st.columns([1, 1, 1])
            with cesc2:
                renderizar_carnet(registro_escaneado)

    registros = []
    for fname in sorted(os.listdir(OS_DIR)):
        if fname.endswith(".json"):
            with open(os.path.join(OS_DIR, fname), "r") as f:
                try:
                    registros.append(json.load(f))
                except json.JSONDecodeError:
                    continue

    if not registros:
        st.info("Aún no hay carnets registrados.")
        return

    busqueda = st.text_input("Buscar por nombre, apellido, DPI o código", placeholder="Escriba para filtrar...")
    if busqueda:
        termino = busqueda.lower()
        registros = [r for r in registros if termino in json.dumps(r, ensure_ascii=False).lower()]

    st.markdown(f"**{len(registros)} registro(s) encontrado(s)**")

    if registros:
        columnas_orden = [c for c in ["codigo", "nombres", "apellidos", "dpi", "fecha_nacimiento", "grado"] if c in registros[0].keys()]

        grados_presentes = {normalizar_grado(r.get("grado")) for r in registros}
        for grado_actual in ordenar_grados_presentes(grados_presentes):
            registros_grado = [r for r in registros if normalizar_grado(r.get("grado")) == grado_actual]
            with st.expander(f"🎓 {grado_actual} — {len(registros_grado)} estudiante(s)", expanded=True):
                df_grupo = pd.DataFrame(registros_grado)[columnas_orden]
                st.caption("👆 Toca el perfil de un estudiante en la tabla para ver su carnet.")
                mostrar_tabla_con_carnet(df_grupo, key_tabla=f"tabla_grado_{grado_actual}")

        st.write("")
        st.markdown("##### Eliminar un registro")
        codigos = [r["codigo"] for r in registros]
        codigo_borrar = st.selectbox("Selecciona el código a eliminar", ["Seleccione..."] + codigos, key="select_borrar")
        if codigo_borrar != "Seleccione...":
            if st.button("Eliminar registro seleccionado", key="btn_eliminar"):
                json_path = os.path.join(OS_DIR, f"{codigo_borrar}.json")
                qr_path = os.path.join(OS_DIR, f"{codigo_borrar}_qr.png")
                if os.path.exists(json_path):
                    os.remove(json_path)
                if os.path.exists(qr_path):
                    os.remove(qr_path)
                st.success(f"Registro '{codigo_borrar}' eliminado correctamente.")
                st.rerun()


# ================== PANEL: ASISTENCIA ==================
def panel_asistencia():
    st.markdown(
        "<h3 style='font-size: 22px; font-weight: 800; color: #0c2340;'>📅 Asistencia estudiantil</h3>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='color:#334155;'>Escanea el código QR del carnet de cada estudiante para registrar su asistencia del día.</p>",
        unsafe_allow_html=True
    )
    st.markdown("<hr style='border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)

    if "asistencia_camera_key" not in st.session_state:
        st.session_state.asistencia_camera_key = 0
    if "asistencia_ultimo_mensaje" not in st.session_state:
        st.session_state.asistencia_ultimo_mensaje = None

    col_cam, col_msg = st.columns([1, 1.3], gap="large")

    with col_cam:
        foto_qr = st.camera_input(
            "Cámara de asistencia",
            key=f"camara_asistencia_{st.session_state.asistencia_camera_key}",
        )

        if foto_qr is not None:
            texto = leer_qr_desde_imagen(foto_qr.getvalue())
            codigo_detectado = extraer_codigo_de_texto_qr(texto)

            if not codigo_detectado:
                st.session_state.asistencia_ultimo_mensaje = (
                    "warning", "No se detectó ningún código QR en la imagen. Intenta acercar más la cámara."
                )
            else:
                registro = cargar_registro(codigo_detectado)
                if not registro:
                    st.session_state.asistencia_ultimo_mensaje = (
                        "warning",
                        f"El código '{codigo_detectado}' no corresponde a ningún carnet registrado.",
                    )
                else:
                    estado, hora = marcar_asistencia(registro)
                    nombre_completo = f"{registro.get('nombres', '')} {registro.get('apellidos', '')}".strip()
                    if estado == "nueva":
                        st.session_state.asistencia_ultimo_mensaje = (
                            "success",
                            f"✅ Asistencia registrada: {nombre_completo} ({registro.get('grado', '')}) a las {hora}.",
                        )
                    else:
                        st.session_state.asistencia_ultimo_mensaje = (
                            "info",
                            f"ℹ️ {nombre_completo} ya tiene asistencia registrada hoy a las {hora}.",
                        )

            # Prepara una cámara nueva y limpia para el siguiente estudiante
            st.session_state.asistencia_camera_key += 1
            st.rerun()

    with col_msg:
        st.write("")
        tipo_msg = st.session_state.asistencia_ultimo_mensaje
        if tipo_msg:
            tipo, texto_msg = tipo_msg
            if tipo == "success":
                st.success(texto_msg)
            elif tipo == "info":
                st.info(texto_msg)
            else:
                st.warning(texto_msg)
        else:
            st.info("Aún no se ha escaneado ningún carnet en esta sesión.")

    st.write("")
    st.markdown("<hr style='border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)

    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    df_asistencias = cargar_asistencias()
    df_hoy = df_asistencias[df_asistencias["fecha"] == fecha_hoy].reset_index(drop=True)

    st.markdown(f"##### Asistencia de hoy ({fecha_hoy}) — {len(df_hoy)} estudiante(s)")

    if df_hoy.empty:
        st.info("Todavía no hay asistencias registradas hoy.")
    else:
        grados_presentes_hoy = {normalizar_grado(g) for g in df_hoy["grado"].tolist()}
        for grado_actual in ordenar_grados_presentes(grados_presentes_hoy):
            df_grupo_hoy = df_hoy[df_hoy["grado"].apply(normalizar_grado) == grado_actual]
            with st.expander(f"🎓 {grado_actual} — {len(df_grupo_hoy)} estudiante(s)", expanded=True):
                st.caption("👆 Toca el perfil de un estudiante en la tabla para ver su carnet.")
                mostrar_tabla_con_carnet(df_grupo_hoy, key_tabla=f"tabla_asistencia_hoy_{grado_actual}")

        st.write("")
        col_desc1, col_desc2 = st.columns(2)
        with col_desc1:
            st.download_button(
                "⬇️ Descargar CSV",
                data=df_hoy.to_csv(index=False).encode("utf-8"),
                file_name=f"asistencia_{fecha_hoy}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_desc2:
            excel_bytes = generar_excel_bytes(df_hoy)
            if excel_bytes is not None:
                st.download_button(
                    "⬇️ Descargar Excel",
                    data=excel_bytes,
                    file_name=f"asistencia_{fecha_hoy}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                st.button(
                    "⬇️ Descargar Excel (falta instalar 'openpyxl')",
                    disabled=True,
                    use_container_width=True,
                )


# ================== PANEL: HISTORIAL MENSUAL DE ASISTENCIA ==================
def panel_historial_asistencia():
    st.markdown(
        "<h3 style='font-size: 22px; font-weight: 800; color: #0c2340;'>🗓️ Historial de asistencia</h3>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='color:#334155;'>Consulta todas las asistencias registradas a lo largo del año, organizadas por mes.</p>",
        unsafe_allow_html=True
    )
    st.markdown("<hr style='border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)

    anio_actual = datetime.now().year
    df = cargar_asistencias()

    if df.empty:
        st.info("Aún no hay asistencias registradas.")
        return

    df = df.copy()
    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce")
    df_anio = df[df["fecha_dt"].dt.year == anio_actual].sort_values("fecha_dt")

    if df_anio.empty:
        st.info(f"No hay asistencias registradas en {anio_actual}.")
        return

    df_anio = df_anio.assign(mes_num=df_anio["fecha_dt"].dt.month)

    st.markdown(f"##### Año {anio_actual} — {len(df_anio)} registro(s) de asistencia en total")

    meses_presentes = sorted(df_anio["mes_num"].unique(), reverse=True)

    for mes_num in meses_presentes:
        df_mes = df_anio[df_anio["mes_num"] == mes_num].drop(columns=["fecha_dt", "mes_num"]).reset_index(drop=True)
        nombre_mes = MESES_ES.get(mes_num, str(mes_num))
        dias_con_registro = df_mes["fecha"].nunique()

        with st.expander(f"📅 {nombre_mes} {anio_actual} — {len(df_mes)} registro(s) en {dias_con_registro} día(s)", expanded=False):
            st.caption("👆 Toca el perfil de un estudiante en la tabla para ver su carnet.")
            grados_presentes_mes = {normalizar_grado(g) for g in df_mes["grado"].tolist()}
            for grado_actual in ordenar_grados_presentes(grados_presentes_mes):
                df_grupo_mes = df_mes[df_mes["grado"].apply(normalizar_grado) == grado_actual]
                st.markdown(f"**🎓 {grado_actual}** — {len(df_grupo_mes)} registro(s)")
                mostrar_tabla_con_carnet(df_grupo_mes, key_tabla=f"tabla_historial_{mes_num}_{grado_actual}")

            st.write("")
            col_dm1, col_dm2 = st.columns(2)
            with col_dm1:
                st.download_button(
                    f"⬇️ Descargar CSV de {nombre_mes}",
                    data=df_mes.to_csv(index=False).encode("utf-8"),
                    file_name=f"asistencia_{anio_actual}_{mes_num:02d}_{nombre_mes}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key=f"csv_mes_{mes_num}",
                )
            with col_dm2:
                excel_bytes_mes = generar_excel_bytes(df_mes)
                if excel_bytes_mes is not None:
                    st.download_button(
                        f"⬇️ Descargar Excel de {nombre_mes}",
                        data=excel_bytes_mes,
                        file_name=f"asistencia_{anio_actual}_{mes_num:02d}_{nombre_mes}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"xlsx_mes_{mes_num}",
                    )
                else:
                    st.button(
                        "⬇️ Excel (falta instalar 'openpyxl')",
                        disabled=True,
                        use_container_width=True,
                        key=f"xlsx_mes_disabled_{mes_num}",
                    )

    st.write("")
    st.markdown("<hr style='border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)
    st.markdown("##### Descargar historial completo del año")
    df_anio_export = df_anio.drop(columns=["fecha_dt", "mes_num"])
    col_da1, col_da2 = st.columns(2)
    with col_da1:
        st.download_button(
            "⬇️ Descargar CSV del año completo",
            data=df_anio_export.to_csv(index=False).encode("utf-8"),
            file_name=f"asistencia_{anio_actual}_completo.csv",
            mime="text/csv",
            use_container_width=True,
            key="csv_anio_completo",
        )
    with col_da2:
        excel_bytes_anio = generar_excel_bytes(df_anio_export)
        if excel_bytes_anio is not None:
            st.download_button(
                "⬇️ Descargar Excel del año completo",
                data=excel_bytes_anio,
                file_name=f"asistencia_{anio_actual}_completo.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="xlsx_anio_completo",
            )
        else:
            st.button(
                "⬇️ Excel del año (falta instalar 'openpyxl')",
                disabled=True,
                use_container_width=True,
                key="xlsx_anio_disabled",
            )


# ================== PANEL: MI CUENTA ==================
def panel_mi_cuenta():
    st.markdown(
        "<h3 style='font-size: 22px; font-weight: 800; color: #0c2340;'>⚙️ Mi cuenta</h3>",
        unsafe_allow_html=True
    )
    st.markdown("<p style='color:#334155;'>Consulta y actualiza tu usuario y contraseña de administrador.</p>", unsafe_allow_html=True)
    st.markdown("<hr style='border: 0; border-top: 1px solid #cbd5e1;'>", unsafe_allow_html=True)

    credenciales = cargar_credenciales_admin()
    st.markdown(f"**Usuario actual:** {credenciales['usuario']}")
    st.write("")

    with st.form("form_cambiar_credenciales"):
        st.markdown("##### Cambiar usuario y/o contraseña")
        password_actual = st.text_input("Contraseña actual", type="password", placeholder="Requerida para confirmar el cambio")
        nuevo_usuario = st.text_input("Nuevo nombre de usuario", value=credenciales["usuario"])
        nueva_password = st.text_input("Nueva contraseña", type="password", placeholder="Déjalo en blanco para no cambiarla")
        confirmar_password = st.text_input("Confirmar nueva contraseña", type="password", placeholder="Repite la nueva contraseña")

        guardar = st.form_submit_button("Guardar cambios", type="primary", use_container_width=True)

        if guardar:
            if not password_actual or hash_password(password_actual) != credenciales["password_hash"]:
                st.error("La contraseña actual es incorrecta.")
            elif not nuevo_usuario:
                st.error("El nombre de usuario no puede estar vacío.")
            elif nueva_password and nueva_password != confirmar_password:
                st.error("La nueva contraseña y su confirmación no coinciden.")
            else:
                password_hash_final = (
                    hash_password(nueva_password) if nueva_password else credenciales["password_hash"]
                )
                guardar_credenciales_admin(nuevo_usuario, password_hash_final)
                st.session_state.username = nuevo_usuario
                st.success("Datos actualizados correctamente.")
                st.rerun()


# ================== FLUJO PRINCIPAL ==================
codigo_desde_qr = st.query_params.get("codigo") or st.session_state.get("codigo_escaneado")

if codigo_desde_qr and not st.session_state.logged_in:
    pantalla_ver_carnet_publico(codigo_desde_qr)

elif st.session_state.pagina == "login_admin" and not st.session_state.logged_in:
    pantalla_login_admin()

elif st.session_state.pagina == "app" and st.session_state.logged_in:
    with st.sidebar:
        st.markdown(f"**Usuario:** {st.session_state.username}")
        st.markdown(f"**Rol:** Administrador")
        st.markdown("---")
        if st.button("Cerrar sesión", use_container_width=True, key="btn_logout"):
            st.session_state.logged_in = False
            st.session_state.rol = None
            st.session_state.username = None
            st.session_state.pagina = "login_admin"
            st.session_state.ultimo_codigo_registrado = None
            st.rerun()

    tab_registro, tab_datos, tab_asistencia, tab_historial, tab_cuenta = st.tabs(
        ["📝 Registrar carnet", "📋 Carnets registrados", "📅 Asistencia", "🗓️ Historial mensual", "⚙️ Mi cuenta"]
    )
    with tab_registro:
        pantalla_registro()
    with tab_datos:
        panel_datos()
    with tab_asistencia:
        panel_asistencia()
    with tab_historial:
        panel_historial_asistencia()
    with tab_cuenta:
        panel_mi_cuenta()

else:
    st.session_state.pagina = "login_admin"
    st.rerun()