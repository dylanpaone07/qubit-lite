# 🖥️ Copiloto de Pantalla

Aplicación de escritorio multiplataforma (Windows / Linux / macOS) que lee
todo el texto visible en tu pantalla y usa IA para **traducirlo, resumirlo o
limpiarlo** al instante, en una ventana flotante minimalista.

Pensada para estudiantes, docentes y cualquiera que necesite comprender
contenido en otro idioma o simplificar texto denso (artículos, papers,
subtítulos, comentarios, UI de apps) sin salir de lo que está haciendo.

---

## ✨ Funcionalidades

- 📸 Captura de pantalla + OCR (Tesseract) para extraer todo el texto visible
- 🌍 Traducción a español, inglés, portugués o francés
- 📝 Tres modos: **Resumen**, **Traducción completa** o **Solo limpieza**
- ⌨️ Atajo global `Ctrl+Alt+S` para capturar sin usar el mouse
- 🖱️ Ícono en la bandeja del sistema — minimizala sin cerrar el proceso
- 🔒 API key gestionada por variables de entorno (nunca en el código)
- 🖥️ Multiplataforma: Windows, Linux (X11) y macOS

---

## 🚀 Instalación

### 1. Clonar el repo
```bash
git clone https://github.com/dylanpaone07/cubit_copilot.git
cd cubit_copilot
```

### 2. Crear y activar un entorno virtual
```bash
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Instalar Tesseract OCR
| SO | Comando |
|---|---|
| Windows | Instalador desde [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) |
| Linux | `sudo apt install tesseract-ocr tesseract-ocr-spa` |
| macOS | `brew install tesseract tesseract-lang` |

### 5. Configurar tu API key
```bash
cp .env.example .env
```
Editá `.env` y pegá tu key de [Anthropic Console](https://console.anthropic.com/settings/keys):
```
ANTHROPIC_API_KEY=sk-ant-tu-clave-aca
```

### 6. Ejecutar
```bash
python copiloto_pantalla.py
```

---

## 📦 Empaquetar como ejecutable (Windows)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name CopilotoPantalla copiloto_pantalla.py
```
El `.exe` queda en `dist/CopilotoPantalla.exe`. El usuario final necesita
Tesseract instalado por separado (no se empaqueta automáticamente).

---

## ⚠️ Notas por sistema operativo

- **Linux + Wayland (Ubuntu 24.04+)**: la captura de pantalla de apps externas
  está bloqueada por seguridad. La app te avisa y te indica cómo cambiar a
  sesión Xorg desde la pantalla de login.
- **Linux — hotkey global**: la librería `keyboard` necesita permisos de root
  (`sudo python copiloto_pantalla.py`) para leer `/dev/input`. Sin sudo, la
  app funciona igual con el botón "Capturar".
- **macOS**: hay que otorgar permisos de "Grabación de pantalla" y
  "Accesibilidad" en Preferencias del Sistema → Privacidad y Seguridad.

---

## 🔒 Seguridad

Este proyecto **nunca** debe contener tu API key en el código fuente. Se lee
exclusivamente desde `.env`, que está excluido del repo vía `.gitignore`. Si
alguna vez una key se expone públicamente (código, chat, captura), revocala
de inmediato en la Anthropic Console y generá una nueva.

---

## 🗺️ Roadmap

- [ ] Mapas conceptuales generados en formato Mermaid
- [ ] Streaming de la respuesta de Claude en tiempo real
- [ ] Historial de capturas guardado localmente
- [ ] Soporte de más idiomas
- [ ] Integración con UI Automation / AT-SPI2 para lectura de texto sin OCR

---

## 🛠️ Stack técnico

`Python` · `tkinter` · `mss` · `Pillow` · `pytesseract` · `Anthropic API` ·
`python-dotenv` · `keyboard` · `pystray`

---

## 📄 Licencia

Este proyecto es de uso personal/educativo. Agregá una licencia (MIT, por
ejemplo) si pensás abrirlo públicamente.
