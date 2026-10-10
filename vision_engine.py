"""
vision_engine.py
=================

Motor de "visión directa": en vez de pasar la captura de pantalla por OCR
(Tesseract) y perder todo el contexto visual (colores, tablas, jerarquía,
gráficos), la imagen se manda tal cual, codificada en Base64, al parámetro
de imagen de la API de Claude. El modelo ve la pantalla real.

Este módulo expone dos funciones:
    - imagen_a_base64(img): prepara la imagen para el envío.
    - analizar_pantalla(...): hace la llamada a la API, con soporte
      opcional de "tool use" (function calling) para el Modo Agente.
"""

import base64
import io
from PIL import Image

# Anthropic recomienda no superar ~1568px en el lado más largo de la imagen:
# pasar ese límite no mejora la precisión y sí consume más tokens (más costo,
# más lento). Si la captura es más grande (típico en monitores 1440p/4K), la
# reducimos nosotros antes de mandarla.
LADO_MAXIMO_RECOMENDADO = 1568


def imagen_a_base64(img: Image.Image) -> str:
    """Redimensiona si hace falta y devuelve la imagen codificada en Base64
    (formato PNG, sin pérdida — importante para no degradar texto pequeño)."""
    ancho, alto = img.size
    lado_mayor = max(ancho, alto)
    if lado_mayor > LADO_MAXIMO_RECOMENDADO:
        factor = LADO_MAXIMO_RECOMENDADO / lado_mayor
        nuevo_tamano = (int(ancho * factor), int(alto * factor))
        img = img.resize(nuevo_tamano, Image.LANCZOS)

    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _armar_prompt_sistema(instruccion_modo: str) -> str:
    return (
        "Sos Qubit, un copiloto de pantalla con visión directa: analizás "
        "capturas de pantalla reales, no texto extraído por OCR. Además del "
        "contenido textual, también podés interpretar diseño, tablas, "
        "gráficos, colores y jerarquía visual para entender mejor el "
        "contexto.\n\n"
        f"Tarea específica para esta consulta: {instruccion_modo}"
    )


def analizar_pantalla(client, img: Image.Image, instruccion_modo: str,
                       tools: list | None = None) -> dict:
    """Envía la captura a Claude y, si se pasan `tools`, maneja el ciclo
    completo de tool use (function calling): si el modelo decide llamar a
    una herramienta, ESTA función NO la ejecuta — devuelve los bloques de
    tool_use para que el llamador (que tiene la lógica de negocio) decida
    qué hacer y arme la segunda vuelta.

    Devuelve un dict con:
        - "respuesta": el objeto Message completo de la API (por si hace
          falta seguir la conversación con tool_result).
        - "texto": el texto de la respuesta ya extraído y unido.
        - "tool_uses": lista de bloques tool_use (vacía si no hubo).
        - "mensaje_usuario": el mensaje original enviado (para reusar en
          la segunda vuelta del tool use).
    """
    imagen_b64 = imagen_a_base64(img)
    prompt_sistema = _armar_prompt_sistema(instruccion_modo)

    mensaje_usuario = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": imagen_b64,
                },
            },
            {"type": "text", "text": "Analizá esta captura de pantalla."},
        ],
    }

    kwargs = dict(
        model="claude-sonnet-5",
        max_tokens=1500,
        system=prompt_sistema,
        messages=[mensaje_usuario],
    )
    if tools:
        kwargs["tools"] = tools

    respuesta = client.messages.create(**kwargs)

    texto = "\n".join(b.text for b in respuesta.content if b.type == "text")
    tool_uses = [b for b in respuesta.content if b.type == "tool_use"]

    return {
        "respuesta": respuesta,
        "texto": texto,
        "tool_uses": tool_uses,
        "mensaje_usuario": mensaje_usuario,
        "prompt_sistema": prompt_sistema,
    }


def continuar_con_resultados_de_tools(client, mensaje_usuario, respuesta_previa,
                                       resultados_tools, prompt_sistema, tools):
    """Segunda vuelta del tool use: le devolvemos a Claude el resultado de
    haber ejecutado la(s) herramienta(s) que pidió, para que redacte la
    respuesta final en lenguaje natural (ej. "Guardé la factura en tu
    Excel: $4500, proveedor XYZ")."""
    mensajes = [
        mensaje_usuario,
        {"role": "assistant", "content": respuesta_previa.content},
        {"role": "user", "content": resultados_tools},
    ]
    respuesta_final = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=800,
        system=prompt_sistema,
        messages=mensajes,
        tools=tools,
    )
    return "\n".join(b.text for b in respuesta_final.content if b.type == "text")
