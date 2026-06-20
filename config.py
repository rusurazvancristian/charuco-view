# Camere
CAM_W, CAM_H = 640, 480
CAM_LEFT     = 0
CAM_RIGHT    = 1
ROTATE_DEG   = 180          # ambele camere montate invers

BASELINE_M   = 0.068        # 68mm baseline fizic (inainte de calibrare)

# ChArUco board (charuco_a4.pdf — calib.io)
CHARUCO_SQUARES_X = 11
CHARUCO_SQUARES_Y = 8
CHARUCO_SQUARE_MM = 24.0    # mm
CHARUCO_MARKER_MM = 18.0    # mm

# GPS — NEO-M8N via CP210x USB-UART
GPS_PORT = "/dev/ttyUSB0"
GPS_BAUD = 9600

# IMU — ICM-20948 pe I2C
IMU_I2C_BUS  = 1
IMU_I2C_ADDR = 0x68

# ELM327 OBD Bluetooth (completat dupa pairing)
ELM_BT_ADDR = None
