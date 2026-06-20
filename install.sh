#!/bin/bash
# Instalare Charuco View pe Raspberry Pi 5
# Rulare: bash install.sh

set -e

echo "=== Charuco View — instalare ==="

echo "[1/3] Pachete sistem..."
sudo apt update -qq
sudo apt install -y python3-picamera2 python3-opencv python3-pip python3-numpy

echo "[2/3] Pachete Python..."
pip3 install --break-system-packages opencv-contrib-python pyserial obd

echo "[3/3] Dependente I2C (IMU)..."
pip3 install --break-system-packages adafruit-blinka adafruit-circuitpython-icm20x

echo ""
echo "=== Instalare completa ==="
echo ""
echo "Pasi urmatori:"
echo "  1. Calibrare stereo (o singura data, in parcare):"
echo "       python3 calibration/capture_calib.py"
echo "       python3 calibration/calibrate_stereo.py"
echo ""
echo "  2. Pornire stream stereo:"
echo "       python3 stereo_stream.py"
