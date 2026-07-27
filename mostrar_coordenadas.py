import ctypes
import time
import os
import sys

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

os.system("cls" if os.name == "nt" else "clear")
print("=========================================================")
print("     RASTREAMENTO DE COORDENADAS DO MOUSE (X, Y)")
print("=========================================================")
print(" -> Posicione o mouse no ponto desejado da tela.")
print(" -> Leia as coordenadas abaixo em tempo real.")
print(" -> Pressione CTRL+C no terminal para finalizar.")
print("=========================================================\n")

try:
    while True:
        x, y = get_mouse_pos()
        sys.stdout.write(f"\r[COORDENADAS] X: {x:<5d} | Y: {y:<5d}  ")
        sys.stdout.flush()
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\n\nEncerrado com sucesso.")
