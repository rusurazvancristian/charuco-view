"""
Captură perechi stereo pentru calibrare ChArUco.

Comenzi:
  SPACE  — salvează perechea curentă
  Q      — ieși

Imaginile sunt salvate în calibration/images/left_NNN.jpg + right_NNN.jpg
Rulează de 25-30 ori cu tabla în poziții diferite (unghi, distanță, colț).
"""

import os
import sys
import time
import glob

import cv2
import numpy as np
from picamera2 import Picamera2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import CAM_W, CAM_H, CAM_LEFT, CAM_RIGHT, ROTATE_DEG

SAVE_DIR = os.path.join(os.path.dirname(__file__), "images")
os.makedirs(SAVE_DIR, exist_ok=True)


def rotate(img):
    if ROTATE_DEG == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


def count_existing():
    return len(glob.glob(os.path.join(SAVE_DIR, "left_*.jpg")))


def flash_green(window_name, img):
    green = img.copy()
    green[:, :, 1] = np.clip(green[:, :, 1].astype(np.int32) + 80, 0, 255)
    cv2.imshow(window_name, green)
    cv2.waitKey(200)


def main():
    print("Deschid camerele...")
    cam_l = Picamera2(CAM_LEFT)
    cam_r = Picamera2(CAM_RIGHT)

    cfg = dict(
        main={"size": (CAM_W, CAM_H), "format": "BGR888"},
        controls={"FrameRate": 30},
    )
    cam_l.configure(cam_l.create_preview_configuration(**cfg))
    cam_r.configure(cam_r.create_preview_configuration(**cfg))
    cam_l.start()
    cam_r.start()
    time.sleep(2.0)

    n = count_existing()
    WIN = "Calibrare Stereo  |  SPACE=salveaza  Q=iesire"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, CAM_W * 2, CAM_H)

    print(f"Perechi deja salvate: {n}")
    print("SPACE = salvează pereche  |  Q = ieși")

    while True:
        left  = rotate(cam_l.capture_array())
        right = rotate(cam_r.capture_array())

        canvas = np.concatenate([left, right], axis=1)

        # linie de separare
        canvas[:, CAM_W - 1 : CAM_W + 1] = (80, 80, 80)

        cv2.putText(canvas, f"STANGA", (10, CAM_H - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 210, 255), 2)
        cv2.putText(canvas, f"DREAPTA", (CAM_W + 10, CAM_H - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 210, 255), 2)
        cv2.putText(canvas, f"Perechi salvate: {n}",
                    (CAM_W - 160, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 80), 2)

        cv2.imshow(WIN, canvas)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q") or key == 27:
            break

        if key == ord(" "):
            lp = os.path.join(SAVE_DIR, f"left_{n:03d}.jpg")
            rp = os.path.join(SAVE_DIR, f"right_{n:03d}.jpg")
            cv2.imwrite(lp, left, [cv2.IMWRITE_JPEG_QUALITY, 95])
            cv2.imwrite(rp, right, [cv2.IMWRITE_JPEG_QUALITY, 95])
            n += 1
            print(f"  [{n:02d}] Salvat")
            flash_green(WIN, canvas)

    cam_l.stop()
    cam_r.stop()
    cv2.destroyAllWindows()
    print(f"\nTotal perechi: {n}")
    if n >= 15:
        print("Suficient! Rulează acum: python3 calibration/calibrate_stereo.py")
    else:
        print(f"Recomandat minim 20 perechi (ai {n}). Rulează din nou pentru mai multe.")


if __name__ == "__main__":
    main()
