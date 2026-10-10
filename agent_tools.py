"""
agent_tools.py
==============

Le da "manos" a Claude (tool use / function calling). Por ahora, una sola
herramienta: guardar un registro estructurado (factura, tarea, producto,
etc.) que aparezca en la captura de pantalla, directamente en un archivo
Excel local — sin que el usuario tenga que copiar y pegar nada a mano.

Si en el futuro se agregan más herramientas (por ejemplo, guardar en una
base de datos, o mandar un mensaje), este es el lugar natural para sumarlas:
cada una necesita (1) su definición en formato tool schema y (2) su función
`ejecutar_...` correspondiente.
"""

import os
from datetime import datetime
from openpyxl import Workbook, load_workbook

# El Excel se guarda al lado de este script, no en un directorio temporal,
# para que sobreviva entre ejecuciones y sea fácil de encontrar.
RUTA_REGISTROS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "registros_qubit.xlsx"
)
ENCABEZADOS = ["Fecha", "Categoría", "Título", "Valor", "Detalle"]


# ------------------------------------------------------------------
#  Definición de la herramienta (lo que Claude "ve" para decidir usarla)
# ------------------------------------------------------------------
TOOL_GUARDAR_REGISTRO = {
    "name": "guardar_registro",
    "description": (
        "Guarda un dato estructurado extraído de la captura de pantalla "
        "(por ejemplo, una fila de una factura, un ítem de una lista de "
        "tareas, o un producto con su precio) en un archivo Excel local, "
        "para que el usuario lo tenga organizado sin copiarlo a mano. "
        "Usar ÚNICAMENTE cuando el contenido sea claramente un dato "
        "estructurado que valga la pena archivar — no para texto genérico, "
        "resúmenes, o contenido que no representa un registro concreto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "categoria": {
                "type": "string",
                "description": "Tipo de dato: 'factura', 'tarea', 'producto', u 'otro'.",
            },
            "titulo": {
                "type": "string",
                "description": (
                    "Título o descripción corta del ítem (ej: nombre del "
                    "producto, título de la tarea, proveedor de la factura)."
                ),
            },
            "valor": {
                "type": "string",
                "description": (
                    "Valor numérico relevante si existe (precio, monto, "
                    "cantidad), como texto. Vacío si no aplica."
                ),
            },
            "detalle": {
                "type": "string",
                "description": "Cualquier detalle adicional relevante, en una frase corta.",
            },
        },
        "required": ["categoria", "titulo"],
    },
}


# ------------------------------------------------------------------
#  Ejecución real de la herramienta
# ------------------------------------------------------------------
def _asegurar_archivo():
    """Crea el Excel con encabezados si todavía no existe."""
    if not os.path.isfile(RUTA_REGISTROS):
        wb = Workbook()
        ws = wb.active
        ws.title = "Registros"
        ws.append(ENCABEZADOS)
        wb.save(RUTA_REGISTROS)


def ejecutar_guardar_registro(datos: dict) -> str:
    """Agrega una fila al Excel de registros. `datos` viene directamente
    del `tool_use.input` que devuelve la API — ya validado contra el
    input_schema de arriba, así que se puede confiar en su forma."""
    _asegurar_archivo()
    wb = load_workbook(RUTA_REGISTROS)
    ws = wb["Registros"]
    fila = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        datos.get("categoria", ""),
        datos.get("titulo", ""),
        datos.get("valor", ""),
        datos.get("detalle", ""),
    ]
    ws.append(fila)
    wb.save(RUTA_REGISTROS)
    return f"Guardado en {os.path.basename(RUTA_REGISTROS)}: {datos.get('titulo', '(sin título)')}"
