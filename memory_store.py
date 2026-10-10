"""
memory_store.py
================

Memoria semántica local (RAG ultraligero) con ChromaDB. Cada vez que Qubit
analiza una pantalla, el resultado se guarda acá como un vector. Más tarde,
el usuario puede preguntar algo como "¿qué precio tenía el producto que vi
hace media hora?" — buscamos las capturas más parecidas semánticamente a la
pregunta y se las pasamos a Claude como contexto para que responda.

ChromaDB corre 100% local (no es una API externa) y, si no se le indica lo
contrario, usa un modelo de embeddings liviano que corre en la propia
máquina (se descarga una única vez, ~80MB, la primera vez que se usa).

La base queda guardada en la carpeta ./qubit_memory_db junto al script.
"""

import os
import uuid
from datetime import datetime

import chromadb

RUTA_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qubit_memory_db")

_cliente = None
_coleccion = None


def _obtener_coleccion():
    """Conexión perezosa: recién se crea/abre la base la primera vez que
    hace falta, no al importar el módulo (así el arranque de la app no
    depende de que ChromaDB esté disponible si el usuario no usa memoria)."""
    global _cliente, _coleccion
    if _coleccion is None:
        _cliente = chromadb.PersistentClient(path=RUTA_DB)
        _coleccion = _cliente.get_or_create_collection("capturas_pantalla")
    return _coleccion


def guardar_captura(texto: str, modo: str, idioma: str) -> str:
    """Guarda el resultado de un análisis como un nuevo recuerdo. Devuelve
    el id generado (no se usa por ahora, pero sirve para debug/logs)."""
    coleccion = _obtener_coleccion()
    doc_id = str(uuid.uuid4())
    coleccion.add(
        documents=[texto],
        metadatas=[{
            "modo": modo,
            "idioma": idioma,
            "timestamp": datetime.now().isoformat(timespec="minutes"),
        }],
        ids=[doc_id],
    )
    return doc_id


def buscar_contexto(pregunta: str, n_resultados: int = 3) -> list[dict]:
    """Busca las capturas guardadas más relacionadas semánticamente con la
    pregunta. Devuelve una lista de dicts con 'texto' y 'meta' (vacía si
    todavía no hay nada guardado)."""
    coleccion = _obtener_coleccion()
    total_guardado = coleccion.count()
    if total_guardado == 0:
        return []

    resultados = coleccion.query(
        query_texts=[pregunta],
        n_results=min(n_resultados, total_guardado),
    )
    documentos = resultados.get("documents", [[]])[0]
    metadatas = resultados.get("metadatas", [[]])[0]
    return [{"texto": doc, "meta": meta} for doc, meta in zip(documentos, metadatas)]
