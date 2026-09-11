#!/bin/bash
# Equivalente a lanzar.bat para Linux/Linux Mint

echo "Iniciando Grabador de Acciones..."

# Ir al directorio donde está este script
cd "$(dirname "$0")"

# Ejecutar el programa Python
python3 grabador_macros.py
