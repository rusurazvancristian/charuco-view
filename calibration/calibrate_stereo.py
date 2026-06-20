"""
Calculează calibrarea stereo din perechile salvate de capture_calib.py.
Salvează stereo_calib.npz în rădăcina proiectului.

Tablă ChArUco: charuco_a4.pdf (calib.io)
  11x8 pătrate, 24mm/pătrat, markeri 18mm, DICT_4X4_50
"""

import os
import sys
import glob

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import (
    CAM_W, CAM_H,
    CHARUCO_SQUARES_X, CHARUCO_SQUARES_Y,
    CHARUCO_SQUARE_MM, CHARUCO_MARKER_MM,
)

IMG_DIR  = os.path.join(os.path.dirname(__file__), "images")
OUT_FILE = os.path.join(os.path.dirname(__file__), "..", "stereo_calib.npz")
IMG_SIZE = (CAM_W, CAM_H)


def build_detector():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    board = cv2.aruco.CharucoBoard(
        (CHARUCO_SQUARES_X, CHARUCO_SQUARES_Y),
        CHARUCO_SQUARE_MM / 1000.0,
        CHARUCO_MARKER_MM / 1000.0,
        dictionary,
    )
    detector = cv2.aruco.CharucoDetector(board)
    return detector, board


def detect_charuco(img_bgr, detector):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    corners, ids, _, _ = detector.detectBoard(gray)
    if ids is None or len(ids) < 4:
        return None, None
    return corners, ids.flatten()


def main():
    left_files  = sorted(glob.glob(os.path.join(IMG_DIR, "left_*.jpg")))
    right_files = sorted(glob.glob(os.path.join(IMG_DIR, "right_*.jpg")))

    if not left_files:
        print("Nu există imagini în calibration/images/")
        print("Rulează mai întâi: python3 calibration/capture_calib.py")
        return

    print(f"Găsite {len(left_files)} perechi. Construiesc detectorul ChArUco...")
    detector, board = build_detector()

    # 3D positions ale colțurilor interioare din tablă
    board_pts_3d = board.chessboardCorners  # (N, 3)

    obj_pts   = []
    img_pts_L = []
    img_pts_R = []
    ok = 0

    for lf, rf in zip(left_files, right_files):
        imgL = cv2.imread(lf)
        imgR = cv2.imread(rf)

        cornersL, idsL = detect_charuco(imgL, detector)
        cornersR, idsR = detect_charuco(imgR, detector)

        if cornersL is None or cornersR is None:
            print(f"  ✗ {os.path.basename(lf)} — ChArUco negăsit")
            continue

        # colțuri comune în ambele imagini
        common = np.intersect1d(idsL, idsR)
        if len(common) < 4:
            print(f"  ✗ {os.path.basename(lf)} — prea puține colțuri comune ({len(common)})")
            continue

        # indexuri în arrays-urile detectate
        idxL = [np.where(idsL == i)[0][0] for i in common]
        idxR = [np.where(idsR == i)[0][0] for i in common]

        obj_p = board_pts_3d[common].reshape(-1, 1, 3).astype(np.float32)
        ptL   = cornersL[idxL].reshape(-1, 1, 2).astype(np.float32)
        ptR   = cornersR[idxR].reshape(-1, 1, 2).astype(np.float32)

        obj_pts.append(obj_p)
        img_pts_L.append(ptL)
        img_pts_R.append(ptR)
        ok += 1
        print(f"  ✓ {os.path.basename(lf)} — {len(common)} colțuri comune")

    if ok < 5:
        print(f"\nPrea puține imagini valide ({ok}). Mai fă capturi.")
        return

    print(f"\nCalibrez cu {ok} perechi valide...")

    # calibrare individuală (pentru estimare initială)
    flags_mono = cv2.CALIB_RATIONAL_MODEL
    rms_L, K1, D1, _, _ = cv2.calibrateCamera(
        obj_pts, img_pts_L, IMG_SIZE, None, None, flags=flags_mono
    )
    rms_R, K2, D2, _, _ = cv2.calibrateCamera(
        obj_pts, img_pts_R, IMG_SIZE, None, None, flags=flags_mono
    )
    print(f"  Stânga  RMS: {rms_L:.4f} px")
    print(f"  Dreapta RMS: {rms_R:.4f} px")

    # calibrare stereo (fix intrinseci deja calibrați)
    rms_s, K1, D1, K2, D2, R, T, E, F = cv2.stereoCalibrate(
        obj_pts, img_pts_L, img_pts_R,
        K1, D1, K2, D2, IMG_SIZE,
        flags=cv2.CALIB_FIX_INTRINSIC | cv2.CALIB_RATIONAL_MODEL,
        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, 1e-7),
    )
    baseline_mm = np.linalg.norm(T) * 1000
    print(f"  Stereo  RMS: {rms_s:.4f} px")
    print(f"  Baseline calibrat: {baseline_mm:.1f} mm  (fizic: 68 mm)")

    if rms_s > 1.5:
        print("  ATENTIE: RMS stereo mare. Refă capturile mai atent.")

    # rectificare
    R1, R2, P1, P2, Q, roi1, roi2 = cv2.stereoRectify(
        K1, D1, K2, D2, IMG_SIZE, R, T,
        flags=cv2.CALIB_ZERO_DISPARITY, alpha=0,
    )
    map1x, map1y = cv2.initUndistortRectifyMap(K1, D1, R1, P1, IMG_SIZE, cv2.CV_32FC1)
    map2x, map2y = cv2.initUndistortRectifyMap(K2, D2, R2, P2, IMG_SIZE, cv2.CV_32FC1)

    np.savez(
        OUT_FILE,
        K1=K1, D1=D1, K2=K2, D2=D2,
        R=R, T=T, E=E, F=F,
        R1=R1, R2=R2, P1=P1, P2=P2, Q=Q,
        map1x=map1x, map1y=map1y,
        map2x=map2x, map2y=map2y,
        image_size=np.array(IMG_SIZE),
    )

    print(f"\n✓ Calibrare salvată: {os.path.abspath(OUT_FILE)}")
    print(f"  fx={P1[0,0]:.1f} px   baseline={abs(P2[0,3]/P2[0,0])*1000:.1f} mm")
    print("Acum pornește: python3 main.py")


if __name__ == "__main__":
    main()
