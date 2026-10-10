"""
Qubit Lite
==========

Copiloto de pantalla con:
    1. Visión directa (la captura va como imagen a Claude, sin OCR de por medio)
    2. Hotkey global (Ctrl+Shift+S) para dispararse desde cualquier lugar del SO
    3. Modo Agente: Claude puede guardar datos estructurados en un Excel local
    4. Memoria semántica local (ChromaDB): preguntale a Qubit sobre capturas pasadas

Arquitectura (ver también vision_engine.py, agent_tools.py, memory_store.py):
    - Este archivo se encarga solo de la interfaz y de orquestar las llamadas
      a los otros módulos. La lógica de "cómo hablarle a Claude con imágenes"
      vive en vision_engine.py, la de "cómo guardar un registro" en
      agent_tools.py, y la de "cómo recordar capturas pasadas" en
      memory_store.py.
    - Todo el trabajo pesado (captura, llamada a la API, tool use, memoria)
      corre en un hilo secundario para no congelar la ventana.
"""

import sys
import os
import platform
import shutil
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog

from mss import mss
from PIL import Image
from anthropic import Anthropic
from dotenv import load_dotenv

import vision_engine
import agent_tools
import memory_store

# --- Librerías opcionales ---
try:
    import keyboard  # Atajo global
    HOTKEY_DISPONIBLE = True
except ImportError:
    HOTKEY_DISPONIBLE = False

try:
    import pystray  # Ícono de bandeja
    from PIL import Image as PILImage
    TRAY_DISPONIBLE = True
except ImportError:
    TRAY_DISPONIBLE = False

# OCR local, ahora relegado a modo alternativo (ver checkbox "OCR local").
try:
    import pytesseract
    OCR_DISPONIBLE = True
except ImportError:
    OCR_DISPONIBLE = False


# ============================================================
#  CONFIGURACIÓN DE TESSERACT (solo si se usa el modo OCR local)
# ============================================================
def configurar_tesseract():
    if not OCR_DISPONIBLE:
        return
    sistema = platform.system()
    if shutil.which("tesseract"):
        return
    rutas_conocidas = []
    if sistema == "Windows":
        rutas_conocidas = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    elif sistema == "Darwin":
        rutas_conocidas = ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]
    else:
        rutas_conocidas = ["/usr/bin/tesseract", "/usr/local/bin/tesseract"]
    for ruta in rutas_conocidas:
        if os.path.isfile(ruta):
            pytesseract.pytesseract.tesseract_cmd = ruta
            return


# ============================================================
#  CARGA DE API KEY Y FLAGS DE FUNCIONES OPCIONALES
# ============================================================
load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY")

# El tray sigue apagado por defecto: en Linux, pystray depende de GTK, que
# no está pensado para inicializarse fuera del hilo principal — correrlo en
# background puede colgar el proceso sin avisar. Queda como experimental:
#   HABILITAR_TRAY=1 python qubit_lite.py
HABILITAR_TRAY = os.getenv("HABILITAR_TRAY", "0") == "1"

# El hotkey SÍ queda activado por defecto en esta versión: ahora el registro
# corre en su propio hilo (ver _configurar_hotkey), así que aunque tarde o
# falle, nunca bloquea el arranque de la ventana como podía pasar antes.
HABILITAR_HOTKEY = os.getenv("HABILITAR_HOTKEY", "1") == "1"
COMBINACION_HOTKEY = "ctrl+shift+s"

IDIOMAS = {
    "Español": "español",
    "Inglés": "inglés",
    "Portugués": "portugués",
    "Francés": "francés",
}

MODOS = {
    "Resumen": (
        "Presenta un resumen minimalista y claro con los puntos más "
        "importantes de la pantalla, en {idioma}. Agrupa elementos "
        "repetitivos (como títulos de videos o ítems de menú) de forma "
        "inteligente."
    ),
    "Traducción completa": (
        "Traducí todo el contenido visible al {idioma} de forma completa y "
        "fiel, sin resumir."
    ),
    "Solo limpieza": (
        "Transcribí y ordená el contenido de forma prolija, sin traducir "
        "ni resumir. Mantené el idioma original."
    ),
}


class QubitLite:
    """Ventana flotante principal. Ver el docstring del módulo para la
    arquitectura general."""

    def __init__(self, root):
        self.root = root
        self.root.title("Qubit Lite")

        try:
            self.root.overrideredirect(True)
        except Exception as e:
            print(f"[Aviso] No se pudieron quitar los bordes de ventana: {e}")
        try:
            self.root.attributes("-topmost", True)
        except Exception as e:
            print(f"[Aviso] No se pudo fijar 'siempre visible': {e}")
        try:
            self.root.attributes("-alpha", 0.95)
        except Exception as e:
            print(f"[Aviso] Transparencia no soportada en este entorno: {e}")

        self.window_w = 460
        self.window_h = 400
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.window_x = (screen_width // 2) - (self.window_w // 2)
        self.window_y = (screen_height // 2) - (self.window_h // 2)
        self.root.geometry(f"{self.window_w}x{self.window_h}+{self.window_x}+{self.window_y}")

        self.cargando = False
        self.idioma_var = tk.StringVar(value="Español")
        self.modo_var = tk.StringVar(value="Resumen")
        self.agente_var = tk.BooleanVar(value=False)
        self.ocr_local_var = tk.BooleanVar(value=False)

        if not API_KEY:
            messagebox.showerror(
                "Falta la API key",
                "No se encontró ANTHROPIC_API_KEY.\n\n"
                "Creá un archivo .env junto al script con:\n"
                "ANTHROPIC_API_KEY=tu_clave_aca"
            )
            sys.exit(1)

        try:
            self.client = Anthropic(api_key=API_KEY)
        except Exception:
            messagebox.showerror("Error de API", "Error al iniciar el cliente de Anthropic.")
            sys.exit(1)

        self._construir_ui()
        self._configurar_hotkey()
        self._configurar_tray()

    # --------------------------------------------------------
    #  UI
    # --------------------------------------------------------
    def _construir_ui(self):
        self.main_frame = tk.Frame(self.root, bg="#1e1e2e", bd=1, relief="flat")
        self.main_frame.pack(fill="both", expand=True)

        self.title_bar = tk.Frame(self.main_frame, bg="#11111b", height=25)
        self.title_bar.pack(fill="x", side="top")

        self.title_label = tk.Label(
            self.title_bar, text="Qubit Lite", bg="#11111b",
            fg="#cdd6f4", font=("Arial", 9, "bold")
        )
        self.title_label.pack(side="left", padx=10)

        self.close_btn = tk.Button(
            self.title_bar, text="✕", bg="#11111b", fg="#f38ba8", bd=0,
            activebackground="#f38ba8", activeforeground="#11111b",
            command=self._cerrar_app, font=("Arial", 9)
        )
        self.close_btn.pack(side="right", padx=10)

        # --- Fila 1: idioma + modo ---
        self.opciones_frame = tk.Frame(self.main_frame, bg="#1e1e2e")
        self.opciones_frame.pack(fill="x", padx=10, pady=(8, 0))

        tk.Label(self.opciones_frame, text="Idioma:", bg="#1e1e2e", fg="#a6adc8",
                  font=("Arial", 8)).grid(row=0, column=0, sticky="w")
        idioma_menu = tk.OptionMenu(self.opciones_frame, self.idioma_var, *IDIOMAS.keys())
        idioma_menu.config(bg="#313244", fg="#cdd6f4", activebackground="#45475a",
                            bd=0, font=("Arial", 8), highlightthickness=0)
        idioma_menu["menu"].config(bg="#313244", fg="#cdd6f4")
        idioma_menu.grid(row=0, column=1, sticky="w", padx=(5, 15))

        tk.Label(self.opciones_frame, text="Modo:", bg="#1e1e2e", fg="#a6adc8",
                  font=("Arial", 8)).grid(row=0, column=2, sticky="w")
        modo_menu = tk.OptionMenu(self.opciones_frame, self.modo_var, *MODOS.keys())
        modo_menu.config(bg="#313244", fg="#cdd6f4", activebackground="#45475a",
                          bd=0, font=("Arial", 8), highlightthickness=0)
        modo_menu["menu"].config(bg="#313244", fg="#cdd6f4")
        modo_menu.grid(row=0, column=3, sticky="w", padx=5)

        # --- Fila 2: checkboxes de funciones (Agente / OCR local) ---
        self.flags_frame = tk.Frame(self.main_frame, bg="#1e1e2e")
        self.flags_frame.pack(fill="x", padx=10, pady=(4, 0))

        agente_chk = tk.Checkbutton(
            self.flags_frame, text="Modo Agente (guardar en Excel)",
            variable=self.agente_var, bg="#1e1e2e", fg="#a6adc8",
            selectcolor="#313244", activebackground="#1e1e2e",
            activeforeground="#cdd6f4", font=("Arial", 8)
        )
        agente_chk.pack(side="left")

        if OCR_DISPONIBLE:
            ocr_chk = tk.Checkbutton(
                self.flags_frame, text="OCR local", variable=self.ocr_local_var,
                bg="#1e1e2e", fg="#a6adc8", selectcolor="#313244",
                activebackground="#1e1e2e", activeforeground="#cdd6f4",
                font=("Arial", 8)
            )
            ocr_chk.pack(side="left", padx=(10, 0))

        # --- Botonera inferior ---
        self.btn_frame = tk.Frame(self.main_frame, bg="#1e1e2e")
        self.btn_frame.pack(fill="x", side="bottom", padx=10, pady=10)

        self.action_btn = tk.Button(
            self.btn_frame, text="Capturar", bg="#89b4fa", fg="#11111b",
            activebackground="#b4befe", bd=0, font=("Arial", 10, "bold"),
            command=self.procesar_pantalla, height=2
        )
        self.action_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.memoria_btn = tk.Button(
            self.btn_frame, text="Memoria", bg="#cba6f7", fg="#11111b",
            activebackground="#ddbaff", bd=0, font=("Arial", 10, "bold"),
            command=self.preguntar_memoria, height=2
        )
        self.memoria_btn.pack(side="left", fill="x", expand=True, padx=4)

        self.copy_btn = tk.Button(
            self.btn_frame, text="Copiar", bg="#313244", fg="#cdd6f4",
            activebackground="#45475a", bd=0, font=("Arial", 10, "bold"),
            command=self.copiar_al_portapapeles, height=2
        )
        self.copy_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

        self.text_area = tk.Text(
            self.main_frame, bg="#1e1e2e", fg="#cdd6f4", insertbackground="white",
            relief="flat", font=("Arial", 10), wrap="word", padx=10, pady=10
        )
        self.text_area.pack(fill="both", expand=True)
        self.text_area.insert(
            "1.0",
            f"Presioná 'Capturar' o {COMBINACION_HOTKEY.upper()} para analizar la pantalla...\n\n"
            "Activá 'Modo Agente' si querés que Qubit guarde automáticamente "
            "facturas, tareas o productos en un Excel.\n\n"
            "Usá 'Memoria' para preguntar sobre capturas anteriores."
        )

        self.title_bar.bind("<ButtonPress-1>", self.iniciar_arrastre)
        self.title_bar.bind("<B1-Motion>", self.arrastrar_ventana)

    # --------------------------------------------------------
    #  Hotkey global (registro en hilo aparte: nunca bloquea el arranque)
    # --------------------------------------------------------
    def _configurar_hotkey(self):
        if not HOTKEY_DISPONIBLE or not HABILITAR_HOTKEY:
            if HOTKEY_DISPONIBLE:
                print("[Info] Hotkey global desactivado (HABILITAR_HOTKEY=0).")
            return

        def registrar():
            try:
                keyboard.add_hotkey(
                    COMBINACION_HOTKEY,
                    lambda: self.root.after(0, self.procesar_pantalla),
                )
                print(f"[Info] Hotkey global '{COMBINACION_HOTKEY}' activo.")
            except Exception as e:
                print(f"[Aviso] No se pudo activar el hotkey global: {e}")
                print("La app sigue funcionando normalmente con el botón 'Capturar'.")

        # Se registra en un hilo aparte a propósito: en Linux, sin permisos
        # de root, esta llamada puede demorar varios segundos antes de
        # fallar. Si corriera en el hilo principal, la ventana quedaría
        # armada pero sin pintarse durante ese lapso.
        threading.Thread(target=registrar, daemon=True).start()

    # --------------------------------------------------------
    #  Ícono de bandeja (experimental, apagado por defecto)
    # --------------------------------------------------------
    def _configurar_tray(self):
        if not TRAY_DISPONIBLE or not HABILITAR_TRAY:
            self.tray_icon = None
            return
        try:
            icono_img = PILImage.new("RGB", (32, 32), "#89b4fa")
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar / Capturar", self._mostrar_desde_tray, default=True),
                pystray.MenuItem("Salir", self._salir_desde_tray),
            )
            self.tray_icon = pystray.Icon("qubit", icono_img, "Qubit Lite", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"[Aviso] No se pudo iniciar el ícono de bandeja: {e}")
            self.tray_icon = None

    def _mostrar_desde_tray(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def _salir_desde_tray(self, icon=None, item=None):
        if getattr(self, "tray_icon", None):
            self.tray_icon.stop()
        self.root.after(0, self.root.quit)

    def _cerrar_app(self):
        if HABILITAR_TRAY and getattr(self, "tray_icon", None):
            self.root.withdraw()
        else:
            self.root.destroy()

    # --------------------------------------------------------
    #  Arrastre de ventana
    # --------------------------------------------------------
    def iniciar_arrastre(self, event):
        self.x = event.x
        self.y = event.y

    def arrastrar_ventana(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def copiar_al_portapapeles(self):
        contenido = self.text_area.get("1.0", tk.END).strip()
        if contenido and not self.cargando:
            self.root.clipboard_clear()
            self.root.clipboard_append(contenido)
            self.copy_btn.config(text="¡Copiado!", bg="#a6e3a1", fg="#11111b")
            self.root.after(1500, self._restaurar_boton_copiar)

    def _restaurar_boton_copiar(self):
        self.copy_btn.config(text="Copiar", bg="#313244", fg="#cdd6f4")

    # --------------------------------------------------------
    #  Captura + Visión + (Agente) + Memoria
    # --------------------------------------------------------
    def procesar_pantalla(self):
        if self.cargando:
            return
        self.cargando = True
        self.action_btn.config(state="disabled")
        self._cambiar_contenido_texto("Preparando captura...")
        self.root.update()

        self.window_x = self.root.winfo_x()
        self.window_y = self.root.winfo_y()
        self.window_w = self.root.winfo_width()
        self.window_h = self.root.winfo_height()
        self.root.withdraw()
        self.root.after(200, lambda: threading.Thread(
            target=self._hilo_captura_y_analisis, daemon=True
        ).start())

    def _capturar_monitor_actual(self):
        with mss() as sct:
            center_x = self.window_x + self.window_w // 2
            center_y = self.window_y + self.window_h // 2
            monitor_actual = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            for monitor in sct.monitors[1:]:
                m_left, m_top = monitor["left"], monitor["top"]
                m_width, m_height = monitor["width"], monitor["height"]
                if (m_left <= center_x < m_left + m_width) and (m_top <= center_y < m_top + m_height):
                    monitor_actual = monitor
                    break
            sct_img = sct.grab(monitor_actual)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    def _hilo_captura_y_analisis(self):
        try:
            self._actualizar_texto_seguro("Capturando pantalla...")
            img = self._capturar_monitor_actual()

            extrema = img.convert("L").getextrema()
            if extrema == (0, 0):
                mensaje_wayland = (
                    "Se capturó una pantalla negra.\n\n"
                    "Esto ocurre en sesiones de Wayland (Ubuntu 24.04+), que "
                    "bloquean las capturas automáticas de apps externas.\n\n"
                    "Solución: cerrá sesión, elegí 'Ubuntu en Xorg' en el "
                    "ícono de engranaje del login, y volvé a iniciar sesión."
                )
                self._finalizar_con_mensaje(mensaje_wayland)
                return

            idioma = IDIOMAS[self.idioma_var.get()]
            instruccion_modo = MODOS[self.modo_var.get()].format(idioma=idioma)
            modo_actual = self.modo_var.get()
            usa_agente = self.agente_var.get()
            usa_ocr = self.ocr_local_var.get() and OCR_DISPONIBLE

            self.root.after(0, self._iniciar_animacion)

            if usa_ocr:
                resultado_texto = self._analizar_via_ocr(img, instruccion_modo)
            else:
                resultado_texto = self._analizar_via_vision(img, instruccion_modo, usa_agente)

            if not resultado_texto.strip():
                self._finalizar_con_mensaje("No se pudo extraer información de la pantalla.")
                return

            # Guardar en la memoria semántica (no bloquea el resultado si falla)
            try:
                memory_store.guardar_captura(resultado_texto, modo_actual, idioma)
            except Exception as e:
                print(f"[Aviso] No se pudo guardar en la memoria semántica: {e}")

            self._finalizar_con_resultado(resultado_texto)

        except Exception as e:
            if OCR_DISPONIBLE and isinstance(e, pytesseract.TesseractNotFoundError):
                instrucciones = (
                    "Error: No se encontró Tesseract OCR en el sistema.\n\n"
                    "• Windows: instalador en github.com/UB-Mannheim/tesseract/wiki\n"
                    "• Linux: sudo apt install tesseract-ocr tesseract-ocr-spa\n"
                    "• macOS: brew install tesseract tesseract-lang\n\n"
                    "O simplemente destildá 'OCR local' para usar visión directa."
                )
                self._finalizar_con_mensaje(instrucciones)
            else:
                self._finalizar_con_mensaje(f"Error en el proceso:\n{str(e)}")

    def _analizar_via_vision(self, img, instruccion_modo, usa_agente):
        """Camino principal: la imagen va directo a Claude. Si el Modo
        Agente está activo, se le pasa la herramienta de guardado y se
        maneja el ciclo de tool use si Claude decide usarla."""
        tools = [agent_tools.TOOL_GUARDAR_REGISTRO] if usa_agente else None
        resultado = vision_engine.analizar_pantalla(
            self.client, img, instruccion_modo, tools=tools
        )

        texto = resultado["texto"]
        tool_uses = resultado["tool_uses"]

        if tool_uses:
            resultados_tools = []
            confirmaciones = []
            for tu in tool_uses:
                if tu.name == "guardar_registro":
                    confirmacion = agent_tools.ejecutar_guardar_registro(tu.input)
                    confirmaciones.append(confirmacion)
                    resultados_tools.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": confirmacion,
                    })
            texto_final = vision_engine.continuar_con_resultados_de_tools(
                self.client,
                resultado["mensaje_usuario"],
                resultado["respuesta"],
                resultados_tools,
                resultado["prompt_sistema"],
                tools,
            )
            texto = (texto_final or texto) + "\n\n📊 " + " | ".join(confirmaciones)

        return texto

    def _analizar_via_ocr(self, img, instruccion_modo):
        """Camino alternativo: OCR local + texto a Claude (sin imagen).
        Útil para no gastar tokens de imagen en pantallas simples."""
        from PIL import ImageEnhance
        gris = img.convert("L")
        img_ocr = ImageEnhance.Contrast(gris).enhance(1.8)
        texto_extraido = pytesseract.image_to_string(img_ocr, lang="spa+eng")

        if not texto_extraido.strip():
            return ""

        prompt_sistema = (
            "Sos Qubit, un copiloto de pantalla. Procesás texto bruto "
            "extraído por OCR, que puede tener errores de tipeo o estar "
            "desordenado.\n\n"
            f"Tarea específica: {instruccion_modo}"
        )
        respuesta = self.client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1200,
            system=prompt_sistema,
            messages=[{"role": "user", "content": f"Texto extraído de la pantalla:\n\n{texto_extraido}"}],
        )
        return "\n".join(b.text for b in respuesta.content if b.type == "text")

    # --------------------------------------------------------
    #  Memoria semántica (RAG)
    # --------------------------------------------------------
    def preguntar_memoria(self):
        if self.cargando:
            return
        pregunta = simpledialog.askstring(
            "Preguntar a la memoria",
            "¿Qué querés saber sobre capturas anteriores?",
            parent=self.root,
        )
        if not pregunta:
            return
        self.cargando = True
        self.action_btn.config(state="disabled")
        self._cambiar_contenido_texto(f"Buscando en la memoria: \"{pregunta}\"...")
        threading.Thread(target=self._hilo_responder_memoria, args=(pregunta,), daemon=True).start()

    def _hilo_responder_memoria(self, pregunta):
        try:
            contextos = memory_store.buscar_contexto(pregunta, n_resultados=3)
            if not contextos:
                self._finalizar_con_mensaje(
                    "Todavía no hay capturas guardadas en la memoria. "
                    "Analizá alguna pantalla primero."
                )
                return

            bloques_contexto = "\n\n---\n\n".join(
                f"[{c['meta'].get('timestamp', '?')}] {c['texto']}" for c in contextos
            )
            prompt_sistema = (
                "Sos Qubit, un asistente con memoria de capturas de pantalla "
                "pasadas del usuario. Te paso fragmentos de análisis "
                "anteriores (los más relevantes a la pregunta). Respondé la "
                "pregunta del usuario basándote SOLO en esos fragmentos. Si "
                "la respuesta no está ahí, decilo con honestidad en vez de "
                "inventar."
            )
            respuesta = self.client.messages.create(
                model="claude-sonnet-5",
                max_tokens=600,
                system=prompt_sistema,
                messages=[{
                    "role": "user",
                    "content": f"Fragmentos de memoria:\n\n{bloques_contexto}\n\nPregunta: {pregunta}",
                }],
            )
            texto = "\n".join(b.text for b in respuesta.content if b.type == "text")
            self._finalizar_con_resultado(texto)
        except Exception as e:
            self._finalizar_con_mensaje(f"Error al consultar la memoria:\n{str(e)}")

    # --------------------------------------------------------
    #  Helpers de UI (thread-safe)
    # --------------------------------------------------------
    def _actualizar_texto_seguro(self, texto):
        self.root.after(0, lambda: self._cambiar_contenido_texto(texto))

    def _cambiar_contenido_texto(self, texto):
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", texto)

    def _iniciar_animacion(self):
        self._animar_carga_loop(0)

    def _animar_carga_loop(self, step):
        if not self.cargando:
            return
        dots = "." * (step % 4)
        self._cambiar_contenido_texto(f"Qubit está analizando{dots}")
        self.root.after(400, self._animar_carga_loop, step + 1)

    def _finalizar_con_resultado(self, resultado):
        def restaurar():
            self.cargando = False
            self.root.deiconify()
            self._cambiar_contenido_texto(resultado)
            self.action_btn.config(state="normal")
        self.root.after(0, restaurar)

    def _finalizar_con_mensaje(self, mensaje):
        def restaurar():
            self.cargando = False
            self.root.deiconify()
            self._cambiar_contenido_texto(mensaje)
            self.action_btn.config(state="normal")
        self.root.after(0, restaurar)


if __name__ == "__main__":
    print("[Diagnóstico] Iniciando Qubit Lite...")
    configurar_tesseract()
    root = tk.Tk()
    print("[Diagnóstico] Construyendo la interfaz.")
    app = QubitLite(root)
    print("[Diagnóstico] Interfaz lista. Entrando al mainloop.")
    root.mainloop()
    print("[Diagnóstico] mainloop finalizado (la ventana se cerró).")
