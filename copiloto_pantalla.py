"""
Copiloto de Pantalla
====================

Aplicación de escritorio que captura la pantalla, extrae el texto visible
mediante OCR (Tesseract) y lo envía a la API de Claude para traducirlo,
resumirlo o limpiarlo, mostrando el resultado en una ventana flotante
minimalista.

Flujo general:
    1. El usuario dispara la captura (botón, hotkey o ítem de bandeja).
    2. La ventana se oculta un instante para no aparecer en su propia foto.
    3. `mss` toma un screenshot del monitor donde está la ventana.
    4. La imagen se preprocesa (escala de grises + contraste) y se pasa
       por Tesseract para extraer el texto crudo.
    5. Ese texto se envía a Claude junto con una instrucción de sistema que
       depende del modo elegido (Resumen / Traducción / Solo limpieza).
    6. El resultado se muestra en la caja de texto de la ventana.

Todo el trabajo pesado (captura, OCR, llamada a la API) corre en un hilo
separado para no congelar la interfaz de tkinter mientras se procesa.
"""

import sys
import os
import platform
import shutil
import threading
import tkinter as tk
from tkinter import messagebox

from mss import mss
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
from anthropic import Anthropic
from dotenv import load_dotenv

# --- Librerías opcionales ---
# La app tiene que poder arrancar aunque el usuario no las tenga instaladas
# (por ejemplo, si clonó el repo pero no instaló el requirements.txt completo).
# Por eso cada una se importa dentro de un try/except y se guarda una bandera
# booleana que se consulta más adelante antes de usarlas.

try:
    import keyboard  # Permite registrar el atajo global Ctrl+Alt+S
    HOTKEY_DISPONIBLE = True
except ImportError:
    HOTKEY_DISPONIBLE = False

try:
    import pystray  # Ícono en la bandeja del sistema (system tray)
    from PIL import Image as PILImage
    TRAY_DISPONIBLE = True
except ImportError:
    TRAY_DISPONIBLE = False


# ============================================================
#  CONFIGURACIÓN DE TESSERACT (multiplataforma, sin editar código)
# ============================================================
def configurar_tesseract():
    """Localiza el ejecutable de Tesseract sin que el usuario tenga que
    editar el código a mano (a diferencia de la v1, donde había que
    descomentar una línea con la ruta exacta).

    Orden de búsqueda:
        1. Si 'tesseract' ya resuelve en el PATH del sistema, no hacemos nada
           y dejamos que pytesseract lo use directamente.
        2. Si no, probamos una lista de rutas de instalación típicas según
           el sistema operativo detectado con `platform.system()`.
        3. Si ninguna existe, no seteamos nada: más adelante,
           `pytesseract.TesseractNotFoundError` se captura y se le muestra
           al usuario un mensaje con instrucciones de instalación.
    """
    sistema = platform.system()

    # Si ya está en el PATH, no hacemos nada.
    if shutil.which("tesseract"):
        return

    rutas_conocidas = []
    if sistema == "Windows":
        rutas_conocidas = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    elif sistema == "Darwin":  # macOS (Homebrew)
        rutas_conocidas = [
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]
    else:  # Linux
        rutas_conocidas = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]

    for ruta in rutas_conocidas:
        if os.path.isfile(ruta):
            pytesseract.pytesseract.tesseract_cmd = ruta
            return
    # Si no se encontró en ningún lado, se lanzará TesseractNotFoundError
    # más adelante y el usuario verá el mensaje de instalación.


# ============================================================
#  CARGA DE API KEY DESDE .env (NUNCA hardcodeada en el código)
# ============================================================
# load_dotenv() busca un archivo .env en el directorio del proyecto y carga
# sus variables como si fueran variables de entorno del sistema. Así, la key
# nunca queda escrita en el .py y por lo tanto nunca se sube a git (el .env
# está listado en .gitignore).
load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY")

# El ícono de bandeja (pystray) usa GTK por debajo en Linux, y GTK no está
# pensado para inicializarse fuera del hilo principal. Correrlo en un hilo
# secundario (como hacíamos) puede colgar el proceso silenciosamente en
# ciertos entornos, sin lanzar una excepción atrapable. Por eso queda
# DESACTIVADO por defecto; se puede probar a activar con:
#   HABILITAR_TRAY=1 python copiloto_pantalla.py
HABILITAR_TRAY = os.getenv("HABILITAR_TRAY", "0") == "1"

# El hotkey global (`keyboard`) necesita acceder a /dev/input en Linux. Sin
# permisos de root, esto puede no fallar limpio: a veces tarda varios
# segundos negociando el acceso antes de rendirse, y durante ese lapso la
# ventana queda armada pero sin pintarse (el mainloop todavía no arrancó).
# Por eso también queda DESACTIVADO por defecto:
#   HABILITAR_HOTKEY=1 python copiloto_pantalla.py
HABILITAR_HOTKEY = os.getenv("HABILITAR_HOTKEY", "0") == "1"

# Idiomas disponibles en el selector de la UI.
# Clave = lo que ve el usuario en el menú | Valor = como se lo describimos a Claude.
IDIOMAS = {
    "Español": "español",
    "Inglés": "inglés",
    "Portugués": "portugués",
    "Francés": "francés",
}

# Cada modo define la instrucción de sistema que recibe Claude.
# {idioma} se completa en tiempo de ejecución con la selección del usuario.
MODOS = {
    "Resumen": (
        "Presenta un resumen minimalista y claro con los puntos más "
        "importantes del texto, en {idioma}. Agrupa elementos repetitivos "
        "(como títulos de videos o ítems de menú) de forma inteligente."
    ),
    "Traducción completa": (
        "Traducí todo el contenido al {idioma} de forma completa y fiel, "
        "corrigiendo errores evidentes de lectura del OCR, sin resumir."
    ),
    "Solo limpieza": (
        "Corregí únicamente los errores de lectura del OCR y ordená el "
        "texto de forma prolija, sin traducir ni resumir. Mantené el "
        "idioma original."
    ),
}


class TraductorFlotante:
    """Ventana flotante principal de la aplicación.

    Encapsula tanto la interfaz (tkinter) como la lógica de captura,
    OCR y llamada a la API de Claude. Se instancia una sola vez, sobre
    la raíz de tkinter (`root`), en el bloque `if __name__ == "__main__"`.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Copiloto de Pantalla")

        # --- Configuración de ventana flotante ---
        # Cada atributo se envuelve por separado: en algunos entornos Linux
        # (sandboxes tipo Snap/Flatpak, sesiones sin compositor) alguno de
        # estos puede no estar soportado. Si eso pasa, preferimos avisar por
        # consola y seguir con una ventana normal antes que dejar la app en
        # un estado a medio construir e invisible.
        try:
            self.root.overrideredirect(True)  # Quita los bordes de ventana clásica
        except Exception as e:
            print(f"[Aviso] No se pudieron quitar los bordes de ventana: {e}")

        try:
            self.root.attributes("-topmost", True)  # Siempre visible arriba de todo
        except Exception as e:
            print(f"[Aviso] No se pudo fijar 'siempre visible': {e}")

        try:
            self.root.attributes("-alpha", 0.95)  # Transparencia sutil
        except Exception as e:
            print(f"[Aviso] Transparencia no soportada en este entorno: {e}")
            print("Esto es común sin un compositor activo (ej. algunos sandboxes o WMs mínimos).")

        self.window_w = 380
        self.window_h = 340

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.window_x = (screen_width // 2) - (self.window_w // 2)
        self.window_y = (screen_height // 2) - (self.window_h // 2)
        self.root.geometry(f"{self.window_w}x{self.window_h}+{self.window_x}+{self.window_y}")

        self.cargando = False
        self.idioma_var = tk.StringVar(value="Español")
        self.modo_var = tk.StringVar(value="Resumen")

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
            self.title_bar, text="Copiloto de Pantalla", bg="#11111b",
            fg="#cdd6f4", font=("Arial", 9, "bold")
        )
        self.title_label.pack(side="left", padx=10)

        self.close_btn = tk.Button(
            self.title_bar, text="✕", bg="#11111b", fg="#f38ba8", bd=0,
            activebackground="#f38ba8", activeforeground="#11111b",
            command=self._ocultar_a_tray, font=("Arial", 9)
        )
        self.close_btn.pack(side="right", padx=10)

        # --- Panel de opciones (idioma + modo) ---
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

        # --- Botonera inferior ---
        self.btn_frame = tk.Frame(self.main_frame, bg="#1e1e2e")
        self.btn_frame.pack(fill="x", side="bottom", padx=10, pady=10)

        self.action_btn = tk.Button(
            self.btn_frame, text="Capturar (Ctrl+Alt+S)", bg="#89b4fa", fg="#11111b",
            activebackground="#b4befe", bd=0, font=("Arial", 10, "bold"),
            command=self.procesar_pantalla, height=2
        )
        self.action_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.copy_btn = tk.Button(
            self.btn_frame, text="Copiar", bg="#313244", fg="#cdd6f4",
            activebackground="#45475a", bd=0, font=("Arial", 10, "bold"),
            command=self.copiar_al_portapapeles, height=2
        )
        self.copy_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))

        self.text_area = tk.Text(
            self.main_frame, bg="#1e1e2e", fg="#cdd6f4", insertbackground="white",
            relief="flat", font=("Arial", 10), wrap="word", padx=10, pady=10
        )
        self.text_area.pack(fill="both", expand=True)
        self.text_area.insert("1.0", "Presioná 'Capturar' o Ctrl+Alt+S para procesar la pantalla...")

        self.title_bar.bind("<ButtonPress-1>", self.iniciar_arrastre)
        self.title_bar.bind("<B1-Motion>", self.arrastrar_ventana)

    # --------------------------------------------------------
    #  Hotkey global
    # --------------------------------------------------------
    def _configurar_hotkey(self):
        """Registra Ctrl+Alt+S como atajo global (funciona aunque la
        ventana no tenga el foco). Desactivado por defecto (ver
        HABILITAR_HOTKEY más arriba): en Linux, sin permisos de root,
        esto puede demorar varios segundos antes de fallar, y ese lapso
        deja la ventana armada pero sin pintarse."""
        if not HOTKEY_DISPONIBLE:
            return
        if not HABILITAR_HOTKEY:
            print("[Info] Hotkey global desactivado por defecto. "
                  "Para probarlo: HABILITAR_HOTKEY=1 python copiloto_pantalla.py")
            return
        try:
            # En Linux, 'keyboard' suele necesitar permisos de root para leer
            # /dev/input directamente. En Windows funciona sin privilegios especiales.
            keyboard.add_hotkey("ctrl+alt+s", lambda: self.root.after(0, self.procesar_pantalla))
        except Exception:
            # Si falla (permisos insuficientes), la app sigue funcionando con el botón.
            pass

    # --------------------------------------------------------
    #  Ícono de bandeja (system tray)
    # --------------------------------------------------------
    def _configurar_tray(self):
        """Crea el ícono de bandeja del sistema. En Linux, pystray depende
        de librerías del sistema operativo (GTK / AppIndicator) que NO se
        instalan con pip — si faltan, pystray.Icon() puede fallar acá.
        Por eso todo el bloque está protegido: si algo sale mal, se
        desactiva el tray y la app sigue funcionando con el botón normal,
        en vez de crashear con una ventana en blanco sin mainloop.

        Además, está desactivado por defecto (ver HABILITAR_TRAY más
        arriba): el hilo de GTK que necesita pystray.Icon.run() puede
        colgar el proceso en ciertos entornos Linux sin avisar."""
        if not TRAY_DISPONIBLE:
            return
        if not HABILITAR_TRAY:
            print("[Info] Ícono de bandeja desactivado por defecto. "
                  "Para probarlo: HABILITAR_TRAY=1 python copiloto_pantalla.py")
            self.tray_icon = None
            return
        try:
            icono_img = PILImage.new("RGB", (32, 32), "#89b4fa")
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar / Capturar", self._mostrar_desde_tray, default=True),
                pystray.MenuItem("Salir", self._salir_desde_tray),
            )
            self.tray_icon = pystray.Icon("copiloto", icono_img, "Copiloto de Pantalla", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"[Aviso] No se pudo iniciar el ícono de bandeja: {e}")
            print("La app va a seguir funcionando normalmente, solo sin ese ícono.")
            self.tray_icon = None

    def _ocultar_a_tray(self):
        """Con el tray desactivado (caso normal ahora), este botón cierra
        la app directamente. Si en algún momento activás HABILITAR_TRAY=1
        y el ícono arrancó bien, en cambio minimiza a la bandeja."""
        if HABILITAR_TRAY and getattr(self, "tray_icon", None):
            self.root.withdraw()
        else:
            self.root.destroy()

    def _mostrar_desde_tray(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def _salir_desde_tray(self, icon=None, item=None):
        if getattr(self, "tray_icon", None):
            self.tray_icon.stop()
        self.root.after(0, self.root.quit)

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
        estados_no_copiables = [
            "Presioná 'Capturar' o Ctrl+Alt+S para procesar la pantalla...",
            "No se detectó texto en la pantalla.",
        ]
        if contenido and contenido not in estados_no_copiables and not self.cargando:
            self.root.clipboard_clear()
            self.root.clipboard_append(contenido)
            self.copy_btn.config(text="¡Copiado!", bg="#a6e3a1", fg="#11111b")
            self.root.after(1500, self._restaurar_boton_copiar)

    def _restaurar_boton_copiar(self):
        self.copy_btn.config(text="Copiar", bg="#313244", fg="#cdd6f4")

    # --------------------------------------------------------
    #  Captura + OCR + Claude
    # --------------------------------------------------------
    def procesar_pantalla(self):
        """Punto de entrada de una captura: valida que no haya otra en
        curso, guarda la posición/tamaño actual de la ventana (los
        necesitamos después para saber en qué monitor está), la oculta
        para que no aparezca en su propia foto, y delega el trabajo
        pesado a un hilo aparte tras una breve espera de redibujado."""
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
        self.root.after(200, self._iniciar_hilo_procesamiento)

    def _iniciar_hilo_procesamiento(self):
        thread = threading.Thread(target=self._hilo_ocr_y_api, daemon=True)
        thread.start()

    @staticmethod
    def _preprocesar_para_ocr(img):
        """Mejora la precisión de Tesseract antes de leer el texto.

        Tesseract funciona mejor sobre imágenes en escala de grises con
        buen contraste que sobre una captura a color "cruda" — reduce
        falsos positivos por antialiasing, sombras y fondos con color.
        El factor 1.8 de contraste es un valor empírico razonable para
        texto de UI (webs, apps); si el texto sale muy fragmentado se
        puede subir a 2.0-2.5, o bajarlo si aparecen manchas negras.
        """
        gris = img.convert("L")
        contraste = ImageEnhance.Contrast(gris).enhance(1.8)
        return contraste

    def _hilo_ocr_y_api(self):
        """Corre en un hilo secundario (nunca en el hilo principal de
        tkinter) porque hace tres cosas potencialmente lentas: capturar
        la pantalla, correr OCR, y esperar la respuesta de la API de
        Claude. Si esto corriera en el hilo principal, la ventana se
        congelaría (no se podría mover ni cerrar) mientras procesa."""
        try:
            self._actualizar_texto_seguro("Capturando pantalla...")
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
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            extrema = img.convert("L").getextrema()
            if extrema == (0, 0):
                mensaje_wayland = (
                    "Se capturó una pantalla negra.\n\n"
                    "Esto ocurre porque estás usando una sesión de Wayland (Ubuntu 24.04).\n"
                    "Por seguridad, Wayland bloquea las capturas de pantalla automáticas.\n\n"
                    "Solución: cerrá sesión, elegí 'Ubuntu en Xorg' en el ícono de "
                    "engranaje del login, y volvé a iniciar sesión."
                )
                self._finalizar_con_mensaje(mensaje_wayland)
                return

            self._actualizar_texto_seguro("Ejecutando OCR...")
            img_ocr = self._preprocesar_para_ocr(img)
            texto_extraido = pytesseract.image_to_string(img_ocr, lang="spa+eng")

            if not texto_extraido.strip():
                self._finalizar_con_mensaje("No se detectó texto en la pantalla.")
                return

            self.root.after(0, self._iniciar_animacion)

            idioma = IDIOMAS[self.idioma_var.get()]
            instruccion_modo = MODOS[self.modo_var.get()].format(idioma=idioma)

            prompt_sistema = (
                "Sos un copiloto de pantalla avanzado. Procesás texto bruto extraído "
                "de una captura de pantalla mediante OCR, que puede tener errores de "
                "tipeo o estar desordenado.\n\n"
                f"Tarea específica para esta consulta: {instruccion_modo}"
            )

            respuesta = self.client.messages.create(
                model="claude-sonnet-5",
                max_tokens=1200,
                system=prompt_sistema,
                messages=[
                    {"role": "user", "content": f"Texto extraído de la pantalla:\n\n{texto_extraido}"}
                ],
            )
            resultado = respuesta.content[0].text
            self._finalizar_con_resultado(resultado)

        except pytesseract.TesseractNotFoundError:
            instrucciones = (
                "Error: No se encontró Tesseract OCR en el sistema.\n\n"
                "• Windows: descargá el instalador desde github.com/UB-Mannheim/tesseract/wiki\n"
                "• Linux: sudo apt install tesseract-ocr tesseract-ocr-spa\n"
                "• macOS: brew install tesseract tesseract-lang"
            )
            self._finalizar_con_mensaje(instrucciones)
        except Exception as e:
            self._finalizar_con_mensaje(f"Error en el proceso:\n{str(e)}")

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
        self._cambiar_contenido_texto(f"Claude está analizando la pantalla{dots}")
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
    print("[Diagnóstico] Iniciando... configurando Tesseract.")
    configurar_tesseract()
    print("[Diagnóstico] Creando ventana raíz de tkinter.")
    root = tk.Tk()
    print("[Diagnóstico] Construyendo la interfaz (TraductorFlotante).")
    app = TraductorFlotante(root)
    print("[Diagnóstico] Interfaz construida sin errores. Entrando al mainloop.")
    root.mainloop()
    print("[Diagnóstico] mainloop finalizado (la ventana se cerró).")

