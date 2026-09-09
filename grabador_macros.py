import sys
import os
import time
import json
import ctypes
import threading
from typing import List, Dict, Any

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QCheckBox, QSpinBox, QDoubleSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QGroupBox,
    QFrame, QSlider, QSplitter, QStyle
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QIcon, QKeySequence

from pynput import mouse, keyboard

# --- ACTIVACIÓN DE PRECISIÓN DPI EN WINDOWS ---
def activar_dpi_awareness():
    if sys.platform == 'win32':
        try:
            # Per Monitor DPI Aware V2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessInternal(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDpiAwareness(1)
                except Exception:
                    pass

activar_dpi_awareness()

# --- CLASE HILO DE REPRODUCCIÓN (PLAYBACK) ---
class HiloReproduccion(QThread):
    progreso_iteracion = pyqtSignal(int, int) # (iteracion_actual, total_iteraciones)
    accion_ejecutada = pyqtSignal(int, int)   # (indice_accion, total_acciones)
    estado_cambiado = pyqtSignal(str)
    finalizado = pyqtSignal()

    def __init__(self, acciones: List[Dict[str, Any]], infinitas: bool, max_iteraciones: int, retardo_bucle: float, velocidad: float):
        super().__init__()
        self.acciones = acciones
        self.infinitas = infinitas
        self.max_iteraciones = max_iteraciones
        self.retardo_bucle = retardo_bucle
        self.velocidad = max(0.01, velocidad)
        self.solicitante_parada = False
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()

    def detener(self):
        self.solicitante_parada = True

    def _convertir_tecla(self, key_str: str):
        if key_str.startswith("Key."):
            attr = key_str.split(".")[1]
            if hasattr(keyboard.Key, attr):
                return getattr(keyboard.Key, attr)
        elif key_str.startswith("vk:"):
            try:
                vk_code = int(key_str.split(":")[1])
                return keyboard.KeyCode.from_vk(vk_code)
            except Exception:
                pass
        return key_str

    def run(self):
        if not self.acciones:
            self.finalizado.emit()
            return

        iteracion = 0
        total_acciones = len(self.acciones)

        while not self.solicitante_parada:
            iteracion += 1
            if not self.infinitas and iteracion > self.max_iteraciones:
                break

            self.progreso_iteracion.emit(iteracion, 0 if self.infinitas else self.max_iteraciones)
            
            for idx, acc in enumerate(self.acciones):
                if self.solicitante_parada:
                    break

                self.accion_ejecutada.emit(idx + 1, total_acciones)

                # Respetar retardo de la acción adaptado a la velocidad
                delay = acc.get("delay", 0.0) / self.velocidad
                if delay > 0:
                    # Dormir en micro-intervalos para respuesta instantánea de parada
                    tiempo_fin = time.perf_counter() + delay
                    while time.perf_counter() < tiempo_fin:
                        if self.solicitante_parada:
                            break
                        time.sleep(min(0.005, max(0.0, tiempo_fin - time.perf_counter())))

                if self.solicitante_parada:
                    break

                # Ejecución Pixel-Perfect de la Acción
                tipo = acc.get("tipo")
                try:
                    if tipo == "mouse_move":
                        self.mouse_controller.position = (acc["x"], acc["y"])
                    elif tipo == "mouse_click":
                        self.mouse_controller.position = (acc["x"], acc["y"])
                        btn_name = acc.get("button", "left")
                        btn = mouse.Button.left
                        if btn_name == "right":
                            btn = mouse.Button.right
                        elif btn_name == "middle":
                            btn = mouse.Button.middle
                        
                        if acc.get("pressed", True):
                            self.mouse_controller.press(btn)
                        else:
                            self.mouse_controller.release(btn)
                    elif tipo == "mouse_scroll":
                        self.mouse_controller.position = (acc["x"], acc["y"])
                        self.mouse_controller.scroll(acc.get("dx", 0), acc.get("dy", 0))
                    elif tipo == "key_press":
                        k = self._convertir_tecla(acc["key"])
                        self.keyboard_controller.press(k)
                    elif tipo == "key_release":
                        k = self._convertir_tecla(acc["key"])
                        self.keyboard_controller.release(k)
                except Exception as e:
                    print(f"Error al reproducir acción {idx}: {e}")

            # Retardo entre bucles
            if not self.solicitante_parada and (self.infinitas or iteracion < self.max_iteraciones):
                if self.retardo_bucle > 0:
                    tiempo_fin = time.perf_counter() + self.retardo_bucle
                    while time.perf_counter() < tiempo_fin:
                        if self.solicitante_parada:
                            break
                        time.sleep(min(0.01, max(0.0, tiempo_fin - time.perf_counter())))

        self.finalizado.emit()


# --- VENTANA PRINCIPAL DE LA APLICACIÓN ---
class GrabadorMacrosApp(QMainWindow):
    signal_tecla_global = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Grabador de Acciones Ratón y Teclado | Pixel-Perfect & Bucle Infinito")
        self.resize(1000, 700)
        self.setMinimumSize(850, 550)

        # Estado de la macro
        self.acciones: List[Dict[str, Any]] = []
        self.grabando = False
        self.reproduciendo = False
        self.ultimo_tiempo = 0.0

        # Escuchadores de pynput
        self.mouse_listener = None
        self.keyboard_listener = None
        self.global_hotkey_listener = None
        self.hilo_playback = None

        self.signal_tecla_global.connect(self.procesar_hotkey_global)

        self._iniciar_estilos()
        self._iniciar_ui()
        self._iniciar_hotkeys_globales()

        # Timer para actualizar posición del ratón en la barra de estado
        self.timer_pos = QTimer(self)
        self.timer_pos.timeout.connect(self._actualizar_posicion_raton_live)
        self.timer_pos.start(50)

    def _iniciar_estilos(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f172a;
            }
            QWidget {
                color: #f8fafc;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                margin-top: 12px;
                font-weight: bold;
                padding-top: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #38bdf8;
            }
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                border: none;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            QPushButton:pressed {
                background-color: #1e293b;
            }
            QPushButton#btnRecord {
                background-color: #dc2626;
            }
            QPushButton#btnRecord:hover {
                background-color: #ef4444;
            }
            QPushButton#btnPlay {
                background-color: #16a34a;
            }
            QPushButton#btnPlay:hover {
                background-color: #22c55e;
            }
            QPushButton#btnStop {
                background-color: #eab308;
                color: #0f172a;
            }
            QPushButton#btnStop:hover {
                background-color: #facc15;
            }
            QTableWidget {
                background-color: #0f172a;
                border: 1px solid #334155;
                gridline-color: #1e293b;
                border-radius: 8px;
                color: #e2e8f0;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #38bdf8;
                padding: 6px;
                border: none;
                font-weight: bold;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #0f172a;
                border: 1px solid #334155;
                padding: 6px;
                border-radius: 6px;
                color: #ffffff;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #0f172a;
            }
            QCheckBox::indicator:checked {
                background-color: #38bdf8;
                border-color: #38bdf8;
            }
            QLabel#lblEstado {
                font-size: 15px;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 20px;
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
            }
        """)

    def _iniciar_ui(self):
        widget_central = QWidget()
        self.setCentralWidget(widget_central)
        main_layout = QVBoxLayout(widget_central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # --- CABECERA Y ESTADO ---
        top_layout = QHBoxLayout()
        
        lbl_titulo = QLabel("⚡ Grabador de Acciones Pixel-Perfect")
        lbl_titulo.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_titulo.setStyleSheet("color: #38bdf8;")
        
        self.lbl_estado = QLabel("🟢 ESTADO: LISTO")
        self.lbl_estado.setObjectName("lblEstado")

        top_layout.addWidget(lbl_titulo)
        top_layout.addStretch()
        top_layout.addWidget(self.lbl_estado)
        main_layout.addLayout(top_layout)

        # --- PANEL DE CONTROL PRINCIPAL ---
        panel_botones = QHBoxLayout()
        
        self.btn_grabar = QPushButton("🔴 Grabar (F8)")
        self.btn_grabar.setObjectName("btnRecord")
        self.btn_grabar.clicked.connect(self.alternar_grabacion)

        self.btn_reproducir = QPushButton("▶ Reproducir (F4)")
        self.btn_reproducir.setObjectName("btnPlay")
        self.btn_reproducir.clicked.connect(self.alternar_reproduccion)

        self.btn_detener = QPushButton("⏹ Detener (ESC)")
        self.btn_detener.setObjectName("btnStop")
        self.btn_detener.clicked.connect(self.detener_todo)

        self.btn_limpiar = QPushButton("🗑 Limpiar Macro")
        self.btn_limpiar.clicked.connect(self.limpiar_macro)

        self.btn_guardar = QPushButton("💾 Guardar JSON")
        self.btn_guardar.clicked.connect(self.guardar_macro)

        self.btn_cargar = QPushButton("📂 Cargar JSON")
        self.btn_cargar.clicked.connect(self.cargar_macro)

        panel_botones.addWidget(self.btn_grabar)
        panel_botones.addWidget(self.btn_reproducir)
        panel_botones.addWidget(self.btn_detener)
        panel_botones.addWidget(self.btn_limpiar)
        panel_botones.addSpacing(10)
        panel_botones.addWidget(self.btn_guardar)
        panel_botones.addWidget(self.btn_cargar)
        main_layout.addLayout(panel_botones)

        # --- CONFIGURACIÓN Y TABLA EN SPLITTER ---
        splitter = QSplitter(Qt.Horizontal)

        # Configuración (Izquierda)
        grupo_config = QGroupBox("⚙️ Configuración de Reproducción")
        layout_config = QVBoxLayout(grupo_config)
        layout_config.setSpacing(14)

        # Opción Bucle Infinito
        self.chk_infinito = QCheckBox("🔁 Repetir en Bucle Infinito")
        self.chk_infinito.setChecked(True)
        self.chk_infinito.toggled.connect(self._actualizar_estado_spin_iteraciones)
        layout_config.addWidget(self.chk_infinito)

        # Iteraciones fijas
        layout_iter = QHBoxLayout()
        lbl_iter = QLabel("Número de Iteraciones:")
        self.spin_iter = QSpinBox()
        self.spin_iter.setRange(1, 1000000)
        self.spin_iter.setValue(1)
        self.spin_iter.setEnabled(False)
        layout_iter.addWidget(lbl_iter)
        layout_iter.addWidget(self.spin_iter)
        layout_config.addLayout(layout_iter)

        # Retardo entre bucles
        layout_delay_bucle = QHBoxLayout()
        lbl_delay_bucle = QLabel("Pausa entre Bucles (s):")
        self.spin_delay_bucle = QDoubleSpinBox()
        self.spin_delay_bucle.setRange(0.0, 3600.0)
        self.spin_delay_bucle.setSingleStep(0.5)
        self.spin_delay_bucle.setValue(0.0)
        layout_delay_bucle.addWidget(lbl_delay_bucle)
        layout_delay_bucle.addWidget(self.spin_delay_bucle)
        layout_config.addLayout(layout_delay_bucle)

        # Velocidad de reproducción
        layout_vel = QVBoxLayout()
        self.lbl_velocidad = QLabel("Velocidad de Reproducción: 1.0x")
        self.slider_vel = QSlider(Qt.Horizontal)
        self.slider_vel.setRange(1, 50) # 0.1x a 5.0x
        self.slider_vel.setValue(10) # 1.0x
        self.slider_vel.valueChanged.connect(self._actualizar_etiqueta_velocidad)
        layout_vel.addWidget(self.lbl_velocidad)
        layout_vel.addWidget(self.slider_vel)
        layout_config.addLayout(layout_vel)

        # Filtro de movimiento del ratón
        self.chk_movimiento_continuo = QCheckBox("🖱️ Grabar Movimiento Continuo del Ratón")
        self.chk_movimiento_continuo.setChecked(True)
        layout_config.addWidget(self.chk_movimiento_continuo)

        # Guía de atajos
        info_box = QFrame()
        info_box.setStyleSheet("background-color: #0f172a; border-radius: 8px; padding: 10px;")
        info_layout = QVBoxLayout(info_box)
        info_layout.addWidget(QLabel("<b>Atajos Globales de Teclado:</b>"))
        info_layout.addWidget(QLabel("• <b>F8</b>: Iniciar / Parar Grabación"))
        info_layout.addWidget(QLabel("• <b>F4</b>: Iniciar / Parar Reproducción"))
        info_layout.addWidget(QLabel("• <b>ESC</b>: Parada de Emergencia"))
        layout_config.addWidget(info_box)

        layout_config.addStretch()
        splitter.addWidget(grupo_config)

        # Tabla de Acciones (Derecha)
        grupo_tabla = QGroupBox("📋 Lista de Acciones Grabadas")
        layout_tabla = QVBoxLayout(grupo_tabla)

        self.tabla = QTableWidget()
        self.tabla.setColumnCount(5)
        self.tabla.setHorizontalHeaderLabels(["#", "Tipo de Acción", "Detalle / Tecla", "Coordenadas (X, Y)", "Retardo (s)"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout_tabla.addWidget(self.tabla)

        splitter.addWidget(grupo_tabla)
        splitter.setSizes([320, 680])
        main_layout.addWidget(splitter)

        # --- BARRA DE ESTADO INFERIOR ---
        self.lbl_cursor_live = QLabel("🎯 Cursor: X: 0 | Y: 0")
        self.lbl_cursor_live.setStyleSheet("color: #38bdf8; font-weight: bold;")
        self.statusBar().addPermanentWidget(self.lbl_cursor_live)

    def _actualizar_estado_spin_iteraciones(self, infinito: bool):
        self.spin_iter.setEnabled(not infinito)

    def _actualizar_etiqueta_velocidad(self, val: int):
        vel = val / 10.0
        self.lbl_velocidad.setText(f"Velocidad de Reproducción: {vel:.1f}x")

    def _actualizar_posicion_raton_live(self):
        try:
            x, y = mouse.Controller().position
            self.lbl_cursor_live.setText(f"🎯 Coordenada Pixel-Perfect: X: {int(x)} | Y: {int(y)}")
        except Exception:
            pass

    # --- ATAJOS GLOBALES ---
    def _iniciar_hotkeys_globales(self):
        def on_press(key):
            try:
                if key == keyboard.Key.f8:
                    self.signal_tecla_global.emit("F8")
                elif key == keyboard.Key.f4:
                    self.signal_tecla_global.emit("F4")
                elif key == keyboard.Key.esc:
                    self.signal_tecla_global.emit("ESC")
            except Exception as e:
                print(f"Error en hotkey global: {e}")

        self.global_hotkey_listener = keyboard.Listener(on_press=on_press)
        self.global_hotkey_listener.daemon = True
        self.global_hotkey_listener.start()

    def procesar_hotkey_global(self, tecla: str):
        if tecla == "F8":
            self.alternar_grabacion()
        elif tecla == "F4":
            self.alternar_reproduccion()
        elif tecla == "ESC":
            self.detener_todo()

    # --- LÓGICA DE GRABACIÓN ---
    def alternar_grabacion(self):
        if self.reproduciendo:
            return
        if self.grabando:
            self.detener_grabacion()
        else:
            self.iniciar_grabacion()

    def iniciar_grabacion(self):
        self.acciones.clear()
        self.actualizar_tabla()
        self.grabando = True
        self.ultimo_tiempo = time.perf_counter()

        self.lbl_estado.setText("🔴 GRABANDO... (Pulsa F8 para parar)")
        self.lbl_estado.setStyleSheet("background-color: #7f1d1d; color: #fca5a5; border-color: #ef4444;")
        self.btn_grabar.setText("⏹ Detener Grabación (F8)")

        # Iniciar escuchadores del ratón y teclado
        self.mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )

        self.mouse_listener.start()
        self.keyboard_listener.start()

    def detener_grabacion(self):
        if not self.grabando:
            return
        self.grabando = False

        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

        # Filtrar la tecla F8 al detener si se grabó como última acción
        if self.acciones and self.acciones[-1].get("key") in ["Key.f8", "F8"]:
            self.acciones.pop()

        self.lbl_estado.setText(f"🟢 LISTO ({len(self.acciones)} acciones grabadas)")
        self.lbl_estado.setStyleSheet("background-color: #1e293b; color: #38bdf8; border-color: #334155;")
        self.btn_grabar.setText("🔴 Grabar (F8)")
        self.actualizar_tabla()

    def _calcular_delay(self) -> float:
        ahora = time.perf_counter()
        delay = ahora - self.ultimo_tiempo
        self.ultimo_tiempo = ahora
        return round(delay, 4)

    def _on_mouse_move(self, x, y):
        if not self.grabando or not self.chk_movimiento_continuo.isChecked():
            return
        self.acciones.append({
            "tipo": "mouse_move",
            "x": int(x),
            "y": int(y),
            "delay": self._calcular_delay()
        })

    def _on_mouse_click(self, x, y, button, pressed):
        if not self.grabando:
            return
        self.acciones.append({
            "tipo": "mouse_click",
            "x": int(x),
            "y": int(y),
            "button": button.name,
            "pressed": pressed,
            "delay": self._calcular_delay()
        })

    def _on_mouse_scroll(self, x, y, dx, dy):
        if not self.grabando:
            return
        self.acciones.append({
            "tipo": "mouse_scroll",
            "x": int(x),
            "y": int(y),
            "dx": dx,
            "dy": dy,
            "delay": self._calcular_delay()
        })

    def _on_key_press(self, key):
        if not self.grabando:
            return
        key_str = self._key_to_string(key)
        if key_str in ["Key.f8", "Key.f4", "Key.esc"]:
            return
        self.acciones.append({
            "tipo": "key_press",
            "key": key_str,
            "delay": self._calcular_delay()
        })

    def _on_key_release(self, key):
        if not self.grabando:
            return
        key_str = self._key_to_string(key)
        if key_str in ["Key.f8", "Key.f4", "Key.esc"]:
            return
        self.acciones.append({
            "tipo": "key_release",
            "key": key_str,
            "delay": self._calcular_delay()
        })

    def _key_to_string(self, key) -> str:
        if isinstance(key, keyboard.Key):
            return f"Key.{key.name}"
        elif hasattr(key, 'char') and key.char:
            return key.char
        elif hasattr(key, 'vk') and key.vk:
            return f"vk:{key.vk}"
        return str(key)

    # --- LÓGICA DE REPRODUCCIÓN ---
    def alternar_reproduccion(self):
        if self.grabando:
            return
        if self.reproduciendo:
            self.detener_reproduccion()
        else:
            self.iniciar_reproduccion()

    def iniciar_reproduccion(self):
        if not self.acciones:
            QMessageBox.warning(self, "Sin Acciones", "No hay acciones grabadas para reproducir.")
            return

        self.reproduciendo = True
        infinitas = self.chk_infinito.isChecked()
        max_iter = self.spin_iter.value()
        retardo_bucle = self.spin_delay_bucle.value()
        vel = self.slider_vel.value() / 10.0

        self.lbl_estado.setText("▶ REPRODUCIENDO... (Pulsa F4 o ESC para detener)")
        self.lbl_estado.setStyleSheet("background-color: #14532d; color: #86efac; border-color: #22c55e;")
        self.btn_reproducir.setText("⏹ Detener Repr. (F4)")

        self.hilo_playback = HiloReproduccion(self.acciones, infinitas, max_iter, retardo_bucle, vel)
        self.hilo_playback.progreso_iteracion.connect(self._on_progreso_iteracion)
        self.hilo_playback.finalizado.connect(self.detener_reproduccion)
        self.hilo_playback.start()

    def _on_progreso_iteracion(self, actual: int, total: int):
        texto_total = "∞" if total == 0 else str(total)
        self.lbl_estado.setText(f"▶ REPRODUCIENDO BUCLE #{actual} / {texto_total} (Pulsa F4/ESC para detener)")

    def detener_reproduccion(self):
        if not self.reproduciendo:
            return
        self.reproduciendo = False
        if self.hilo_playback:
            self.hilo_playback.detener()
            self.hilo_playback.wait(1000)
            self.hilo_playback = None

        self.lbl_estado.setText("🟢 LISTO")
        self.lbl_estado.setStyleSheet("background-color: #1e293b; color: #38bdf8; border-color: #334155;")
        self.btn_reproducir.setText("▶ Reproducir (F4)")

    def detener_todo(self):
        if self.grabando:
            self.detener_grabacion()
        if self.reproduciendo:
            self.detener_reproduccion()

    def limpiar_macro(self):
        self.detener_todo()
        self.acciones.clear()
        self.actualizar_tabla()
        self.lbl_estado.setText("🟢 LISTO (Macro Limpiada)")

    # --- TABLA Y PERSISTENCIA JSON ---
    def actualizar_tabla(self):
        self.tabla.setRowCount(0)
        for i, acc in enumerate(self.acciones):
            self.tabla.insertRow(i)
            self.tabla.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            
            tipo = acc.get("tipo", "")
            icono = "🖱️" if "mouse" in tipo else "⌨️"
            self.tabla.setItem(i, 1, QTableWidgetItem(f"{icono} {tipo}"))
            
            detalle = ""
            if "mouse" in tipo:
                detalle = f"Boton: {acc.get('button', '')} ({'Presionar' if acc.get('pressed') else 'Soltar'})" if tipo == "mouse_click" else ""
            else:
                detalle = f"Tecla: {acc.get('key', '')} ({'Presionar' if tipo == 'key_press' else 'Soltar'})"
            self.tabla.setItem(i, 2, QTableWidgetItem(detalle))

            coords = f"X: {acc.get('x', '-')}, Y: {acc.get('y', '-')}" if "x" in acc else "-"
            self.tabla.setItem(i, 3, QTableWidgetItem(coords))
            self.tabla.setItem(i, 4, QTableWidgetItem(f"{acc.get('delay', 0.0):.4f}s"))

    def guardar_macro(self):
        if not self.acciones:
            QMessageBox.warning(self, "Macro Vacía", "No hay acciones para guardar.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Guardar Macro JSON", "", "Archivos JSON (*.json)")
        if path:
            data = {
                "version": "1.0",
                "total_acciones": len(self.acciones),
                "acciones": self.acciones
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, "Éxito", f"Macro guardada con éxito en:\n{path}")

    def cargar_macro(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cargar Macro JSON", "", "Archivos JSON (*.json)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.acciones = data.get("acciones", [])
                self.actualizar_tabla()
                QMessageBox.information(self, "Éxito", f"Se cargaron {len(self.acciones)} acciones desde la macro.")
                self.lbl_estado.setText(f"🟢 MACRO CARGADA ({len(self.acciones)} acciones)")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo cargar la macro:\n{e}")

    def closeEvent(self, event):
        self.detener_todo()
        if self.global_hotkey_listener:
            self.global_hotkey_listener.stop()
        event.accept()


# --- PUNTO DE ENTRADA ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    ventana = GrabadorMacrosApp()
    ventana.show()
    sys.exit(app.exec_())
