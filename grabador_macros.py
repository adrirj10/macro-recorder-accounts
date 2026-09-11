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
    QFrame, QSlider, QSplitter, QStyle, QTabWidget
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

# --- HELPER SONIDO DE ALERTA ---
def reproducir_sonido_alerta():
    def _beep():
        if sys.platform == 'win32':
            try:
                import winsound
                winsound.Beep(1000, 400)  # 1000 Hz, 400 ms
                return
            except Exception:
                pass
        else:
            # Linux: intentar con paplay (PulseAudio), beep, o speaker-test
            import subprocess
            try:
                # Generar un beep con paplay usando un archivo WAV temporal
                import wave, struct, tempfile
                fname = tempfile.mktemp(suffix='.wav')
                sample_rate = 44100
                duration = 0.4  # segundos
                freq = 1000  # Hz
                num_samples = int(sample_rate * duration)
                with wave.open(fname, 'w') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    for i in range(num_samples):
                        val = int(32767 * 0.5 * __import__('math').sin(2 * __import__('math').pi * freq * i / sample_rate))
                        wf.writeframes(struct.pack('<h', val))
                subprocess.Popen(['paplay', fname], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
            try:
                subprocess.Popen(['beep', '-f', '1000', '-l', '400'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
        # Fallback universal
        try:
            QApplication.beep()
        except Exception:
            pass
    threading.Thread(target=_beep, daemon=True).start()

# --- CLASE HILO DE REPRODUCCIÓN (PLAYBACK) ---
class HiloReproduccion(QThread):
    progreso_iteracion = pyqtSignal(int, int) # (iteracion_actual, total_iteraciones)
    accion_ejecutada = pyqtSignal(int, int)   # (indice_accion, total_acciones)
    cambio_macro_ejecutando = pyqtSignal(str, int) # (nombre_macro, iteracion)
    estado_cambiado = pyqtSignal(str)
    intervencion_requerida = pyqtSignal(str)  # (nombre_macro)
    intervencion_reanudada = pyqtSignal()
    finalizado = pyqtSignal()

    def __init__(self, acciones_macro1: List[Dict[str, Any]], acciones_macro2: List[Dict[str, Any]],
                 frecuencia_macro2: int, infinitas: bool, max_iteraciones: int,
                 retardo_bucle: float, velocidad: float):
        super().__init__()
        self.acciones_macro1 = acciones_macro1
        self.acciones_macro2 = acciones_macro2
        self.frecuencia_macro2 = max(1, frecuencia_macro2)
        self.infinitas = infinitas
        self.max_iteraciones = max_iteraciones
        self.retardo_bucle = retardo_bucle
        self.velocidad = max(0.01, velocidad)
        self.solicitante_parada = False
        self.esperando_intervencion = False
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()

    def detener(self):
        self.solicitante_parada = True
        self.esperando_intervencion = False

    def reanudar_intervencion(self):
        if self.esperando_intervencion:
            self.esperando_intervencion = False
            self.intervencion_reanudada.emit()

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

    def _ejecutar_secuencia(self, acciones: List[Dict[str, Any]], nombre_macro: str):
        total_acciones = len(acciones)
        for idx, acc in enumerate(acciones):
            if self.solicitante_parada:
                break

            self.accion_ejecutada.emit(idx + 1, total_acciones)

            # Respetar retardo de la acción adaptado a la velocidad
            delay = acc.get("delay", 0.0) / self.velocidad
            if delay > 0:
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
                if tipo == "pause_point":
                    self.esperando_intervencion = True
                    self.intervencion_requerida.emit(nombre_macro)
                    reproducir_sonido_alerta()
                    while self.esperando_intervencion and not self.solicitante_parada:
                        time.sleep(0.05)
                elif tipo == "mouse_move":
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
                print(f"Error al reproducir acción {idx} de {nombre_macro}: {e}")

    def run(self):
        if not self.acciones_macro1 and not self.acciones_macro2:
            self.finalizado.emit()
            return

        iteracion_m1 = 0
        iteracion_m2 = 0

        while not self.solicitante_parada:
            # 1. Ejecutar 1 iteración de Macro 1 (si tiene acciones)
            if self.acciones_macro1:
                iteracion_m1 += 1
                if not self.infinitas and iteracion_m1 > self.max_iteraciones:
                    break
                
                self.cambio_macro_ejecutando.emit("Macro 1 (F8)", iteracion_m1)
                self._ejecutar_secuencia(self.acciones_macro1, "Macro 1")

            if self.solicitante_parada:
                break

            # 2. Tras N iteraciones completadas de Macro 1, ejecutar 1 iteración de Macro 2
            if self.acciones_macro2 and iteracion_m1 > 0 and (iteracion_m1 % self.frecuencia_macro2 == 0):
                iteracion_m2 += 1
                self.cambio_macro_ejecutando.emit("Macro 2 (F1)", iteracion_m2)
                self._ejecutar_secuencia(self.acciones_macro2, "Macro 2")

            # Retardo entre bucles
            if not self.solicitante_parada and (self.infinitas or iteracion_m1 < self.max_iteraciones):
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
        self.setWindowTitle("Grabador Dual de Macros Pixel-Perfect | F8 (M1) & F1 (M2)")
        self.resize(1050, 720)
        self.setMinimumSize(900, 580)

        # Estado de las macros
        self.acciones_macro1: List[Dict[str, Any]] = []
        self.acciones_macro2: List[Dict[str, Any]] = []
        self.grabando_macro = 0  # 0: No, 1: Macro 1 (F8), 2: Macro 2 (F1)
        self.grabacion_pausada = False
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
                padding: 9px 15px;
                border-radius: 8px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            QPushButton:pressed {
                background-color: #1e293b;
            }
            QPushButton#btnRecord1 {
                background-color: #dc2626;
            }
            QPushButton#btnRecord1:hover {
                background-color: #ef4444;
            }
            QPushButton#btnRecord2 {
                background-color: #9333ea;
            }
            QPushButton#btnRecord2:hover {
                background-color: #a855f7;
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
            QTabWidget::pane {
                border: 1px solid #334155;
                border-radius: 8px;
                background-color: #0f172a;
            }
            QTabBar::tab {
                background-color: #1e293b;
                color: #94a3b8;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #38bdf8;
                color: #0f172a;
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
        
        lbl_titulo = QLabel("⚡ Grabador Dual de Macros (F8 & F1)")
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
        
        self.btn_grabar1 = QPushButton("🔴 Grabar Macro 1 (F8)")
        self.btn_grabar1.setObjectName("btnRecord1")
        self.btn_grabar1.clicked.connect(self.alternar_grabacion_macro1)

        self.btn_grabar2 = QPushButton("🟣 Grabar Macro 2 (F1)")
        self.btn_grabar2.setObjectName("btnRecord2")
        self.btn_grabar2.clicked.connect(self.alternar_grabacion_macro2)

        self.btn_reproducir = QPushButton("▶ Reproducir (F4)")
        self.btn_reproducir.setObjectName("btnPlay")
        self.btn_reproducir.clicked.connect(self.alternar_reproduccion)

        self.btn_detener = QPushButton("⏹ Detener (ESC)")
        self.btn_detener.setObjectName("btnStop")
        self.btn_detener.clicked.connect(self.detener_todo)

        self.btn_limpiar = QPushButton("🗑 Limpiar")
        self.btn_limpiar.clicked.connect(self.limpiar_macros)

        self.btn_guardar = QPushButton("💾 Guardar JSON")
        self.btn_guardar.clicked.connect(self.guardar_macro)

        self.btn_cargar = QPushButton("📂 Cargar JSON")
        self.btn_cargar.clicked.connect(self.cargar_macro)

        panel_botones.addWidget(self.btn_grabar1)
        panel_botones.addWidget(self.btn_grabar2)
        panel_botones.addWidget(self.btn_reproducir)
        panel_botones.addWidget(self.btn_detener)
        panel_botones.addWidget(self.btn_limpiar)
        panel_botones.addSpacing(10)
        panel_botones.addWidget(self.btn_guardar)
        panel_botones.addWidget(self.btn_cargar)
        main_layout.addLayout(panel_botones)

        # --- CONFIGURACIÓN Y TABLAS EN SPLITTER ---
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

        # Iteraciones fijas de Macro 1
        layout_iter = QHBoxLayout()
        lbl_iter = QLabel("Iteraciones de Macro 1:")
        self.spin_iter = QSpinBox()
        self.spin_iter.setRange(1, 1000000)
        self.spin_iter.setValue(1)
        self.spin_iter.setEnabled(False)
        layout_iter.addWidget(lbl_iter)
        layout_iter.addWidget(self.spin_iter)
        layout_config.addLayout(layout_iter)

        # Frecuencia de Macro 2
        layout_freq = QHBoxLayout()
        lbl_freq = QLabel("Ejecutar Macro 2 cada:")
        self.spin_freq_m2 = QSpinBox()
        self.spin_freq_m2.setRange(1, 100)
        self.spin_freq_m2.setValue(2)
        self.spin_freq_m2.setSuffix(" iter. de M1 (e.g. 1 1 2 1 1 2)")
        layout_freq.addWidget(lbl_freq)
        layout_freq.addWidget(self.spin_freq_m2)
        layout_config.addLayout(layout_freq)

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
        info_layout.addWidget(QLabel("• <b>F8</b>: Grabar / Detener Macro 1"))
        info_layout.addWidget(QLabel("• <b>F1</b>: Grabar / Detener Macro 2"))
        info_layout.addWidget(QLabel("• <b>Z</b>: Pausar / Reanudar (Grabación y Playback)"))
        info_layout.addWidget(QLabel("• <b>F4</b>: Iniciar / Parar Reproducción"))
        info_layout.addWidget(QLabel("• <b>ESC</b>: Parada de Emergencia"))
        layout_config.addWidget(info_box)

        layout_config.addStretch()
        splitter.addWidget(grupo_config)

        # Pestañas de Tablas (Derecha)
        self.tabs_macro = QTabWidget()
        
        # Tabla Macro 1
        self.tabla_m1 = QTableWidget()
        self.tabla_m1.setColumnCount(5)
        self.tabla_m1.setHorizontalHeaderLabels(["#", "Tipo de Acción", "Detalle / Tecla", "Coordenadas (X, Y)", "Retardo (s)"])
        self.tabla_m1.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabs_macro.addTab(self.tabla_m1, "📋 Macro 1 (F8) [0]")

        # Tabla Macro 2
        self.tabla_m2 = QTableWidget()
        self.tabla_m2.setColumnCount(5)
        self.tabla_m2.setHorizontalHeaderLabels(["#", "Tipo de Acción", "Detalle / Tecla", "Coordenadas (X, Y)", "Retardo (s)"])
        self.tabla_m2.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabs_macro.addTab(self.tabla_m2, "🟣 Macro 2 (F1) [0]")

        splitter.addWidget(self.tabs_macro)
        splitter.setSizes([340, 660])
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
                elif key == keyboard.Key.f1:
                    self.signal_tecla_global.emit("F1")
                elif key == keyboard.Key.f4:
                    self.signal_tecla_global.emit("F4")
                elif key == keyboard.Key.esc:
                    self.signal_tecla_global.emit("ESC")
                elif hasattr(key, 'char') and key.char and key.char.lower() == 'z':
                    self.signal_tecla_global.emit("Z")
            except Exception as e:
                print(f"Error en hotkey global: {e}")

        self.global_hotkey_listener = keyboard.Listener(on_press=on_press)
        self.global_hotkey_listener.daemon = True
        self.global_hotkey_listener.start()

    def procesar_hotkey_global(self, tecla: str):
        if tecla == "F8":
            self.alternar_grabacion_macro1()
        elif tecla == "F1":
            self.alternar_grabacion_macro2()
        elif tecla == "F4":
            self.alternar_reproduccion()
        elif tecla == "ESC":
            self.detener_todo()
        elif tecla == "Z":
            if self.grabando_macro != 0:
                self.alternar_pausa_grabacion()
            elif self.reproduciendo and self.hilo_playback and self.hilo_playback.esperando_intervencion:
                self.hilo_playback.reanudar_intervencion()

    # --- LÓGICA DE GRABACIÓN ---
    def alternar_grabacion_macro1(self):
        if self.reproduciendo or self.grabando_macro == 2:
            return
        if self.grabando_macro == 1:
            self.detener_grabacion()
        else:
            self.iniciar_grabacion(num_macro=1)

    def alternar_grabacion_macro2(self):
        if self.reproduciendo or self.grabando_macro == 1:
            return
        if self.grabando_macro == 2:
            self.detener_grabacion()
        else:
            self.iniciar_grabacion(num_macro=2)

    def alternar_pausa_grabacion(self):
        if self.grabando_macro == 0:
            return

        macro_nombre = f"MACRO {self.grabando_macro}"
        acciones = self.acciones_macro1 if self.grabando_macro == 1 else self.acciones_macro2

        if not self.grabacion_pausada:
            self.grabacion_pausada = True
            acciones.append({
                "tipo": "pause_point",
                "delay": self._calcular_delay()
            })
            self.actualizar_tablas()
            reproducir_sonido_alerta()
            self.lbl_estado.setText(f"🟠 GRABACIÓN PAUSADA EN {macro_nombre} (Pulsa 'Z' para reanudar)")
            self.lbl_estado.setStyleSheet("background-color: #7c2d12; color: #fdba74; border-color: #f97316;")
        else:
            self.grabacion_pausada = False
            self.ultimo_tiempo = time.perf_counter()
            reproducir_sonido_alerta()
            key_st = "F8" if self.grabando_macro == 1 else "F1"
            self.lbl_estado.setText(f"🔴 GRABANDO {macro_nombre}... (Pulsa {key_st} para parar, 'Z' para pausar)")
            self.lbl_estado.setStyleSheet("background-color: #7f1d1d; color: #fca5a5; border-color: #ef4444;")

    def iniciar_grabacion(self, num_macro: int):
        self.grabando_macro = num_macro
        self.grabacion_pausada = False
        self.ultimo_tiempo = time.perf_counter()

        if num_macro == 1:
            self.acciones_macro1.clear()
            self.tabs_macro.setCurrentIndex(0)
            self.lbl_estado.setText("🔴 GRABANDO MACRO 1... (Pulsa F8 para parar, 'Z' para pausar)")
            self.lbl_estado.setStyleSheet("background-color: #7f1d1d; color: #fca5a5; border-color: #ef4444;")
            self.btn_grabar1.setText("⏹ Detener M1 (F8)")
        else:
            self.acciones_macro2.clear()
            self.tabs_macro.setCurrentIndex(1)
            self.lbl_estado.setText("🟣 GRABANDO MACRO 2... (Pulsa F1 para parar, 'Z' para pausar)")
            self.lbl_estado.setStyleSheet("background-color: #581c87; color: #e9d5ff; border-color: #a855f7;")
            self.btn_grabar2.setText("⏹ Detener M2 (F1)")

        self.actualizar_tablas()

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
        if self.grabando_macro == 0:
            return

        macro_detenida = self.grabando_macro
        self.grabando_macro = 0
        self.grabacion_pausada = False

        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

        # Filtrar teclas de activación F8 / F1 al detener si se grabaron como última acción
        acciones = self.acciones_macro1 if macro_detenida == 1 else self.acciones_macro2
        if acciones and acciones[-1].get("key") in ["Key.f8", "F8", "Key.f1", "F1"]:
            acciones.pop()

        self.lbl_estado.setText(f"🟢 LISTO (Macro 1: {len(self.acciones_macro1)} acc | Macro 2: {len(self.acciones_macro2)} acc)")
        self.lbl_estado.setStyleSheet("background-color: #1e293b; color: #38bdf8; border-color: #334155;")
        self.btn_grabar1.setText("🔴 Grabar Macro 1 (F8)")
        self.btn_grabar2.setText("🟣 Grabar Macro 2 (F1)")
        self.actualizar_tablas()

    def _calcular_delay(self) -> float:
        ahora = time.perf_counter()
        delay = ahora - self.ultimo_tiempo
        self.ultimo_tiempo = ahora
        return round(delay, 4)

    def _es_tecla_z(self, key) -> bool:
        if hasattr(key, 'char') and key.char and key.char.lower() == 'z':
            return True
        if hasattr(key, 'vk') and key.vk == 90:
            return True
        return False

    def _on_mouse_move(self, x, y):
        if self.grabando_macro == 0 or self.grabacion_pausada or not self.chk_movimiento_continuo.isChecked():
            return
        acc = {
            "tipo": "mouse_move",
            "x": int(x),
            "y": int(y),
            "delay": self._calcular_delay()
        }
        if self.grabando_macro == 1:
            self.acciones_macro1.append(acc)
        else:
            self.acciones_macro2.append(acc)

    def _on_mouse_click(self, x, y, button, pressed):
        if self.grabando_macro == 0 or self.grabacion_pausada:
            return
        acc = {
            "tipo": "mouse_click",
            "x": int(x),
            "y": int(y),
            "button": button.name,
            "pressed": pressed,
            "delay": self._calcular_delay()
        }
        if self.grabando_macro == 1:
            self.acciones_macro1.append(acc)
        else:
            self.acciones_macro2.append(acc)

    def _on_mouse_scroll(self, x, y, dx, dy):
        if self.grabando_macro == 0 or self.grabacion_pausada:
            return
        acc = {
            "tipo": "mouse_scroll",
            "x": int(x),
            "y": int(y),
            "dx": dx,
            "dy": dy,
            "delay": self._calcular_delay()
        }
        if self.grabando_macro == 1:
            self.acciones_macro1.append(acc)
        else:
            self.acciones_macro2.append(acc)

    def _on_key_press(self, key):
        if self.grabando_macro == 0 or self.grabacion_pausada:
            return
        if self._es_tecla_z(key):
            return
        key_str = self._key_to_string(key)
        if key_str in ["Key.f8", "Key.f1", "Key.f4", "Key.esc"]:
            return
        acc = {
            "tipo": "key_press",
            "key": key_str,
            "delay": self._calcular_delay()
        }
        if self.grabando_macro == 1:
            self.acciones_macro1.append(acc)
        else:
            self.acciones_macro2.append(acc)

    def _on_key_release(self, key):
        if self.grabando_macro == 0 or self.grabacion_pausada:
            return
        if self._es_tecla_z(key):
            return
        key_str = self._key_to_string(key)
        if key_str in ["Key.f8", "Key.f1", "Key.f4", "Key.esc"]:
            return
        acc = {
            "tipo": "key_release",
            "key": key_str,
            "delay": self._calcular_delay()
        }
        if self.grabando_macro == 1:
            self.acciones_macro1.append(acc)
        else:
            self.acciones_macro2.append(acc)

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
        if self.grabando_macro != 0:
            return
        if self.reproduciendo:
            self.detener_reproduccion()
        else:
            self.iniciar_reproduccion()

    def iniciar_reproduccion(self):
        if not self.acciones_macro1 and not self.acciones_macro2:
            QMessageBox.warning(self, "Sin Acciones", "No hay acciones grabadas en Macro 1 ni en Macro 2.")
            return

        self.reproduciendo = True
        infinitas = self.chk_infinito.isChecked()
        max_iter = self.spin_iter.value()
        freq_m2 = self.spin_freq_m2.value()
        retardo_bucle = self.spin_delay_bucle.value()
        vel = self.slider_vel.value() / 10.0

        self.lbl_estado.setText("▶ INICIANDO REPRODUCCIÓN... (F4/ESC para detener)")
        self.lbl_estado.setStyleSheet("background-color: #14532d; color: #86efac; border-color: #22c55e;")
        self.btn_reproducir.setText("⏹ Detener Repr. (F4)")

        self.hilo_playback = HiloReproduccion(
            self.acciones_macro1, self.acciones_macro2, freq_m2,
            infinitas, max_iter, retardo_bucle, vel
        )
        self.hilo_playback.cambio_macro_ejecutando.connect(self._on_cambio_macro_ejecutando)
        self.hilo_playback.intervencion_requerida.connect(self._on_intervencion_requerida)
        self.hilo_playback.intervencion_reanudada.connect(self._on_intervencion_reanudada)
        self.hilo_playback.finalizado.connect(self.detener_reproduccion)
        self.hilo_playback.start()

    def _on_cambio_macro_ejecutando(self, nombre_macro: str, iteracion: int):
        if not (self.hilo_playback and self.hilo_playback.esperando_intervencion):
            color_bg = "#14532d" if "1" in nombre_macro else "#581c87"
            color_text = "#86efac" if "1" in nombre_macro else "#e9d5ff"
            color_border = "#22c55e" if "1" in nombre_macro else "#a855f7"
            
            self.lbl_estado.setText(f"▶ REPRODUCIENDO {nombre_macro} | Iteración #{iteracion} (F4/ESC para detener)")
            self.lbl_estado.setStyleSheet(f"background-color: {color_bg}; color: {color_text}; border-color: {color_border};")

    def _on_intervencion_requerida(self, nombre_macro: str):
        self.lbl_estado.setText(f"⏸ PAUSADO EN REPRODUCCIÓN ({nombre_macro}) - Pulsa 'Z' para continuar")
        self.lbl_estado.setStyleSheet("background-color: #7c2d12; color: #fdba74; border-color: #f97316;")

    def _on_intervencion_reanudada(self):
        self.lbl_estado.setText("▶ REPRODUCIENDO... (Pulsa F4 o ESC para detener)")
        self.lbl_estado.setStyleSheet("background-color: #14532d; color: #86efac; border-color: #22c55e;")

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
        if self.grabando_macro != 0:
            self.detener_grabacion()
        if self.reproduciendo:
            self.detener_reproduccion()

    def limpiar_macros(self):
        self.detener_todo()
        self.acciones_macro1.clear()
        self.acciones_macro2.clear()
        self.actualizar_tablas()
        self.lbl_estado.setText("🟢 LISTO (Macros Limpiadas)")

    # --- TABLAS Y PERSISTENCIA JSON ---
    def _poblar_tabla(self, tabla: QTableWidget, acciones: List[Dict[str, Any]]):
        tabla.setRowCount(0)
        for i, acc in enumerate(acciones):
            tabla.insertRow(i)
            tabla.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            
            tipo = acc.get("tipo", "")
            if tipo == "pause_point":
                tabla.setItem(i, 1, QTableWidgetItem("🔔 Pausa / Intervención ('Z')"))
                tabla.setItem(i, 2, QTableWidgetItem("Esperar a pulsar 'Z' para continuar"))
                tabla.setItem(i, 3, QTableWidgetItem("-"))
                tabla.setItem(i, 4, QTableWidgetItem(f"{acc.get('delay', 0.0):.4f}s"))
            else:
                icono = "🖱️" if "mouse" in tipo else "⌨️"
                tabla.setItem(i, 1, QTableWidgetItem(f"{icono} {tipo}"))
                
                detalle = ""
                if "mouse" in tipo:
                    detalle = f"Boton: {acc.get('button', '')} ({'Presionar' if acc.get('pressed') else 'Soltar'})" if tipo == "mouse_click" else ""
                else:
                    detalle = f"Tecla: {acc.get('key', '')} ({'Presionar' if tipo == 'key_press' else 'Soltar'})"
                tabla.setItem(i, 2, QTableWidgetItem(detalle))

                coords = f"X: {acc.get('x', '-')}, Y: {acc.get('y', '-')}" if "x" in acc else "-"
                tabla.setItem(i, 3, QTableWidgetItem(coords))
                tabla.setItem(i, 4, QTableWidgetItem(f"{acc.get('delay', 0.0):.4f}s"))

    def actualizar_tablas(self):
        self._poblar_tabla(self.tabla_m1, self.acciones_macro1)
        self._poblar_tabla(self.tabla_m2, self.acciones_macro2)
        self.tabs_macro.setTabText(0, f"📋 Macro 1 (F8) [{len(self.acciones_macro1)}]")
        self.tabs_macro.setTabText(1, f"🟣 Macro 2 (F1) [{len(self.acciones_macro2)}]")

    def guardar_macro(self):
        if not self.acciones_macro1 and not self.acciones_macro2:
            QMessageBox.warning(self, "Macros Vacías", "No hay acciones para guardar.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Guardar Macro JSON", "", "Archivos JSON (*.json)")
        if path:
            data = {
                "version": "2.0",
                "frecuencia_macro2": self.spin_freq_m2.value(),
                "total_acciones_macro1": len(self.acciones_macro1),
                "total_acciones_macro2": len(self.acciones_macro2),
                "acciones_macro1": self.acciones_macro1,
                "acciones_macro2": self.acciones_macro2
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, "Éxito", f"Macros guardadas con éxito en:\n{path}")

    def cargar_macro(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cargar Macro JSON", "", "Archivos JSON (*.json)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                if "acciones_macro1" in data:
                    self.acciones_macro1 = data.get("acciones_macro1", [])
                    self.acciones_macro2 = data.get("acciones_macro2", [])
                    self.spin_freq_m2.setValue(data.get("frecuencia_macro2", 2))
                else:
                    self.acciones_macro1 = data.get("acciones", [])
                    self.acciones_macro2 = []

                self.actualizar_tablas()
                QMessageBox.information(
                    self, "Éxito",
                    f"Se cargaron {len(self.acciones_macro1)} acciones en Macro 1 y {len(self.acciones_macro2)} acciones en Macro 2."
                )
                self.lbl_estado.setText(f"🟢 MACROS CARGADAS (M1: {len(self.acciones_macro1)} | M2: {len(self.acciones_macro2)})")
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

