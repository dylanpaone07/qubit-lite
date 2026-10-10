# 🖥️ Qubit Lite

Copiloto de pantalla con visión directa, agente con herramientas, y memoria
semántica local. Ve lo que ves, entiende el contexto visual completo (no
solo texto), puede archivar datos automáticamente, y recuerda lo que ya
analizó para responder preguntas más tarde.

---

## ✨ Las 4 capas

### 1. Visión directa
La captura de pantalla se manda como imagen (Base64) directo a la API de
Claude — sin pasar por OCR. Esto significa que Claude ve el diseño real:
colores, tablas, jerarquía visual, gráficos, no solo texto plano. Más
preciso, especialmente en pantallas con estructura visual compleja.

El OCR local (Tesseract) sigue disponible como modo alternativo — tildá
"OCR local" en la interfaz si preferís gastar menos tokens en pantallas de
solo texto simple.

### 2. Hotkey global — `Ctrl+Shift+S`
Disparás la captura desde cualquier lugar del sistema operativo, sin tener
que ir a buscar la ventana. Activado por defecto; el registro del atajo
corre en su propio hilo, así que nunca bloquea el arranque de la app aunque
tarde o falle (algo que sí podía pasar en versiones anteriores).

### 3. Modo Agente (tool use)
Con el checkbox "Modo Agente" activado, Claude puede decidir guardar datos
estructurados (una factura, una tarea, un producto con precio) directamente
en un Excel local (`registros_qubit.xlsx`), sin que copies nada a mano.
Claude decide cuándo vale la pena guardar algo — no guarda cualquier cosa.

### 4. Memoria semántica local (RAG)
Cada análisis se guarda como vector en una base local (ChromaDB, embeddings
100% locales, sin costo de API extra). Usá el botón "Memoria" para
preguntar cosas como *"¿qué precio tenía el producto que vi hace media
hora?"* — Qubit busca en lo que ya analizó y responde con ese contexto.

---

## 🚀 Instalación

### 1. Entorno virtual
```bash
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
```

### 2. Dependencias
```bash
pip install -r requirements.txt
```
`chromadb` descarga un modelo de embeddings liviano (~80MB) la primera vez
que se usa la Memoria — necesita internet esa primera vez, después queda
cacheado localmente.

### 3. (Opcional) Tesseract, solo si vas a usar "OCR local"
| SO | Comando |
|---|---|
| Windows | Instalador desde [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) |
| Linux | `sudo apt install tesseract-ocr tesseract-ocr-spa` |
| macOS | `brew install tesseract tesseract-lang` |

### 4. API key
```bash
cp .env.example .env
```
Editá `.env` y pegá tu key de [Anthropic Console](https://console.anthropic.com/settings/keys):
```
ANTHROPIC_API_KEY=sk-ant-tu-clave-aca
```

### 5. Ejecutar
```bash
python qubit_lite.py
```

---

## ⚙️ Variables de entorno opcionales

| Variable | Default | Qué hace |
|---|---|---|
| `HABILITAR_HOTKEY` | `1` (activado) | Atajo global Ctrl+Shift+S |
| `HABILITAR_TRAY` | `0` (desactivado) | Ícono de bandeja — experimental en Linux, ver nota abajo |

```bash
HABILITAR_TRAY=1 python qubit_lite.py
```

---

## ⚠️ Notas por sistema operativo

- **Linux + Wayland (Ubuntu 24.04+)**: la captura de pantalla de apps
  externas está bloqueada por seguridad. La app avisa y explica cómo
  cambiar a sesión Xorg desde la pantalla de login.
- **Linux — ícono de bandeja**: `pystray` usa GTK, que no está pensado para
  correr fuera del hilo principal. Puede colgar el proceso en algunos
  entornos — por eso está desactivado por defecto. Si lo probás
  (`HABILITAR_TRAY=1`) y la ventana no responde, es la causa más probable.
- **macOS**: hay que otorgar permisos de "Grabación de pantalla" en
  Preferencias del Sistema → Privacidad y Seguridad.

---

## 🏗️ Arquitectura

```
qubit_lite.py       → UI (tkinter) y orquestación general
vision_engine.py     → Llamadas a Claude con imagen + manejo de tool use
agent_tools.py        → Definición y ejecución de la herramienta "guardar en Excel"
memory_store.py        → ChromaDB: guardar y buscar capturas pasadas
```

Los datos generados (`registros_qubit.xlsx`, carpeta `qubit_memory_db/`) son
tuyos, locales, y están excluidos del repo vía `.gitignore` — no se suben a
GitHub ni se comparten.

---

## 🔒 Seguridad

La API key vive únicamente en `.env`, nunca en el código. Si alguna vez se
expone (código, chat, captura de pantalla), revocala de inmediato en la
Anthropic Console y generá una nueva.

---

## 🗺️ Próximos pasos posibles

- [ ] Más herramientas para el Modo Agente (ej. crear evento de calendario)
- [ ] Streaming de la respuesta en tiempo real
- [ ] Exportar la memoria semántica a un dashboard visual
- [ ] Empaquetado como `.exe` / `.app` para distribución sin Python

---

## 🛠️ Stack técnico

`Python` · `tkinter` · `mss` · `Pillow` · `Anthropic API (visión + tool use)` ·
`ChromaDB` · `openpyxl` · `python-dotenv` · `keyboard` · `pystray` ·
`pytesseract` (opcional)
