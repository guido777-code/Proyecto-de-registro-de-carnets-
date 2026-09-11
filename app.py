import streamlit as st
import streamlit.components.v1 as components
import qrcode
import json
import os
import re
import secrets
import base64
import hashlib
import uuid
import textwrap
import html as html_lib
import urllib.parse as urlparse
import cv2
import numpy as np
import pandas as pd
import string
from io import BytesIO
from datetime import datetime, date

APP_VERSION = "2.1"

st.set_page_config(
    page_title="Registro de Carnet Estudiantil",
    page_icon="🪪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CONFIGURACIÓN
# ============================================================
OS_DIR = os.getenv("CARNETS_DATA_DIR", "datos_carnets")
os.makedirs(OS_DIR, exist_ok=True)

BASE_URL = os.getenv(
    "CARNETS_BASE_URL",
    "http://localhost:8501"
).rstrip("/")

# Todos los archivos de datos se guardan dentro de la carpeta de datos.
CREDENCIALES_FILE = os.path.join(OS_DIR, "credenciales_admin.json")
DOCENTES_FILE = os.path.join(OS_DIR, "docentes.json")
ASISTENCIA_FILE = os.path.join(OS_DIR, "asistencias.csv")

COLUMNAS_ASISTENCIA = [
    "codigo", "nombres", "apellidos", "grado", "fecha", "hora"
]

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre",
    12: "Diciembre",
}

NIVELES_EDUCATIVOS = [
    "Preprimaria",
    "Primaria",
    "Básico",
    "Diversificado – Bachillerato",
    "Diversificado – Magisterio",
]

NOMBRE_COLEGIO_LINEA1 = "COLEGIO MIXTO EVANGÉLICO"
NOMBRE_COLEGIO_LINEA2 = "NAZARENO"
NOMBRE_COLEGIO_LINEA3 = "COBÁN, ALTA VERAPAZ"


# ============================================================
# UTILIDADES GENERALES
# ============================================================
def normalizar_texto(valor):
    return re.sub(r"\s+", " ", str(valor or "").strip())


def normalizar_codigo(codigo):
    return normalizar_texto(codigo).upper()


def normalizar_grado(grado):
    grado = normalizar_texto(grado)
    return grado if grado else "Sin grado"


def ordenar_grados_presentes(grados_presentes):
    extras = sorted(
        {g for g in grados_presentes if g != "Sin grado"},
        key=lambda x: x.casefold()
    )
    return extras + (["Sin grado"] if "Sin grado" in grados_presentes else [])


def codigo_valido(codigo):
    return bool(re.fullmatch(
        r"[A-Za-z0-9_-]{3,30}",
        str(codigo or "").strip()
    ))


def nombre_archivo_seguro(codigo, sufijo, extension):
    codigo_limpio = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        str(codigo).strip()
    )
    extension_limpia = re.sub(
        r"[^A-Za-z0-9]",
        "",
        extension.lower()
    )
    return f"{codigo_limpio}_{sufijo}.{extension_limpia}"


def ruta_registro(codigo):
    return os.path.join(OS_DIR, f"{normalizar_codigo(codigo)}.json")


def codigo_existente(codigo):
    return os.path.exists(ruta_registro(codigo))


def get_base64(bin_file):
    with open(bin_file, "rb") as f:
        return base64.b64encode(f.read()).decode()


def escribir_json_atomico(path, datos):
    """Evita dejar un JSON corrupto si el proceso se interrumpe durante la escritura."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ============================================================
# CONTRASEÑAS
# ============================================================
def hash_password(password):
    salt = secrets.token_bytes(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def verificar_hash_password(password, stored_hash):
    if not password or not stored_hash:
        return False

    if stored_hash.startswith("pbkdf2$"):
        try:
            _, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return secrets.compare_digest(
                digest.hex(),
                digest_hex
            )
        except (ValueError, TypeError):
            return False

    # Compatibilidad con instalaciones antiguas SHA-256.
    legacy = hashlib.sha256(
        password.encode("utf-8")
    ).hexdigest()

    return secrets.compare_digest(legacy, stored_hash)


def cargar_credenciales_admin():
    if not os.path.exists(CREDENCIALES_FILE):
        usuario = os.getenv(
            "CARNETS_DEFAULT_USER",
            "admin.nazareno"
        )
        password_inicial = os.getenv("CARNETS_DEFAULT_PASSWORD")

        # Si no existe una contraseña configurada por entorno,
        # se genera una temporal y se muestra UNA sola vez.
        if not password_inicial:
            password_inicial = secrets.token_urlsafe(10)
            st.session_state.password_inicial_temporal = password_inicial

        datos = {
            "usuario": usuario,
            "password_hash": hash_password(password_inicial),
            "requiere_cambio_password": True,
        }

        try:
            escribir_json_atomico(CREDENCIALES_FILE, datos)
        except OSError:
            st.error("No se pudo crear el archivo de credenciales.")
            st.stop()

        return datos

    try:
        with open(CREDENCIALES_FILE, "r", encoding="utf-8") as f:
            datos = json.load(f)

        if (
            not isinstance(datos, dict)
            or "usuario" not in datos
            or "password_hash" not in datos
        ):
            raise ValueError("Formato de credenciales inválido.")

        return datos

    except (json.JSONDecodeError, OSError, ValueError):
        st.error(
            "No se pudo leer el archivo de credenciales. "
            "Revíselo antes de continuar."
        )
        st.stop()


def guardar_credenciales_admin(
    usuario,
    password_hash_value,
    requiere_cambio_password=False
):
    datos = {
        "usuario": usuario,
        "password_hash": password_hash_value,
        "requiere_cambio_password": requiere_cambio_password,
    }
    escribir_json_atomico(CREDENCIALES_FILE, datos)


def verificar_admin(usuario, password):
    credenciales = cargar_credenciales_admin()

    return (
        secrets.compare_digest(
            normalizar_texto(usuario),
            str(credenciales["usuario"])
        )
        and verificar_hash_password(
            password,
            str(credenciales["password_hash"])
        )
    )


# ============================================================
# GESTIÓN DE DOCENTES
# ============================================================
def cargar_docentes():
    if not os.path.exists(DOCENTES_FILE):
        return []

    try:
        with open(DOCENTES_FILE, "r", encoding="utf-8") as f:
            datos = json.load(f)

        return datos if isinstance(datos, list) else []

    except (json.JSONDecodeError, OSError):
        return []


def guardar_docentes(docentes):
    escribir_json_atomico(DOCENTES_FILE, docentes)


# ============================================================
# CARNETS
# ============================================================
def cargar_registro(codigo):
    codigo = normalizar_codigo(codigo)

    if not codigo_valido(codigo):
        return None

    path = ruta_registro(codigo)

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            datos = json.load(f)

        return datos if isinstance(datos, dict) else None

    except (json.JSONDecodeError, OSError):
        return None


def listar_registros():
    registros = []

    try:
        archivos = sorted(os.listdir(OS_DIR))
    except OSError:
        return registros

    for fname in archivos:
        if not fname.lower().endswith(".json"):
            continue

        # Ignorar archivos internos.
        if fname in {
            "credenciales_admin.json",
            "docentes.json",
        }:
            continue

        path = os.path.join(OS_DIR, fname)

        try:
            with open(path, "r", encoding="utf-8") as f:
                datos = json.load(f)

            if isinstance(datos, dict) and datos.get("codigo"):
                registros.append(datos)

        except (json.JSONDecodeError, OSError):
            continue

    return registros


def buscar_duplicado_por_dpi(dpi):
    dpi_normalizado = normalizar_texto(dpi).lower().replace(" ", "")

    if not dpi_normalizado or dpi_normalizado == "noaplica":
        return None

    for registro in listar_registros():
        dpi_existente = (
            normalizar_texto(registro.get("dpi"))
            .lower()
            .replace(" ", "")
        )

        if (
            dpi_existente
            and dpi_existente != "noaplica"
            and dpi_existente == dpi_normalizado
        ):
            return registro

    return None


def generar_codigo_aleatorio(longitud=7):
    caracteres = string.ascii_uppercase + string.digits

    for _ in range(1000):
        codigo = "".join(
            secrets.choice(caracteres)
            for _ in range(longitud)
        )

        if not codigo_existente(codigo):
            return codigo

    raise RuntimeError(
        "No fue posible generar un código único."
    )


# ============================================================
# ASISTENCIA
# ============================================================
def cargar_asistencias():
    if not os.path.exists(ASISTENCIA_FILE):
        return pd.DataFrame(columns=COLUMNAS_ASISTENCIA)

    try:
        df = pd.read_csv(
            ASISTENCIA_FILE,
            dtype=str,
            encoding="utf-8-sig"
        )

    except (pd.errors.EmptyDataError, FileNotFoundError):
        return pd.DataFrame(columns=COLUMNAS_ASISTENCIA)

    for col in COLUMNAS_ASISTENCIA:
        if col not in df.columns:
            df[col] = ""

    return df[COLUMNAS_ASISTENCIA].fillna("")


def guardar_asistencias(df):
    salida = df.copy()

    for col in COLUMNAS_ASISTENCIA:
        if col not in salida.columns:
            salida[col] = ""

    salida = salida[COLUMNAS_ASISTENCIA].fillna("").astype(str)

    tmp = f"{ASISTENCIA_FILE}.tmp"
    salida.to_csv(
        tmp,
        index=False,
        encoding="utf-8-sig"
    )
    os.replace(tmp, ASISTENCIA_FILE)


def registrar_asistencia_codigo(codigo):
    codigo = normalizar_codigo(codigo)

    datos = cargar_registro(codigo)

    if not datos:
        return False, "Código no registrado en la base de datos."

    df = cargar_asistencias()

    ahora = datetime.now()
    fecha_hoy = ahora.strftime("%Y-%m-%d")
    hora_actual = ahora.strftime("%H:%M:%S")

    ya_registrado = not df[
        (df["codigo"].str.upper() == codigo)
        & (df["fecha"] == fecha_hoy)
    ].empty

    if ya_registrado:
        nombre = normalizar_texto(
            f"{datos.get('nombres', '')} {datos.get('apellidos', '')}"
        )
        return (
            False,
            f"El estudiante {nombre} ya registró su asistencia hoy."
        )

    nueva_fila = {
        "codigo": codigo,
        "nombres": datos.get("nombres", ""),
        "apellidos": datos.get("apellidos", ""),
        "grado": datos.get("grado", ""),
        "fecha": fecha_hoy,
        "hora": hora_actual,
    }

    df = pd.concat(
        [df, pd.DataFrame([nueva_fila])],
        ignore_index=True
    )

    guardar_asistencias(df)

    nombre = normalizar_texto(
        f"{datos.get('nombres', '')} {datos.get('apellidos', '')}"
    )

    return (
        True,
        f"Asistencia registrada: {nombre} "
        f"({datos.get('grado', 'Sin grado')})"
    )


# ============================================================
# EXCEL
# ============================================================
def generar_excel_bytes(
    df,
    titulo_reporte="HISTORIAL DE ASISTENCIA"
):
    try:
        import openpyxl
        from openpyxl.styles import (
            Font, PatternFill, Alignment, Border, Side
        )
        from openpyxl.drawing.image import Image
        from openpyxl.utils import get_column_letter

    except ImportError:
        st.error(
            "Falta la librería openpyxl. "
            "Instálela con: pip install openpyxl"
        )
        return None

    df = df.copy()

    for col in COLUMNAS_ASISTENCIA:
        if col not in df.columns:
            df[col] = ""

    df = df[COLUMNAS_ASISTENCIA].fillna("")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Historial Asistencia"
    ws.freeze_panes = "B8"
    ws.sheet_view.showGridLines = True

    # Logo
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        try:
            img = Image(LOGO_PATH)
            img.width = 85
            img.height = 85
            ws.add_image(img, "B2")
        except Exception:
            pass

    ws["D2"] = "COLEGIO MIXTO EVANGÉLICO NAZARENO"
    ws["D2"].font = Font(
        name="Calibri",
        size=15,
        bold=True,
        color="002060"
    )

    ws["D3"] = "COBÁN, ALTA VERAPAZ"
    ws["D3"].font = Font(
        name="Calibri",
        size=10,
        bold=True,
        color="595959"
    )

    ws["D4"] = titulo_reporte.upper()
    ws["D4"].font = Font(
        name="Calibri",
        size=12,
        bold=True,
        color="1F4E79"
    )

    fila_encabezado = 7
    columna_inicio = 2

    fill_header = PatternFill(
        start_color="1F4E79",
        end_color="1F4E79",
        fill_type="solid"
    )

    font_header = Font(
        name="Calibri",
        size=11,
        bold=True,
        color="FFFFFF"
    )

    fill_zebra = PatternFill(
        start_color="F2F5F9",
        end_color="F2F5F9",
        fill_type="solid"
    )

    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
    )

    headers = [
        "Código",
        "Nombres",
        "Apellidos",
        "Grado",
        "Fecha",
        "Hora",
    ]

    for idx, text in enumerate(headers):
        col = columna_inicio + idx
        cell = ws.cell(
            row=fila_encabezado,
            column=col,
            value=text
        )
        cell.fill = fill_header
        cell.font = font_header
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )
        cell.border = thin_border

    for row_idx, row_data in enumerate(
        df.to_dict(orient="records")
    ):
        fila_actual = fila_encabezado + 1 + row_idx

        valores = [
            row_data.get("codigo", ""),
            row_data.get("nombres", ""),
            row_data.get("apellidos", ""),
            row_data.get("grado", ""),
            row_data.get("fecha", ""),
            row_data.get("hora", ""),
        ]

        for col_idx, valor in enumerate(valores):
            col = columna_inicio + col_idx

            cell = ws.cell(
                row=fila_actual,
                column=col,
                value=str(valor)
            )

            cell.font = Font(
                name="Calibri",
                size=10
            )
            cell.border = thin_border

            if row_idx % 2 == 1:
                cell.fill = fill_zebra

            cell.alignment = Alignment(
                horizontal=(
                    "center"
                    if col_idx in [0, 4, 5]
                    else "left"
                ),
                vertical="center"
            )

    for col_idx in range(
        columna_inicio,
        columna_inicio + len(headers)
    ):
        col_letter = get_column_letter(col_idx)
        max_len = 0

        for row in range(
            fila_encabezado,
            ws.max_row + 1
        ):
            value = ws.cell(
                row=row,
                column=col_idx
            ).value

            if value is not None:
                max_len = max(
                    max_len,
                    len(str(value))
                )

        ws.column_dimensions[col_letter].width = max(
            min(max_len + 4, 45),
            12
        )

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return buffer.getvalue()


# ============================================================
# FOTOS Y CARNET
# ============================================================
def obtener_foto_base64(nombre_foto):
    if not nombre_foto:
        return None

    ruta = os.path.join(OS_DIR, os.path.basename(nombre_foto))

    if not os.path.exists(ruta):
        return None

    extension = (
        os.path.splitext(nombre_foto)[1]
        .lower()
        .replace(".", "")
    )

    mime = {
        "jpg": "jpeg",
        "jpeg": "jpeg",
        "png": "png",
    }.get(extension)

    if not mime:
        return None

    try:
        with open(ruta, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        return f"data:image/{mime};base64,{b64}"

    except OSError:
        return None


def renderizar_carnet(datos):
    nombres = html_lib.escape(
        str(datos.get("nombres", ""))
    )
    apellidos = html_lib.escape(
        str(datos.get("apellidos", ""))
    )
    codigo = html_lib.escape(
        str(datos.get("codigo", ""))
    )
    grado = html_lib.escape(
        str(datos.get("grado", ""))
    )

    foto_b64 = obtener_foto_base64(
        datos.get("foto")
    )

    qr_path = os.path.join(
        OS_DIR,
        f"{normalizar_codigo(datos.get('codigo', ''))}_qr.png"
    )

    qr_b64 = (
        get_base64(qr_path)
        if os.path.exists(qr_path)
        else ""
    )

    logo_b64 = ""

    if LOGO_PATH and os.path.exists(LOGO_PATH):
        ext_logo = (
            os.path.splitext(LOGO_PATH)[1]
            .lower()
            .replace(".", "")
        )

        mime_logo = (
            "jpeg"
            if ext_logo in {"jpg", "jpeg"}
            else "png"
        )

        logo_b64 = (
            f"data:image/{mime_logo};base64,"
            f"{get_base64(LOGO_PATH)}"
        )

    if foto_b64:
        img_foto = (
            '<img src="'
            f'{foto_b64}'
            '" style="width:130px;height:150px;'
            'object-fit:cover;border-radius:12px;'
            'border:3px solid #fff;" />'
        )
    else:
        img_foto = (
            '<div style="width:130px;height:150px;'
            'border-radius:12px;background:#e2e8f0;'
            'display:flex;align-items:center;'
            'justify-content:center;font-size:40px;'
            'border:3px solid #fff;">👤</div>'
        )

    img_qr = (
        f'<img src="data:image/png;base64,{qr_b64}" '
        'style="width:65px;height:65px;border-radius:6px;'
        'background:white;padding:2px;" />'
        if qr_b64
        else ""
    )

    logo_img = (
        f'<img src="{logo_b64}" '
        'style="width:40px;height:40px;'
        'border-radius:50%;background:white;padding:2px;" />'
        if logo_b64
        else ""
    )

    html_content = textwrap.dedent(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background: transparent;
                    font-family: sans-serif;
                    display: flex;
                    justify-content: center;
                }}

                .card {{
                    width: 300px;
                    border-radius: 20px;
                    background:
                        linear-gradient(
                            160deg,
                            #0c2340 0%,
                            #0066ff 100%
                        );
                    padding: 18px;
                    color: #ffffff;
                    box-shadow:
                        0 8px 20px rgba(0,0,0,0.3);
                    box-sizing: border-box;
                }}

                .header {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 8px;
                }}

                .title {{
                    text-align: left;
                    font-size: 11px;
                    font-weight: bold;
                    line-height: 1.2;
                }}

                .subtitle {{
                    text-align: left;
                    margin-bottom: 10px;
                }}

                .sub-label {{
                    font-size: 9px;
                    opacity: 0.8;
                }}

                .sub-year {{
                    font-size: 15px;
                    font-weight: bold;
                }}

                .photo-container {{
                    display: flex;
                    justify-content: center;
                    margin-bottom: 10px;
                }}

                .footer {{
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-end;
                    text-align: left;
                    gap: 8px;
                }}

                .field-label {{
                    font-size: 8px;
                    opacity: 0.8;
                }}

                .field-val {{
                    font-size: 13px;
                    font-weight: bold;
                    margin-bottom: 4px;
                }}
            </style>
        </head>

        <body>
            <div class="card">
                <div class="header">
                    {logo_img}
                    <div class="title">
                        Colegio Mixto<br>
                        Evangélico Nazareno
                    </div>
                </div>

                <div class="subtitle">
                    <div class="sub-label">
                        Carnet estudiantil
                    </div>
                    <div class="sub-year">
                        Ciclo escolar {datetime.now().year}
                    </div>
                </div>

                <div class="photo-container">
                    {img_foto}
                </div>

                <div class="footer">
                    <div>
                        <div class="field-label">CÓDIGO</div>
                        <div class="field-val">
                            {codigo}
                        </div>

                        <div class="field-label">
                            NOMBRE
                        </div>
                        <div class="field-val">
                            {nombres}<br>{apellidos}
                        </div>

                        <div class="field-label">
                            GRADO
                        </div>
                        <div
                            class="field-val"
                            style="margin-bottom:0;"
                        >
                            {grado}
                        </div>
                    </div>

                    <div>
                        {img_qr}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    )

    components.html(
        html_content,
        height=440
    )


def mostrar_tabla_con_carnet(
    df_tabla,
    key_tabla
):
    if df_tabla.empty:
        st.info("No hay registros para mostrar.")
        return

    df_tabla = df_tabla.reset_index(drop=True)

    columnas_visibles = [
        c for c in [
            "codigo",
            "nombres",
            "apellidos",
            "grado",
            "fecha",
            "hora",
        ]
        if c in df_tabla.columns
    ]

    df_visual = df_tabla[columnas_visibles]

    evento = st.dataframe(
        df_visual,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=key_tabla,
    )

    filas = []

    if evento is not None:
        try:
            filas = list(
                evento.selection.rows
            )
        except AttributeError:
            try:
                filas = evento.selection.get(
                    "rows",
                    []
                )
            except AttributeError:
                filas = []

    if filas and "codigo" in df_visual.columns:
        codigo_tocado = df_visual.iloc[
            filas[0]
        ]["codigo"]

        datos_tocados = cargar_registro(
            codigo_tocado
        )

        if datos_tocados:
            st.write("")

            c1, c2, c3 = st.columns(3)

            with c2:
                renderizar_carnet(
                    datos_tocados
                )


# ============================================================
# LOGO / FONDO
# ============================================================
LOGO_PATH = os.getenv(
    "CARNETS_LOGO_PATH",
    "logo_colegio_nazareno.png"
)

if not os.path.exists(LOGO_PATH):
    LOGO_PATH = None

    for ext in [
        "logo.png",
        "logo.jpg",
        "logo.jpeg"
    ]:
        if os.path.exists(ext):
            LOGO_PATH = ext
            break

FONDO_PATH = None

for ext in [
    "fondo.jpg",
    "fondo.jpeg",
    "fondo.png"
]:
    if os.path.exists(ext):
        FONDO_PATH = ext
        break


# ============================================================
# ESTADO DE SESIÓN
# ============================================================
defaults = {
    "pagina": "login_admin",
    "logged_in": False,
    "rol": None,
    "username": None,
    "ultimo_codigo_registrado": None,
    "codigo_escaneado": None,
    "modo_oscuro": False,
    "docente_editando": None,
    "vista_actual": "inicio",
    "password_inicial_temporal": None,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# TEMA
# ============================================================
MODO_OSCURO = st.session_state.modo_oscuro

if MODO_OSCURO:
    PALETA = {
        "texto": "#F4F7FB",
        "texto_suave": "#A8B3C7",
        "fondo_gradiente": (
            "radial-gradient(circle at 15% 0%, rgba(47,111,237,.16), transparent 30%), "
            "linear-gradient(135deg,#07111F 0%,#0B172A 48%,#101E35 100%)"
        ),
        "input_bg": "#111F33",
        "input_borde": "#30445F",
        "placeholder": "#71809A",
        "primario": "#4F8CFF",
        "primario_texto": "#FFFFFF",
        "secundario_bg": "#132238",
        "card_bg": "rgba(15,29,49,.94)",
        "card_borde": "rgba(110,145,190,.20)",
        "sidebar_bg": "#071426",
        "sidebar_texto": "#D8E2F0",
        "sidebar_activo_bg": "#2F6FED",
        "sidebar_hover_bg": "#102744",
        "badge_bg": "#12233B",
        "hr_color": "rgba(125,151,184,.18)",
    }
else:
    PALETA = {
        "texto": "#102A43",
        "texto_suave": "#62748A",
        "fondo_gradiente": (
            "radial-gradient(circle at 12% 0%, rgba(47,111,237,.12), transparent 30%), "
            "linear-gradient(135deg,#F5F9FE 0%,#EEF5FC 48%,#E5F0FA 100%)"
        ),
        "input_bg": "#FFFFFF",
        "input_borde": "#D8E3EF",
        "placeholder": "#9AA9BB",
        "primario": "#246BCE",
        "primario_texto": "#FFFFFF",
        "secundario_bg": "#FFFFFF",
        "card_bg": "rgba(255,255,255,.94)",
        "card_borde": "rgba(31,73,125,.10)",
        "sidebar_bg": "#0B2A50",
        "sidebar_texto": "#E5EEF8",
        "sidebar_activo_bg": "#2F6FED",
        "sidebar_hover_bg": "#143B69",
        "badge_bg": "#F1F6FC",
        "hr_color": "rgba(31,73,125,.10)",
    }

st.markdown(
    f"""
    <style>
    /* ========================================================
       IDENTIDAD VISUAL PROFESIONAL
       Solo estilos: no modifica la lógica de la aplicación.
       ======================================================== */

    :root {{
        --primary: {PALETA["primario"]};
        --text: {PALETA["texto"]};
        --muted: {PALETA["texto_suave"]};
        --surface: {PALETA["card_bg"]};
        --surface-2: {PALETA["input_bg"]};
        --border: {PALETA["card_borde"]};
        --input-border: {PALETA["input_borde"]};
        --sidebar: {PALETA["sidebar_bg"]};
        --sidebar-text: {PALETA["sidebar_texto"]};
        --sidebar-active: {PALETA["sidebar_activo_bg"]};
        --sidebar-hover: {PALETA["sidebar_hover_bg"]};
        --shadow-sm: 0 4px 14px rgba(15,42,82,.06);
        --shadow-md: 0 14px 38px rgba(15,42,82,.10);
        --shadow-lg: 0 22px 60px rgba(15,42,82,.14);
        --radius: 18px;
    }}

    * {{
        box-sizing: border-box;
    }}

    html, body, [data-testid="stAppViewContainer"] {{
        background: {PALETA["fondo_gradiente"]} !important;
    }}

    [data-testid="stAppViewContainer"] {{
        min-height: 100vh;
    }}

    [data-testid="stHeader"] {{
        background: transparent !important;
        height: 0 !important;
    }}

    [data-testid="stToolbar"] {{
        visibility: hidden;
        height: 0;
    }}

    .block-container {{
        max-width: 1320px !important;
        padding: 1.35rem 2rem 2.8rem !important;
    }}

    h1, h2, h3, h4, h5, h6, label, p,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stCaptionContainer"] {{
        color: {PALETA["texto"]} !important;
        font-family: "Segoe UI", Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif !important;
    }}

    h1, h2, h3, h4, h5, h6 {{
        letter-spacing: -.02em;
    }}

    h1 {{ font-weight: 800 !important; }}
    h2, h3 {{ font-weight: 750 !important; }}

    hr {{
        border: 0 !important;
        border-top: 1px solid {PALETA["hr_color"]} !important;
        margin: 1.15rem 0 !important;
    }}

    /* Tarjetas */
    .card-panel,
    .login-card {{
        position: relative;
        background: {PALETA["card_bg"]} !important;
        border: 1px solid {PALETA["card_borde"]} !important;
        border-radius: var(--radius) !important;
        box-shadow: var(--shadow-md) !important;
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
    }}

    .card-panel {{
        padding: 28px 30px !important;
        margin-bottom: 20px !important;
    }}

    .login-card {{
        padding: 42px !important;
        box-shadow: var(--shadow-lg) !important;
    }}

    .card-panel::before,
    .login-card::before {{
        content: "";
        position: absolute;
        top: 0;
        left: 24px;
        right: 24px;
        height: 2px;
        border-radius: 999px;
        background: linear-gradient(90deg, transparent, var(--primary), transparent);
        opacity: .55;
        pointer-events: none;
    }}

    /* Inputs */
    div[data-baseweb="input"],
    div[data-baseweb="base-input"],
    div[data-baseweb="select"] > div,
    [data-testid="stTextInput"] input,
    [data-testid="stDateInput"] input,
    input[type="text"],
    input[type="password"],
    input[type="date"] {{
        background: {PALETA["input_bg"]} !important;
        color: {PALETA["texto"]} !important;
        border-color: {PALETA["input_borde"]} !important;
        border-radius: 12px !important;
        min-height: 44px;
        transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
    }}

    div[data-baseweb="input"]:focus-within,
    div[data-baseweb="base-input"]:focus-within,
    [data-testid="stTextInput"]:focus-within,
    [data-testid="stDateInput"]:focus-within {{
        border-color: var(--primary) !important;
        box-shadow: 0 0 0 3px rgba(47,111,237,.12) !important;
    }}

    input::placeholder {{
        color: {PALETA["placeholder"]} !important;
    }}

    div[data-baseweb="select"] svg,
    div[data-baseweb="datepicker"] svg,
    [data-testid="stDateInput"] svg,
    [data-testid="stSelectbox"] svg {{
        fill: {PALETA["texto"]} !important;
    }}

    /* Selectores / popovers */
    div[data-baseweb="popover"] ul[role="listbox"],
    div[data-baseweb="popover"] div[data-baseweb="calendar"],
    div[data-baseweb="menu"] {{
        background: {PALETA["input_bg"]} !important;
        border: 1px solid {PALETA["input_borde"]} !important;
        border-radius: 12px !important;
        box-shadow: var(--shadow-lg) !important;
    }}

    div[data-baseweb="popover"] ul[role="listbox"] *,
    div[data-baseweb="popover"] div[data-baseweb="calendar"] *,
    div[data-baseweb="menu"] * {{
        color: {PALETA["texto"]} !important;
    }}

    div[data-baseweb="popover"] li[aria-selected="true"],
    div[data-baseweb="popover"] div[aria-selected="true"] {{
        background: rgba(47,111,237,.12) !important;
    }}

    /* Botones */
    div.stButton > button,
    div.stDownloadButton > button,
    div.stFormSubmitButton > button {{
        min-height: 44px !important;
        border-radius: 12px !important;
        padding: 0 18px !important;
        font-weight: 700 !important;
        letter-spacing: .01em;
        transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease !important;
    }}

    div.stButton > button:hover,
    div.stDownloadButton > button:hover,
    div.stFormSubmitButton > button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(15,42,82,.12) !important;
    }}

    div.stButton > button[kind="primary"],
    div.stDownloadButton > button,
    div.stFormSubmitButton > button[kind="primary"] {{
        background: linear-gradient(135deg, {PALETA["primario"]}, #4F8CFF) !important;
        color: #FFFFFF !important;
        border: 0 !important;
        box-shadow: 0 7px 18px rgba(47,111,237,.22) !important;
    }}

    div.stButton > button[kind="secondary"],
    div.stFormSubmitButton > button[kind="secondary"] {{
        background: {PALETA["secundario_bg"]} !important;
        color: {PALETA["texto"]} !important;
        border: 1px solid {PALETA["input_borde"]} !important;
    }}

    /* Métricas */
    [data-testid="stMetric"] {{
        background: linear-gradient(145deg, rgba(255,255,255,.05), rgba(255,255,255,0));
        border: 1px solid {PALETA["card_borde"]};
        border-radius: 14px;
        padding: 16px 18px;
        box-shadow: var(--shadow-sm);
    }}

    [data-testid="stMetricLabel"] {{
        color: {PALETA["texto_suave"]} !important;
        font-weight: 600 !important;
    }}

    [data-testid="stMetricValue"] {{
        color: {PALETA["texto"]} !important;
        font-weight: 800 !important;
    }}

    /* Alertas */
    [data-testid="stAlert"] {{
        border-radius: 13px !important;
        border: 1px solid {PALETA["card_borde"]} !important;
        box-shadow: var(--shadow-sm) !important;
    }}

    /* Expander */
    [data-testid="stExpander"] {{
        background: {PALETA["card_bg"]} !important;
        border: 1px solid {PALETA["card_borde"]} !important;
        border-radius: 14px !important;
        overflow: hidden;
        box-shadow: var(--shadow-sm) !important;
    }}

    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] details > summary {{
        background: transparent !important;
    }}

    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary * {{
        color: {PALETA["texto"]} !important;
        font-weight: 700 !important;
    }}

    /* Sidebar */
    [data-testid="stSidebar"],
    [data-testid="stSidebarContent"] {{
        background: linear-gradient(180deg, {PALETA["sidebar_bg"]} 0%, #0D3764 100%) !important;
        border-right: 1px solid rgba(255,255,255,.06) !important;
    }}

    [data-testid="stSidebar"] * {{
        color: {PALETA["sidebar_texto"]} !important;
    }}

    [data-testid="stSidebar"] hr {{
        border-top: 1px solid rgba(255,255,255,.11) !important;
    }}

    [data-testid="stSidebar"] div.stButton > button {{
        width: 100%;
        min-height: 45px !important;
        background: transparent !important;
        border: 1px solid transparent !important;
        color: #FFFFFF !important;
        text-align: left !important;
        justify-content: flex-start !important;
        opacity: 1 !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
        padding: 10px 14px !important;
        margin: 2px 0 !important;
        box-shadow: none !important;
    }}

    /* Refuerzo de contraste: evita que Streamlit aplique texto oscuro a los botones secundarios */
    [data-testid="stSidebar"] div.stButton > button,
    [data-testid="stSidebar"] div.stButton > button *,
    [data-testid="stSidebar"] div.stButton > button[kind="secondary"],
    [data-testid="stSidebar"] div.stButton > button[kind="secondary"] * {{
        color: #FFFFFF !important;
        opacity: 1 !important;
    }}

    [data-testid="stSidebar"] div.stButton > button:hover {{
        background: {PALETA["sidebar_hover_bg"]} !important;
        border-color: rgba(255,255,255,.06) !important;
        transform: translateX(2px);
        box-shadow: none !important;
    }}

    [data-testid="stSidebar"] div.stButton > button[kind="primary"] {{
        background: linear-gradient(135deg, {PALETA["sidebar_activo_bg"]}, #4F8CFF) !important;
        color: #FFFFFF !important;
        box-shadow: 0 8px 20px rgba(47,111,237,.22) !important;
    }}

    [data-testid="stSidebar"] div.stButton > button p {{
        text-align: left !important;
        font-weight: 650 !important;
    }}

    .sidebar-nombre-colegio {{
        line-height: 1.2;
        margin: 8px 0 14px;
        padding: 0 4px;
    }}

    .sidebar-nombre-colegio .l1 {{
        font-size: 10px;
        font-weight: 700;
        letter-spacing: .08em;
        opacity: .72;
    }}

    .sidebar-nombre-colegio .l2 {{
        font-size: 22px;
        font-weight: 850;
        letter-spacing: .03em;
    }}

    .sidebar-nombre-colegio .l3 {{
        font-size: 9px;
        opacity: .62;
        letter-spacing: .13em;
        margin-top: 3px;
    }}

    /* Usuario y barra superior */
    .badge-usuario {{
        background: {PALETA["badge_bg"]} !important;
        color: {PALETA["texto"]} !important;
        border: 1px solid {PALETA["card_borde"]} !important;
        border-radius: 999px !important;
        padding: 8px 15px !important;
        font-size: 13px;
        font-weight: 700;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        white-space: nowrap;
        box-shadow: var(--shadow-sm);
    }}

    .badge-usuario span {{
        color: {PALETA["texto"]} !important;
    }}

    /* Cámara y carga de archivos */
    [data-testid="stCameraInput"],
    [data-testid="stFileUploader"] section {{
        background: {PALETA["input_bg"]} !important;
        border: 1px dashed {PALETA["input_borde"]} !important;
        border-radius: 13px !important;
    }}

    [data-testid="stCameraInput"] p,
    [data-testid="stCameraInput"] span,
    [data-testid="stCameraInput"] label,
    [data-testid="stFileUploader"] p,
    [data-testid="stFileUploader"] span {{
        color: {PALETA["texto"]} !important;
    }}

    /* Dataframes */
    [data-testid="stDataFrame"] {{
        border: 1px solid {PALETA["card_borde"]} !important;
        border-radius: 14px !important;
        overflow: hidden !important;
        box-shadow: var(--shadow-sm);
    }}

    /* Tabs */
    [data-baseweb="tab-list"] {{
        gap: 6px !important;
        border-bottom: 1px solid {PALETA["hr_color"]} !important;
    }}

    [data-baseweb="tab-list"] button[data-baseweb="tab"],
    [data-baseweb="tab-list"] [role="tab"] {{
        min-height: 46px !important;
        padding: 10px 16px !important;
        border-radius: 10px 10px 0 0 !important;
        color: {PALETA["texto_suave"]} !important;
        font-weight: 650 !important;
    }}

    [data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"],
    [data-baseweb="tab-list"] [role="tab"][aria-selected="true"] {{
        color: var(--primary) !important;
        background: rgba(47,111,237,.07) !important;
    }}

    /* Responsive */
    @media (max-width: 900px) {{
        .block-container {{
            padding: 1rem 1rem 2rem !important;
        }}
        .card-panel, .login-card {{
            padding: 22px !important;
        }}
        .sidebar-nombre-colegio .l2 {{
            font-size: 19px;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True
)


# BARRA SUPERIOR
# ============================================================
def barra_superior():
    _, col_der = st.columns([6, 1.6])

    with col_der:
        c1, c2 = st.columns([3.4, 1], gap="small")

        with c1:
            st.markdown(
                f"""
                <div class='badge-usuario'>
                    👤 Usuario: {html_lib.escape(
                        str(st.session_state.username or "")
                    )}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with c2:
            icono_tema = (
                "☀️"
                if MODO_OSCURO
                else "🌙"
            )

            if st.button(
                icono_tema,
                key="btn_toggle_tema",
                help="Cambiar tema"
            ):
                st.session_state.modo_oscuro = (
                    not st.session_state.modo_oscuro
                )
                st.rerun()

    st.write("")


# ============================================================
# LOGIN
# ============================================================
def pantalla_login_admin():
    col_a, col_b, col_c = st.columns(
        [1, 1.2, 1]
    )

    with col_b:
        st.markdown(
            "<div class='login-card'>",
            unsafe_allow_html=True
        )

        if LOGO_PATH:
            lc1, lc2, lc3 = st.columns(3)

            with lc2:
                st.image(
                    LOGO_PATH,
                    width=110
                )

        st.markdown(
            """
            <h2 style='text-align:center;
                       font-size:24px;
                       font-weight:800;'>
                Acceso de administrador
            </h2>
            """,
            unsafe_allow_html=True
        )

        # Carga las credenciales para poder mostrar el aviso
        # de primera configuración.
        credenciales = cargar_credenciales_admin()

        if (
            credenciales.get("requiere_cambio_password")
            and st.session_state.password_inicial_temporal
        ):
            st.warning(
                "Primera configuración: su contraseña temporal es:"
            )
            st.code(
                st.session_state.password_inicial_temporal,
                language=None
            )
            st.caption(
                "Después de iniciar sesión, cámbiela desde "
                "⚙️ Mi cuenta."
            )

        usuario = st.text_input(
            "Usuario",
            placeholder="Ingrese su usuario",
            key="login_usuario"
        )

        password = st.text_input(
            "Contraseña",
            placeholder="Ingrese su contraseña",
            type="password",
            key="login_password"
        )

        if st.button(
            "Ingresar",
            type="primary",
            use_container_width=True,
            key="btn_login"
        ):
            if verificar_admin(
                usuario,
                password
            ):
                st.session_state.logged_in = True
                st.session_state.rol = "admin"
                st.session_state.username = (
                    normalizar_texto(usuario)
                )
                st.session_state.pagina = "app"

                # No volver a mostrar la contraseña temporal
                # después de entrar.
                st.session_state.password_inicial_temporal = None

                st.rerun()

            else:
                st.error(
                    "Usuario o contraseña incorrectos."
                )

        st.markdown(
            "</div>",
            unsafe_allow_html=True
        )


# ============================================================
# CARNET PÚBLICO
# ============================================================
def pantalla_ver_carnet_publico(codigo):
    codigo = normalizar_codigo(codigo)

    col_a, col_b, col_c = st.columns(
        [1, 1.3, 1]
    )

    with col_b:
        if LOGO_PATH:
            lc1, lc2, lc3 = st.columns(3)

            with lc2:
                st.image(
                    LOGO_PATH,
                    width=100
                )

        datos = cargar_registro(codigo)

        if not datos:
            st.error(
                "No se encontró ningún carnet con ese código."
            )
        else:
            renderizar_carnet(datos)

        if st.button(
            "Ir al inicio",
            use_container_width=True,
            key="btn_volver_publico"
        ):
            st.query_params.clear()
            st.session_state.codigo_escaneado = None
            st.session_state.pagina = "login_admin"
            st.rerun()


# ============================================================
# DASHBOARD
# ============================================================
def panel_inicio():
    total_carnets = len(listar_registros())
    total_docentes = len(cargar_docentes())

    df_asis = cargar_asistencias()
    fecha_hoy = datetime.now().strftime(
        "%Y-%m-%d"
    )

    asistencias_hoy = int(
        (df_asis["fecha"] == fecha_hoy).sum()
    ) if not df_asis.empty else 0

    col_izq, col_der = st.columns(
        [5, 7],
        gap="large"
    )

    with col_izq:
        if LOGO_PATH:
            st.image(
                LOGO_PATH,
                width=170
            )

        st.markdown(
            """
            <h1 style='font-size:36px;
                       font-weight:800;'>
                Bienvenido de<br>
                nuevo
            </h1>
            """,
            unsafe_allow_html=True
        )

        st.markdown(
            f"""
            <p style='font-size:16px;'>
                Panel de control del sistema de carnet
                y asistencia estudiantil del
                {NOMBRE_COLEGIO_LINEA2.title()}.
            </p>
            """,
            unsafe_allow_html=True
        )

        st.caption(
            f"Versión del sistema: {APP_VERSION}"
        )

    with col_der:
        st.markdown(
            "<div class='card-panel'>",
            unsafe_allow_html=True
        )

        st.markdown(
            "### 📊 Resumen general"
        )

        m1, m2, m3 = st.columns(3)

        m1.metric(
            "🪪 Carnets registrados",
            total_carnets
        )

        m2.metric(
            "✅ Asistencias hoy",
            asistencias_hoy
        )

        m3.metric(
            "👩‍🏫 Docentes",
            total_docentes
        )

        st.markdown(
            "</div>",
            unsafe_allow_html=True
        )

        st.markdown(
            "<div class='card-panel'>",
            unsafe_allow_html=True
        )

        st.markdown(
            "### 🚀 Accesos rápidos"
        )

        b1, b2, b3 = st.columns(3)

        with b1:
            if st.button(
                "📝 Registrar carnet",
                use_container_width=True
            ):
                st.session_state.vista_actual = "registro"
                st.session_state.ultimo_codigo_registrado = None
                st.rerun()

        with b2:
            if st.button(
                "📅 Ir a asistencia",
                use_container_width=True
            ):
                st.session_state.vista_actual = "asistencia"
                st.rerun()

        with b3:
            if st.button(
                "📋 Ver carnets",
                use_container_width=True
            ):
                st.session_state.vista_actual = "datos"
                st.rerun()

        st.markdown(
            "</div>",
            unsafe_allow_html=True
        )


# ============================================================
# REGISTRO DE CARNET
# ============================================================
def pantalla_registro():
    if st.session_state.ultimo_codigo_registrado:
        st.markdown(
            """
            <h2 style='text-align:center;'>
                ¡Carnet registrado con éxito! ✅
            </h2>
            """,
            unsafe_allow_html=True
        )

        datos = cargar_registro(
            st.session_state.ultimo_codigo_registrado
        )

        if datos:
            c1, c2, c3 = st.columns(3)

            with c2:
                renderizar_carnet(datos)

        if st.button(
            "Registrar otro carnet",
            use_container_width=True
        ):
            st.session_state.ultimo_codigo_registrado = None
            st.rerun()

        return

    col_izq, col_der = st.columns(
        [5, 7],
        gap="large"
    )

    with col_izq:
        if LOGO_PATH:
            st.image(
                LOGO_PATH,
                width=170
            )

        st.markdown(
            """
            <h1 style='font-size:38px;
                       font-weight:800;'>
                Registro de<br>
                Carnet estudiantil
            </h1>
            """,
            unsafe_allow_html=True
        )

        st.markdown(
            """
            <p style='font-size:16px;'>
                Completa el formulario para registrar
                el carnet estudiantil.
            </p>
            """,
            unsafe_allow_html=True
        )

    with col_der:
        st.markdown(
            "<div class='card-panel'>",
            unsafe_allow_html=True
        )

        st.markdown(
            "### 👤 Datos personales"
        )

        c1, c2 = st.columns(2)

        with c1:
            nombres = st.text_input(
                "Nombres *",
                placeholder="Ingrese nombres",
                key="registro_nombres"
            )

        with c2:
            apellidos = st.text_input(
                "Apellidos *",
                placeholder="Ingrese apellidos",
                key="registro_apellidos"
            )

        c3, c4 = st.columns(2)

        with c3:
            dpi = st.text_input(
                "DPI",
                placeholder="Opcional",
                key="registro_dpi"
            )

        with c4:
            fecha_nac = st.date_input(
                "Fecha de nacimiento *",
                value=None,
                min_value=date(1995, 1, 1),
                max_value=date.today(),
                key="registro_fecha_nac"
            )

        st.markdown(
            "### 📝 Información académica"
        )

        c5, c6 = st.columns(2)

        with c5:
            carnet_actual = st.text_input(
                "No. de carnet actual (si tiene)",
                placeholder="Opcional",
                key="registro_carnet_actual"
            )

        with c6:
            nivel_seleccionado = st.selectbox(
                "Nivel educativo *",
                ["Seleccione el nivel"]
                + NIVELES_EDUCATIVOS,
                key="registro_nivel"
            )

        docentes_registrados = cargar_docentes()

        docentes_filtrados = [
            d for d in docentes_registrados
            if nivel_seleccionado in d.get(
                "niveles", []
            )
        ]

        docente_seleccionado = None
        materia_seleccionada = None

        if nivel_seleccionado != "Seleccione el nivel":
            st.markdown("---")
            st.markdown(
                "### 👩‍🏫 Docente y Materia Asignada"
            )

            if not docentes_filtrados:
                st.info(
                    "No hay docentes registrados "
                    f"asignados al nivel: "
                    f"**{nivel_seleccionado}**"
                )
            else:
                c_doc, c_mat = st.columns(2)

                nombres_docentes = [
                    "Seleccione docente"
                ] + [
                    d.get("nombre", "")
                    for d in docentes_filtrados
                ]

                with c_doc:
                    nombre_doc_elegido = st.selectbox(
                        "Docente asignado",
                        nombres_docentes,
                        key="registro_docente"
                    )

                with c_mat:
                    if (
                        nombre_doc_elegido
                        != "Seleccione docente"
                    ):
                        docente_obj = next(
                            (
                                d for d
                                in docentes_filtrados
                                if d.get("nombre")
                                == nombre_doc_elegido
                            ),
                            None
                        )

                        if docente_obj:
                            docente_seleccionado = (
                                docente_obj.get(
                                    "nombre"
                                )
                            )

                            materias_docente = (
                                docente_obj.get(
                                    "materias",
                                    []
                                )
                            )

                            materia_seleccionada = (
                                st.selectbox(
                                    "Materia",
                                    [
                                        "Seleccione materia"
                                    ] + materias_docente,
                                    key="registro_materia"
                                )
                            )

        st.markdown("---")
        st.markdown(
            "### 🎓 Grado actual"
        )

        grado = st.text_input(
            "Escriba el grado manualmente",
            placeholder=(
                "Ej. Primero Básico – Sección A"
            ),
            key="registro_grado"
        )

        foto_estudiante = st.file_uploader(
            "Foto del estudiante *",
            type=["png", "jpg", "jpeg"],
            key="registro_foto"
        )

        if foto_estudiante is not None:
            st.image(
                foto_estudiante,
                width=140
            )

        st.write("")

        if st.button(
            "Registrar carnet",
            type="primary",
            use_container_width=True,
            key="btn_registrar_carnet"
        ):
            nombres_limpios = normalizar_texto(nombres)
            apellidos_limpios = normalizar_texto(apellidos)
            grado_limpio = normalizar_texto(grado)

            if not nombres_limpios or not apellidos_limpios:
                st.error(
                    "Ingrese Nombres y Apellidos."
                )

            elif nivel_seleccionado == "Seleccione el nivel":
                st.error(
                    "Seleccione el nivel educativo."
                )

            elif not grado_limpio:
                st.error(
                    "Ingrese el grado del estudiante."
                )

            elif fecha_nac is None:
                st.error(
                    "Ingrese la fecha de nacimiento."
                )

            elif foto_estudiante is None:
                st.error(
                    "Suba una foto del estudiante."
                )

            else:
                dpi_final = (
                    normalizar_texto(dpi)
                    if normalizar_texto(dpi)
                    else "No aplica"
                )

                duplicado = (
                    buscar_duplicado_por_dpi(
                        dpi_final
                    )
                    if dpi_final != "No aplica"
                    else None
                )

                if duplicado:
                    st.error(
                        "Este DPI ya está registrado "
                        f"con el código "
                        f"{duplicado.get('codigo', '')}."
                    )

                else:
                    codigo = (
                        normalizar_codigo(
                            carnet_actual
                        )
                        if normalizar_texto(
                            carnet_actual
                        )
                        else generar_codigo_aleatorio()
                    )

                    if not codigo_valido(codigo):
                        st.error(
                            "El número de carnet debe tener "
                            "entre 3 y 30 caracteres y usar "
                            "solo letras, números, guion "
                            "o guion bajo."
                        )
                        return

                    if codigo_existente(codigo):
                        st.error(
                            f"Ya existe un carnet con "
                            f"el código {codigo}. "
                            "Use otro código."
                        )
                        return

                    ext_foto = (
                        os.path.splitext(
                            foto_estudiante.name
                        )[1]
                        .lower()
                        .replace(".", "")
                    )

                    if ext_foto not in {
                        "jpg",
                        "jpeg",
                        "png"
                    }:
                        st.error(
                            "Formato de foto no permitido."
                        )
                        return

                    contenido_foto = (
                        foto_estudiante.getvalue()
                    )

                    if len(contenido_foto) > 5 * 1024 * 1024:
                        st.error(
                            "La foto supera el límite de 5 MB."
                        )
                        return

                    nombre_foto = nombre_archivo_seguro(
                        codigo,
                        "foto",
                        ext_foto
                    )

                    ruta_foto = os.path.join(
                        OS_DIR,
                        nombre_foto
                    )

                    datos = {
                        "nombres": nombres_limpios,
                        "apellidos": apellidos_limpios,
                        "dpi": dpi_final,
                        "fecha_nacimiento": str(fecha_nac),
                        "codigo": codigo,
                        "grado": grado_limpio,
                        "nivel": nivel_seleccionado,
                        "docente": (
                            docente_seleccionado
                            or "No asignado"
                        ),
                        "materia": (
                            materia_seleccionada
                            if (
                                materia_seleccionada
                                and materia_seleccionada
                                != "Seleccione materia"
                            )
                            else "No asignada"
                        ),
                    }

                    # Guardar foto primero.
                    try:
                        with open(
                            ruta_foto,
                            "wb"
                        ) as f:
                            f.write(contenido_foto)
                    except OSError:
                        st.error(
                            "No se pudo guardar la foto."
                        )
                        return

                    datos["foto"] = nombre_foto

                    # QR público.
                    url_destinatario = (
                        f"{BASE_URL}/"
                        f"?codigo="
                        f"{urlparse.quote(codigo)}"
                    )

                    qr = qrcode.QRCode(
                        version=None,
                        error_correction=qrcode.constants.ERROR_CORRECT_M,
                        box_size=10,
                        border=3
                    )

                    qr.add_data(
                        url_destinatario
                    )
                    qr.make(fit=True)

                    img_qr = qr.make_image(
                        fill_color="black",
                        back_color="white"
                    )

                    ruta_qr = os.path.join(
                        OS_DIR,
                        f"{codigo}_qr.png"
                    )

                    try:
                        img_qr.save(
                            ruta_qr
                        )
                    except OSError:
                        # Si falla el QR, eliminar la foto
                        # para no dejar archivos huérfanos.
                        try:
                            os.remove(ruta_foto)
                        except OSError:
                            pass

                        st.error(
                            "No se pudo generar el código QR."
                        )
                        return

                    # Guardar registro al final.
                    try:
                        escribir_json_atomico(
                            ruta_registro(codigo),
                            datos
                        )
                    except OSError:
                        for archivo in [
                            ruta_foto,
                            ruta_qr
                        ]:
                            try:
                                os.remove(archivo)
                            except OSError:
                                pass

                        st.error(
                            "No se pudo guardar el registro."
                        )
                        return

                    st.session_state.ultimo_codigo_registrado = codigo
                    st.rerun()

        st.markdown(
            "</div>",
            unsafe_allow_html=True
        )


# ============================================================
# DOCENTES
# ============================================================
def panel_docentes():
    st.markdown(
        "### 👩‍🏫 Registro y Gestión de Docentes"
    )

    docentes = cargar_docentes()

    if st.session_state.docente_editando is not None:
        doc_edit = next(
            (
                d for d in docentes
                if d.get("id")
                == st.session_state.docente_editando
            ),
            None
        )

        if doc_edit:
            st.markdown(
                "#### ✏️ Editar Docente"
            )

            with st.form(
                "form_editar_docente"
            ):
                niveles_edit = st.multiselect(
                    "Nivel(es) Educativo(s) *",
                    NIVELES_EDUCATIVOS,
                    default=doc_edit.get(
                        "niveles",
                        []
                    )
                )

                materias_edit = st.text_input(
                    "Materias que imparte "
                    "(separadas por comas) *",
                    value=", ".join(
                        doc_edit.get(
                            "materias",
                            []
                        )
                    )
                )

                nombre_edit = st.text_input(
                    "Docente encargado "
                    "(Nombre completo) *",
                    value=doc_edit.get(
                        "nombre",
                        ""
                    )
                )

                col_e1, col_e2 = st.columns(2)

                with col_e1:
                    guardar_edit = (
                        st.form_submit_button(
                            "Guardar Cambios",
                            type="primary",
                            use_container_width=True
                        )
                    )

                with col_e2:
                    cancelar_edit = (
                        st.form_submit_button(
                            "Cancelar",
                            use_container_width=True
                        )
                    )

                if guardar_edit:
                    nombre_limpio = normalizar_texto(
                        nombre_edit
                    )

                    lista_materias = [
                        normalizar_texto(m)
                        for m in materias_edit.split(",")
                        if normalizar_texto(m)
                    ]

                    existe_otro = any(
                        d.get("id")
                        != doc_edit.get("id")
                        and normalizar_texto(
                            d.get("nombre", "")
                        ).casefold()
                        == nombre_limpio.casefold()
                        for d in docentes
                    )

                    if not niveles_edit:
                        st.error(
                            "Seleccione al menos un nivel."
                        )

                    elif not lista_materias:
                        st.error(
                            "Ingrese al menos una materia."
                        )

                    elif not nombre_limpio:
                        st.error(
                            "El nombre no puede estar vacío."
                        )

                    elif existe_otro:
                        st.error(
                            "Ya existe otro docente "
                            "con ese nombre."
                        )

                    else:
                        doc_edit["nombre"] = nombre_limpio
                        doc_edit["materias"] = lista_materias
                        doc_edit["niveles"] = niveles_edit

                        guardar_docentes(
                            docentes
                        )

                        st.session_state.docente_editando = None

                        st.success(
                            "Docente actualizado exitosamente."
                        )

                        st.rerun()

                if cancelar_edit:
                    st.session_state.docente_editando = None
                    st.rerun()

    else:
        with st.expander(
            "➕ Registrar Nuevo Docente",
            expanded=True
        ):
            with st.form(
                "form_nuevo_docente",
                clear_on_submit=True
            ):
                niveles_docente = st.multiselect(
                    "Nivel(es) Educativo(s) *",
                    NIVELES_EDUCATIVOS
                )

                materias_input = st.text_input(
                    "Materias que imparte "
                    "(separadas por comas) *",
                    placeholder=(
                        "Ej. Matemáticas, Física, Biología"
                    )
                )

                nombre_docente = st.text_input(
                    "Docente encargado "
                    "(Nombre completo) *",
                    placeholder=(
                        "Ej. Prof. Juan Carlos López"
                    )
                )

                guardar = st.form_submit_button(
                    "Guardar Docente",
                    type="primary"
                )

                if guardar:
                    nombre_limpio = normalizar_texto(
                        nombre_docente
                    )

                    lista_materias = [
                        normalizar_texto(m)
                        for m in materias_input.split(",")
                        if normalizar_texto(m)
                    ]

                    existe = any(
                        normalizar_texto(
                            d.get("nombre", "")
                        ).casefold()
                        == nombre_limpio.casefold()
                        for d in docentes
                    )

                    if not niveles_docente:
                        st.error(
                            "Seleccione al menos un nivel."
                        )

                    elif not lista_materias:
                        st.error(
                            "Ingrese al menos una materia."
                        )

                    elif not nombre_limpio:
                        st.error(
                            "Ingrese el nombre del docente."
                        )

                    elif existe:
                        st.error(
                            "Ya existe un docente "
                            "registrado con ese nombre."
                        )

                    else:
                        nuevo_docente = {
                            "id": uuid.uuid4().hex[:12],
                            "nombre": nombre_limpio,
                            "materias": lista_materias,
                            "niveles": niveles_docente,
                        }

                        docentes.append(
                            nuevo_docente
                        )

                        guardar_docentes(
                            docentes
                        )

                        st.success(
                            f"Docente '{nombre_limpio}' "
                            "registrado exitosamente."
                        )

                        st.rerun()

    st.markdown("---")
    st.markdown(
        "### 📋 Docentes Registrados"
    )

    if not docentes:
        st.info(
            "No hay docentes registrados."
        )
        return

    for idx, doc in enumerate(docentes):
        with st.container():
            cd1, cd2, cd3 = st.columns(
                [3, 3, 2]
            )

            with cd1:
                st.markdown(
                    "**Niveles que imparte:**"
                )
                st.caption(
                    ", ".join(
                        doc.get("niveles", [])
                    )
                )

                st.caption(
                    "**Materias:** "
                    + ", ".join(
                        doc.get("materias", [])
                    )
                )

            with cd2:
                st.markdown(
                    "**👨‍🏫 Docente encargado:** "
                    f"{doc.get('nombre', '')}"
                )

            with cd3:
                cbtn1, cbtn2 = st.columns(2)

                with cbtn1:
                    if st.button(
                        "✏️ Editar",
                        key=f"edit_doc_{doc.get('id')}",
                        use_container_width=True
                    ):
                        st.session_state.docente_editando = (
                            doc.get("id")
                        )
                        st.rerun()

                with cbtn2:
                    if st.button(
                        "🗑️ Eliminar",
                        key=f"del_doc_{doc.get('id')}",
                        use_container_width=True
                    ):
                        docentes.pop(idx)

                        guardar_docentes(
                            docentes
                        )

                        if (
                            st.session_state.docente_editando
                            == doc.get("id")
                        ):
                            st.session_state.docente_editando = None

                        st.success(
                            "Docente eliminado."
                        )

                        st.rerun()

        st.divider()


# ============================================================
# CARNETS REGISTRADOS
# ============================================================
def panel_datos():
    st.markdown(
        "### 📋 Carnets registrados"
    )

    registros = listar_registros()

    if not registros:
        st.info(
            "Aún no hay carnets registrados."
        )
        return

    busqueda = st.text_input(
        "Buscar por nombre, apellido, DPI o código",
        placeholder="Escriba para filtrar...",
        key="buscar_carnet"
    )

    if busqueda:
        termino = normalizar_texto(
            busqueda
        ).casefold()

        registros = [
            r for r in registros
            if termino in (
                f"{r.get('codigo', '')} "
                f"{r.get('nombres', '')} "
                f"{r.get('apellidos', '')} "
                f"{r.get('dpi', '')} "
                f"{r.get('grado', '')}"
            ).casefold()
        ]

    if not registros:
        st.warning(
            "No se encontraron estudiantes."
        )
        return

    grados_presentes = {
        normalizar_grado(
            r.get("grado")
        )
        for r in registros
    }

    for grado_actual in ordenar_grados_presentes(
        grados_presentes
    ):
        registros_grado = [
            r for r in registros
            if normalizar_grado(
                r.get("grado")
            ) == grado_actual
        ]

        with st.expander(
            f"🎓 {grado_actual} — "
            f"{len(registros_grado)} estudiante(s)",
            expanded=True
        ):
            df_grupo = pd.DataFrame(
                registros_grado
            )

            mostrar_tabla_con_carnet(
                df_grupo,
                key_tabla=(
                    "tabla_grado_"
                    + re.sub(
                        r"[^A-Za-z0-9_-]",
                        "_",
                        grado_actual
                    )
                )
            )


# ============================================================
# ASISTENCIA
# ============================================================
def extraer_codigo_desde_qr(valor_qr):
    valor_qr = normalizar_texto(
        valor_qr
    )

    if not valor_qr:
        return None

    try:
        parsed = urlparse.urlparse(
            valor_qr
        )

        query_codigo = (
            urlparse.parse_qs(
                parsed.query
            ).get("codigo", [None])[0]
        )

        if query_codigo:
            return normalizar_codigo(
                query_codigo
            )

    except Exception:
        pass

    return normalizar_codigo(
        valor_qr
    )


def panel_asistencia():
    st.markdown(
        "### 📅 Asistencia estudiantil"
    )

    with st.expander(
        "📷 Escanear QR con Cámara / "
        "Buscador Manual",
        expanded=True
    ):
        col_cam, col_manual = st.columns(2)

        with col_cam:
            st.markdown(
                "#### 📸 Cámara web"
            )

            foto_cam = st.camera_input(
                "Apunte el código QR a la cámara",
                key="camara_qr"
            )

            if foto_cam is not None:
                bytes_data = foto_cam.getvalue()

                cv2_img = cv2.imdecode(
                    np.frombuffer(
                        bytes_data,
                        np.uint8
                    ),
                    cv2.IMREAD_COLOR
                )

                if cv2_img is None:
                    st.error(
                        "No se pudo leer la imagen."
                    )
                else:
                    detector = cv2.QRCodeDetector()

                    try:
                        val, pts, qr_code = (
                            detector.detectAndDecode(
                                cv2_img
                            )
                        )
                    except cv2.error:
                        val = ""

                    if val:
                        codigo = (
                            extraer_codigo_desde_qr(
                                val
                            )
                        )

                        if not codigo or not codigo_valido(
                            codigo
                        ):
                            st.error(
                                "El QR detectado no contiene "
                                "un código de carnet válido."
                            )
                        else:
                            exito, msg = (
                                registrar_asistencia_codigo(
                                    codigo
                                )
                            )

                            if exito:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.warning(msg)

                    else:
                        st.error(
                            "No se pudo detectar un código QR "
                            "válido en la imagen. "
                            "Intente nuevamente."
                        )

        with col_manual:
            st.markdown(
                "#### 🔍 Buscar estudiante / "
                "Lector USB"
            )

            registros = listar_registros()

            todos_estudiantes = []
            grados_unicos = set()

            for datos_est in registros:
                cod = datos_est.get(
                    "codigo",
                    ""
                )
                nom = datos_est.get(
                    "nombres",
                    ""
                )
                ape = datos_est.get(
                    "apellidos",
                    ""
                )
                grd = normalizar_grado(
                    datos_est.get(
                        "grado",
                        ""
                    )
                )

                todos_estudiantes.append({
                    "codigo": cod,
                    "nombre_completo": (
                        f"{cod} - {nom} {ape}"
                    ),
                    "grado": grd,
                })

                grados_unicos.add(grd)

            grados_ordenados = (
                ["-- Todos los grados --"]
                + ordenar_grados_presentes(
                    grados_unicos
                )
            )

            grado_seleccionado = st.selectbox(
                "Filtrar por Grado / Sección:",
                options=grados_ordenados,
                key="select_filtro_grado_asistencia"
            )

            if (
                grado_seleccionado
                == "-- Todos los grados --"
            ):
                estudiantes_filtrados = (
                    todos_estudiantes
                )
            else:
                estudiantes_filtrados = [
                    e for e
                    in todos_estudiantes
                    if e["grado"]
                    == grado_seleccionado
                ]

            opciones_estudiantes = {
                "-- Seleccione estudiante --": None
            }

            for est in sorted(
                estudiantes_filtrados,
                key=lambda x: x[
                    "nombre_completo"
                ].casefold()
            ):
                opciones_estudiantes[
                    est["nombre_completo"]
                ] = est["codigo"]

            estudiante_elegido = st.selectbox(
                "Seleccione estudiante",
                options=list(
                    opciones_estudiantes.keys()
                ),
                key="select_asistencia_manual"
            )

            if st.button(
                "Registrar asistencia",
                type="primary",
                use_container_width=True,
                key="btn_asistencia_manual"
            ):
                codigo_sel = (
                    opciones_estudiantes.get(
                        estudiante_elegido
                    )
                )

                if codigo_sel:
                    exito, msg = (
                        registrar_asistencia_codigo(
                            codigo_sel
                        )
                    )

                    if exito:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.warning(msg)

                else:
                    st.error(
                        "Seleccione un estudiante válido."
                    )

    st.markdown("---")

    fecha_hoy = datetime.now().strftime(
        "%Y-%m-%d"
    )

    df_asistencias = cargar_asistencias()

    df_hoy = df_asistencias[
        df_asistencias["fecha"]
        == fecha_hoy
    ].reset_index(drop=True)

    if df_hoy.empty:
        st.info(
            "Todavía no hay asistencias registradas hoy."
        )
        return

    grados_presentes_hoy = {
        normalizar_grado(g)
        for g in df_hoy["grado"].tolist()
    }

    for grado_actual in ordenar_grados_presentes(
        grados_presentes_hoy
    ):
        df_grupo_hoy = df_hoy[
            df_hoy["grado"].apply(
                normalizar_grado
            )
            == grado_actual
        ]

        with st.expander(
            f"🎓 {grado_actual} — "
            f"{len(df_grupo_hoy)} estudiante(s)",
            expanded=True
        ):
            mostrar_tabla_con_carnet(
                df_grupo_hoy,
                key_tabla=(
                    "tabla_asistencia_hoy_"
                    + re.sub(
                        r"[^A-Za-z0-9_-]",
                        "_",
                        grado_actual
                    )
                )
            )

    col_desc1, col_desc2 = st.columns(2)

    with col_desc1:
        st.download_button(
            "⬇️ Descargar CSV",
            data=df_hoy.to_csv(
                index=False
            ).encode("utf-8-sig"),
            file_name=(
                f"asistencia_{fecha_hoy}.csv"
            ),
            mime="text/csv",
            use_container_width=True,
            key="download_csv_hoy"
        )

    with col_desc2:
        excel_bytes = generar_excel_bytes(
            df_hoy,
            titulo_reporte=(
                "REPORTE DE ASISTENCIA DIARIA "
                f"({fecha_hoy})"
            )
        )

        if excel_bytes is not None:
            st.download_button(
                "📊 Descargar Excel Profesional",
                data=excel_bytes,
                file_name=(
                    f"asistencia_{fecha_hoy}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
                use_container_width=True,
                key="download_excel_hoy"
            )


# ============================================================
# HISTORIAL
# ============================================================
def panel_historial_asistencia():
    st.markdown(
        "### 🗓️ Historial de asistencia"
    )

    anio_actual = datetime.now().year
    df = cargar_asistencias()

    if df.empty:
        st.info(
            "Aún no hay asistencias registradas."
        )
        return

    df = df.copy()

    df["fecha_dt"] = pd.to_datetime(
        df["fecha"],
        errors="coerce"
    )

    df_anio = (
        df[
            df["fecha_dt"].dt.year
            == anio_actual
        ]
        .sort_values(
            ["fecha_dt", "hora"]
        )
    )

    if df_anio.empty:
        st.info(
            f"No hay asistencias registradas "
            f"en {anio_actual}."
        )
        return

    df_anio = df_anio.assign(
        mes_num=df_anio["fecha_dt"].dt.month
    )

    meses_presentes = sorted(
        df_anio["mes_num"].dropna().unique(),
        reverse=True
    )

    for mes_num in meses_presentes:
        mes_num = int(mes_num)

        df_mes = (
            df_anio[
                df_anio["mes_num"]
                == mes_num
            ]
            .drop(
                columns=["fecha_dt", "mes_num"]
            )
            .reset_index(drop=True)
        )

        nombre_mes = MESES_ES.get(
            mes_num,
            str(mes_num)
        )

        with st.expander(
            f"📅 {nombre_mes} {anio_actual} — "
            f"{len(df_mes)} registro(s)",
            expanded=True
        ):
            grados_presentes_mes = {
                normalizar_grado(g)
                for g in df_mes["grado"].tolist()
            }

            for grado_actual in ordenar_grados_presentes(
                grados_presentes_mes
            ):
                df_grupo_mes = df_mes[
                    df_mes["grado"].apply(
                        normalizar_grado
                    )
                    == grado_actual
                ]

                st.markdown(
                    f"**🎓 {grado_actual}**"
                )

                mostrar_tabla_con_carnet(
                    df_grupo_mes,
                    key_tabla=(
                        "tabla_historial_"
                        f"{mes_num}_"
                        + re.sub(
                            r"[^A-Za-z0-9_-]",
                            "_",
                            grado_actual
                        )
                    )
                )

            st.markdown("---")
            st.markdown(
                f"### 📥 Descargar reportes "
                f"de {nombre_mes} {anio_actual}"
            )

            col_csv, col_excel = st.columns(2)

            with col_csv:
                csv_mes = df_mes.to_csv(
                    index=False
                ).encode("utf-8-sig")

                st.download_button(
                    label=(
                        f"⬇️ Descargar CSV "
                        f"de {nombre_mes}"
                    ),
                    data=csv_mes,
                    file_name=(
                        f"asistencia_{anio_actual}_"
                        f"{mes_num:02d}_{nombre_mes}.csv"
                    ),
                    mime="text/csv",
                    use_container_width=True,
                    key=(
                        f"btn_csv_historial_"
                        f"{mes_num}"
                    ),
                )

            with col_excel:
                excel_bytes_mes = (
                    generar_excel_bytes(
                        df_mes,
                        titulo_reporte=(
                            "REPORTE DE ASISTENCIA - "
                            f"{nombre_mes.upper()} "
                            f"{anio_actual}"
                        )
                    )
                )

                if excel_bytes_mes is not None:
                    st.download_button(
                        label=(
                            f"📊 Descargar Excel "
                            f"Profesional de "
                            f"{nombre_mes}"
                        ),
                        data=excel_bytes_mes,
                        file_name=(
                            f"asistencia_{anio_actual}_"
                            f"{mes_num:02d}_"
                            f"{nombre_mes}.xlsx"
                        ),
                        mime=(
                            "application/vnd.openxmlformats-"
                            "officedocument.spreadsheetml.sheet"
                        ),
                        use_container_width=True,
                        type="primary",
                        key=(
                            f"btn_excel_profesional_"
                            f"{mes_num}"
                        ),
                    )


# ============================================================
# MI CUENTA
# ============================================================
def panel_mi_cuenta():
    st.markdown(
        "### ⚙️ Mi cuenta"
    )

    credenciales = cargar_credenciales_admin()

    st.markdown(
        f"**Usuario actual:** "
        f"{html_lib.escape(str(credenciales['usuario']))}"
    )

    if credenciales.get(
        "requiere_cambio_password",
        False
    ):
        st.warning(
            "Por seguridad, debe cambiar la "
            "contraseña inicial."
        )

    with st.form(
        "form_cambiar_credenciales"
    ):
        password_actual = st.text_input(
            "Contraseña actual",
            type="password"
        )

        nuevo_usuario = st.text_input(
            "Nuevo nombre de usuario",
            value=str(
                credenciales["usuario"]
            )
        )

        nueva_password = st.text_input(
            "Nueva contraseña",
            type="password"
        )

        confirmar_password = st.text_input(
            "Confirmar nueva contraseña",
            type="password"
        )

        guardar = st.form_submit_button(
            "Guardar cambios",
            type="primary",
            use_container_width=True
        )

        if guardar:
            # IMPORTANTE:
            # NO se vuelve a generar un hash para comparar
            # porque PBKDF2 usa una sal aleatoria.
            if not verificar_hash_password(
                password_actual,
                str(
                    credenciales["password_hash"]
                )
            ):
                st.error(
                    "La contraseña actual es incorrecta."
                )

            elif (
                nueva_password
                and len(nueva_password) < 8
            ):
                st.error(
                    "La nueva contraseña debe tener "
                    "al menos 8 caracteres."
                )

            elif (
                nueva_password
                and nueva_password
                != confirmar_password
            ):
                st.error(
                    "Las contraseñas no coinciden."
                )

            elif not normalizar_texto(
                nuevo_usuario
            ):
                st.error(
                    "El usuario no puede quedar vacío."
                )

            else:
                password_hash_final = (
                    hash_password(
                        nueva_password
                    )
                    if nueva_password
                    else credenciales["password_hash"]
                )

                guardar_credenciales_admin(
                    normalizar_texto(
                        nuevo_usuario
                    ),
                    password_hash_final,
                    requiere_cambio_password=False
                )

                st.session_state.username = (
                    normalizar_texto(
                        nuevo_usuario
                    )
                )

                st.session_state.password_inicial_temporal = None

                st.success(
                    "Datos actualizados correctamente."
                )

                st.rerun()


# ============================================================
# NAVEGACIÓN
# ============================================================
NAV_ITEMS = [
    ("inicio", "🏠", "Inicio", panel_inicio),
    ("registro", "📝", "Registrar carnet", pantalla_registro),
    ("docentes", "👩‍🏫", "Docentes", panel_docentes),
    ("datos", "📋", "Carnets registrados", panel_datos),
    ("asistencia", "📅", "Asistencia", panel_asistencia),
    ("historial", "🗓️", "Historial mensual", panel_historial_asistencia),
    ("cuenta", "⚙️", "Mi cuenta", panel_mi_cuenta),
]


def renderizar_sidebar():
    with st.sidebar:
        if LOGO_PATH:
            st.image(
                LOGO_PATH,
                width=56
            )

        st.markdown(
            f"""
            <div class='sidebar-nombre-colegio'>
                <div class='l1'>
                    {NOMBRE_COLEGIO_LINEA1}
                </div>
                <div class='l2'>
                    {NOMBRE_COLEGIO_LINEA2}
                </div>
                <div class='l3'>
                    {NOMBRE_COLEGIO_LINEA3}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.write("")

        for (
            clave,
            icono,
            etiqueta,
            _
        ) in NAV_ITEMS:

            activo = (
                st.session_state.vista_actual
                == clave
            )

            if st.button(
                f"{icono}   {etiqueta}",
                key=f"nav_{clave}",
                use_container_width=True,
                type=(
                    "primary"
                    if activo
                    else "secondary"
                )
            ):
                st.session_state.vista_actual = clave
                st.session_state.docente_editando = None
                st.rerun()

        st.markdown(
            "<hr>",
            unsafe_allow_html=True
        )

        if st.button(
            "⏻   Cerrar sesión",
            key="btn_logout",
            use_container_width=True
        ):
            st.query_params.clear()

            st.session_state.logged_in = False
            st.session_state.rol = None
            st.session_state.username = None
            st.session_state.pagina = "login_admin"
            st.session_state.vista_actual = "inicio"
            st.session_state.ultimo_codigo_registrado = None
            st.session_state.docente_editando = None

            st.rerun()


# ============================================================
# FLUJO PRINCIPAL
# ============================================================
codigo_desde_qr = (
    st.query_params.get("codigo")
    or st.session_state.get(
        "codigo_escaneado"
    )
)

if (
    codigo_desde_qr
    and not st.session_state.logged_in
):
    pantalla_ver_carnet_publico(
        codigo_desde_qr
    )

elif (
    st.session_state.pagina == "login_admin"
    and not st.session_state.logged_in
):
    pantalla_login_admin()

elif (
    st.session_state.pagina == "app"
    and st.session_state.logged_in
):
    renderizar_sidebar()
    barra_superior()

    funciones_por_vista = {
        clave: funcion
        for clave, _, _, funcion
        in NAV_ITEMS
    }

    vista = (
        st.session_state.vista_actual
        if st.session_state.vista_actual
        in funciones_por_vista
        else "inicio"
    )

    funciones_por_vista[vista]()

else:
    st.session_state.pagina = "login_admin"
    st.session_state.logged_in = False
    st.rerun()
