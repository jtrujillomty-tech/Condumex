import os
import re
import glob
import zipfile
import smtplib
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from playwright.sync_api import Playwright, sync_playwright
from PyPDF2 import PdfMerger

# Módulos para correo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# --- 1. INSTALACIÓN DE NAVEGADOR PARA LA NUBE ---
@st.cache_resource
def instalar_navegador():
    """Instala Chromium automáticamente en el servidor de Streamlit"""
    os.system("playwright install chromium")

instalar_navegador()
load_dotenv()

# --- CONFIGURACIÓN DE CREDENCIALES ---
# Streamlit usa st.secrets en la nube, pero fallback a os.getenv localmente
USUARIO_F1HR = os.environ.get("FACTURACION1HR_USER") or st.secrets.get("FACTURACION1HR_USER")
PASSWORD_F1HR = os.environ.get("FACTURACION1HR_PASS") or st.secrets.get("FACTURACION1HR_PASS")
SMTP_USER = os.environ.get("SMTP_USER") or st.secrets.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS") or st.secrets.get("SMTP_PASS")

CARPETA_BASE = "Envios_Facturacion"
os.makedirs(CARPETA_BASE, exist_ok=True)

CLIENTES_CONDUMEX = [
    "10825-CONDUMEX SA DE CV", "10188-EQUITER SA DE CV", "10824-ARCOMEX SA DE CV",
    "9193-ARNESES ELECTRICOS AUTOMOTRICES SA DE CV", "10249-CORDAFLEX SA DE CV",
    "10826-NACIONAL DE COBRE SA DE CV", "10861-OPERADORA CICSA SA DE CV",
    "10866-CONALUM SA DE CV", "10864-CONCENSOL SA DE CV", "10867-CONTICON SA DE CV",
    "10865-PRECITUBO SA DE CV", "10964-ARNESES ELECTRONICOS ARNELEC SA DE CV"
]

CORREOS_DEFAULT = [
    "nerojas.mty@aduax.com",
    "jaguirre.mty@aduax.com",
    "splatas.mty@aduax.com",
    "jtrujillo.mty@aduax.com"
]

DESTINATARIOS_POR_CLIENTE = {}

def obtener_referencia_o_pedimento(carpeta_factura, ref_operativa):
    archivos = os.listdir(carpeta_factura)
    for archivo in archivos:
        match = re.search(r'(\d{15,16})', archivo)
        if match:
            return match.group(1)
    if pd.notna(ref_operativa):
        return str(ref_operativa).strip().replace("/", "-")
    return "SIN_REF"

def enviar_correo_expediente(cliente_limpio, folio, ref_pedimento, carpeta_factura):
    destinatarios = DESTINATARIOS_POR_CLIENTE.get(cliente_limpio, CORREOS_DEFAULT)
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = ", ".join(destinatarios)
    msg['Subject'] = f"{folio};{ref_pedimento};{cliente_limpio}"
    
    cuerpo = "Buen dia, se comparte expediente en el acomodo solicitado.\n\nSaludos"
    msg.attach(MIMEText(cuerpo, 'plain'))
    
    archivos = os.listdir(carpeta_factura)
    for archivo in archivos:
        ruta_archivo = os.path.join(carpeta_factura, archivo)
        if os.path.isdir(ruta_archivo):
            continue
        
        nombre_upper = archivo.upper()
        ext = os.path.splitext(archivo)[1].lower()
        es_pdf_completo = (nombre_upper == f"{folio.upper()}_COMPLETO.PDF")
        
        if ext == ".pdf" and not es_pdf_completo:
            continue 
            
        try:
            with open(ruta_archivo, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename= {archivo}")
            msg.attach(part)
        except Exception:
            pass
            
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    server.sendmail(SMTP_USER, destinatarios, msg.as_string())
    server.quit()

def armar_expediente_pdf(carpeta_factura, folio, mapeo_archivos):
    archivos_pdf = glob.glob(os.path.join(carpeta_factura, "*.pdf"))
    agrupados = {i: [] for i in range(1, 16)}
    agrupados[99] = [] 
    
    for ruta_pdf in archivos_pdf:
        nombre_archivo = os.path.basename(ruta_pdf).upper()
        if nombre_archivo == f"{folio.upper()}_COMPLETO.PDF":
            continue
        tipo_doc = mapeo_archivos.get(nombre_archivo, "OTROS")
        
        if "CTA" in tipo_doc and "GASTOS" in tipo_doc: agrupados[1].append(ruta_pdf)
        elif "VALIDACI" in tipo_doc and "EI" in tipo_doc: agrupados[2].append(ruta_pdf)
        elif "RENDICION" in tipo_doc: agrupados[3].append(ruta_pdf)
        elif "SIMPLIFICADO" in tipo_doc: agrupados[4].append(ruta_pdf)
        elif "PEDIMENTO" in tipo_doc and "SIMPLIFICADO" not in tipo_doc: agrupados[5].append(ruta_pdf)
        elif "COMPROBADOS" in tipo_doc: agrupados[6].append(ruta_pdf)
        elif "VALIDACI" in tipo_doc and "TERCEROS" in tipo_doc: agrupados[7].append(ruta_pdf)
        elif "FACTURA" in tipo_doc: agrupados[8].append(ruta_pdf)
        elif "GUIA" in tipo_doc or "BL" in tipo_doc: agrupados[9].append(ruta_pdf)
        elif "CARTA" in tipo_doc or "IVA" in tipo_doc or "3.1.8" in tipo_doc: agrupados[10].append(ruta_pdf)
        elif "DODA" in tipo_doc: agrupados[11].append(ruta_pdf)
        elif "ANEXO" in tipo_doc: agrupados[12].append(ruta_pdf)
        elif "MANIFESTACION" in tipo_doc or "VALOR" in tipo_doc: agrupados[13].append(ruta_pdf)
        elif "CALCULO" in tipo_doc or "HOJA" in tipo_doc: agrupados[14].append(ruta_pdf)
        else: agrupados[99].append(ruta_pdf) 
            
    merger = PdfMerger()
    for categoria in sorted(agrupados.keys()):
        for pdf in sorted(agrupados[categoria]):
            merger.append(pdf)
            
    ruta_salida = os.path.join(carpeta_factura, f"{folio}_Completo.pdf")
    merger.write(ruta_salida)
    merger.close()
    return ruta_salida

def procesar_descargas_y_envios(playwright: Playwright, df_envios: pd.DataFrame, barra_progreso, texto_estado):
    # args especiales para la nube (sin interfaz, ignorar sandbox)
    browser = playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=0.8'])
    context = browser.new_context()
    page = context.new_page()
    
    texto_estado.info("Iniciando sesión en Facturacion1hr...")
    page.goto("https://web.aduax.com/Facturacion1hr/Account/Login")
    page.wait_for_timeout(1000)
    
    page.get_by_role("textbox", name="Nombre de Usuario").click()
    page.get_by_role("textbox", name="Nombre de Usuario").fill(USUARIO_F1HR)
    page.get_by_role("textbox", name="Nombre de Usuario").press("Tab")
    page.get_by_role("textbox", name="Credenciales").fill(PASSWORD_F1HR)
    page.get_by_role("textbox", name="Credenciales").press("Tab")
    page.get_by_role("combobox").press("Enter")
    page.wait_for_timeout(500)
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_timeout(2000)
    
    texto_estado.info("Navegando a la bandeja de Referencias (ELI)...")
    page.get_by_role("button").nth(1).click()
    page.wait_for_timeout(1000)
    page.get_by_role("link", name="Cambiar ").click()
    page.wait_for_timeout(1000)
    page.get_by_text("ELI", exact=True).click()
    page.wait_for_timeout(1000)
    page.get_by_role("heading", name="Facturacion1Hr").click()
    page.wait_for_timeout(1000)
    page.get_by_role("link", name="Referencias Posibles a liberar").click()
    page.wait_for_timeout(3000)
    
    page.get_by_role("tab", name="Concluídas").click()
    page.wait_for_timeout(500)
    page.get_by_role("tab", name="Facturadas").click()
    page.wait_for_timeout(500)
    page.get_by_role("tab", name="Concluídas").click()
    page.wait_for_timeout(5000)
    
    frame_concluidas = page.locator("#frm_concluidas").content_frame

    resultados = []
    rutas_pdfs_completos = []
    total_folios = len(df_envios)
    
    for index, row in df_envios.reset_index().iterrows():
        factura = str(row['Folio Factura']).strip()
        cliente_completo = str(row['Cliente']).strip()
        ref_operativa = row.get('ReferenciaOperativa', '')
        
        nombre_cliente_carpeta = cliente_completo.split("-", 1)[1].strip() if "-" in cliente_completo else cliente_completo
        carpeta_destino = os.path.join(CARPETA_BASE, nombre_cliente_carpeta, factura)
        os.makedirs(carpeta_destino, exist_ok=True)
        
        # Actualizamos Progreso en Streamlit
        progreso_actual = (index) / total_folios
        barra_progreso.progress(progreso_actual)
        texto_estado.info(f"Procesando Folio {index+1}/{total_folios}: **{factura}**")
        
        try:
            # 1. BÚSQUEDA Y DESCARGA
            texto_estado.write(f"🔎 Buscando factura {factura} en el portal...")
            buscador = frame_concluidas.get_by_role("searchbox", name="Buscar")
            buscador.click()
            buscador.fill("")
            page.wait_for_timeout(500)
            buscador.fill(factura)
            page.wait_for_timeout(3000)
            
            with page.expect_popup(timeout=15000) as popup_info:
                frame_concluidas.get_by_role("link", name=factura).click()
            popup = popup_info.value
            popup.wait_for_load_state("networkidle")
            popup.wait_for_timeout(3000)
            
            mapeo_archivos = {}
            filas = popup.locator("tbody tr")
            cantidad_filas = filas.count()
            
            for i in range(cantidad_filas):
                try:
                    nombre_arch = filas.nth(i).locator("td").nth(1).inner_text().strip().upper()
                    tipo_doc = filas.nth(i).locator("td").nth(2).inner_text().strip().upper()
                    mapeo_archivos[nombre_arch] = tipo_doc
                except Exception:
                    pass
            
            texto_estado.write(f"📥 Descargando archivos para {factura}...")
            for i in range(cantidad_filas):
                try:
                    tipo_documento = filas.nth(i).locator("td").nth(2).inner_text().strip().upper()
                    if "VALIDACIÓN DE CFDI EI" in tipo_documento or "VALIDACIÓN DE CFDI TERCEROS" in tipo_documento:
                        boton_descarga = filas.nth(i).locator("td .row div:nth-child(2) .button").first
                        with popup.expect_download(timeout=15000) as d_info:
                            boton_descarga.click(force=True)
                        download = d_info.value
                        ruta_ind = os.path.join(carpeta_destino, download.suggested_filename)
                        download.save_as(ruta_ind)
                        popup.wait_for_timeout(1000)
                except Exception:
                    pass

            with popup.expect_download(timeout=30000) as download_info:
                with popup.expect_popup() as p2_info:
                    popup.get_by_role("button", name="Descargar").click()
                p2 = p2_info.value
            
            ruta_zip = os.path.join(carpeta_destino, "expediente.zip")
            download_info.value.save_as(ruta_zip)
            p2.close()
            
            with zipfile.ZipFile(ruta_zip, 'r') as zip_ref:
                zip_ref.extractall(carpeta_destino)
            os.remove(ruta_zip)
            popup.close()
            
            # 2. ARMADO DE PDF
            texto_estado.write(f"📄 Uniendo PDFs para {factura}...")
            ruta_completo = armar_expediente_pdf(carpeta_destino, factura, mapeo_archivos)
            rutas_pdfs_completos.append(ruta_completo)
            
            # 3. ENVÍO DE CORREO
            texto_estado.write(f"✉️ Enviando correo para {factura}...")
            ref_pedimento = obtener_referencia_o_pedimento(carpeta_destino, ref_operativa)
            enviar_correo_expediente(nombre_cliente_carpeta, factura, ref_pedimento, carpeta_destino)
            
            resultados.append({"Folio": factura, "Estatus": "✅ Éxito", "Detalle": "Descargado, unido y enviado"})
            page.wait_for_timeout(2000)
            
        except Exception as e:
            resultados.append({"Folio": factura, "Estatus": "❌ Error", "Detalle": f"Fallo en proceso: {str(e)}"})

    # Finalizar
    barra_progreso.progress(1.0)
    texto_estado.success("Proceso automatizado finalizado.")
    context.close()
    browser.close()
    
    return resultados, rutas_pdfs_completos


# ==========================================
# INTERFAZ DE USUARIO (STREAMLIT)
# ==========================================
st.set_page_config(page_title="Bot Facturación F1H", page_icon="🤖")

st.title("🤖 Automatización: Descarga y Envío de Expedientes")
st.write("Sube el archivo `Envios.xlsx` extraído del sistema. El bot se encargará de descargar los archivos de F1H, armar el expediente ordenado y enviarlo por correo.")

archivo_subido = st.file_uploader("Selecciona el archivo Excel", type=["xlsx"])

if archivo_subido is not None:
    # Leemos el archivo cargado
    df = pd.read_excel(archivo_subido, dtype={"Folio Factura": str})
    df_condumex = df[df['Cliente'].isin(CLIENTES_CONDUMEX)]
    
    if df_condumex.empty:
        st.warning("No se encontraron envíos pendientes para los clientes de Condumex en este archivo.")
    else:
        st.info(f"Se encontraron **{len(df_condumex)}** folios listos para procesar.")
        
        if st.button("🚀 Iniciar Procesamiento Automático"):
            barra_progreso = st.progress(0)
            texto_estado = st.empty()
            
            with st.spinner("Ejecutando robot... Esto puede tomar varios minutos."):
                with sync_playwright() as playwright:
                    resultados, rutas_pdfs = procesar_descargas_y_envios(playwright, df_condumex, barra_progreso, texto_estado)
            
            # --- RESUMEN FINAL ---
            st.header("📊 Resumen de Ejecución")
            df_resultados = pd.DataFrame(resultados)
            
            exitosos = len(df_resultados[df_resultados['Estatus'] == '✅ Éxito'])
            errores = len(df_resultados[df_resultados['Estatus'] == '❌ Error'])
            
            col1, col2 = st.columns(2)
            col1.metric("Cuentas Exitosas", exitosos)
            col2.metric("Cuentas con Error", errores)
            
            st.dataframe(df_resultados, use_container_width=True)
            
            # --- FUSIÓN MAESTRA (RELACIÓN DE ENVÍO) ---
            if rutas_pdfs:
                st.subheader("📥 Descarga de Relación General")
                st.write("Se han unificado todos los expedientes exitosos en un solo documento.")
                
                merger_final = PdfMerger()
                for pdf_individual in rutas_pdfs:
                    merger_final.append(pdf_individual)
                    
                ruta_relacion = "Relacion_Envio.pdf"
                merger_final.write(ruta_relacion)
                merger_final.close()
                
                with open(ruta_relacion, "rb") as file:
                    st.download_button(
                        label="Descargar Relacion_Envio.pdf",
                        data=file,
                        file_name="Relacion_Envio.pdf",
                        mime="application/pdf"
                    )