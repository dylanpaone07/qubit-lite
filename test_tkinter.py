"""
Test mínimo de tkinter — sin OCR, sin API, sin overrideredirect, sin alpha.
Si esta ventana básica también aparece en blanco o no renderiza el texto,
el problema es 100% del entorno gráfico (Cursor / sandbox / sesión gráfica),
no de nuestra aplicación.

Correr con:  python test_tkinter.py
"""
import tkinter as tk

root = tk.Tk()
root.title("Test básico")
root.geometry("300x150+100+100")

label = tk.Label(root, text="Si ves este texto, tkinter funciona bien.", wraplength=250)
label.pack(expand=True, padx=20, pady=20)

boton = tk.Button(root, text="Cerrar", command=root.destroy)
boton.pack(pady=10)

print("[Diagnóstico] Ventana básica creada. Entrando a mainloop.")
root.mainloop()
print("[Diagnóstico] Ventana básica cerrada correctamente.")
