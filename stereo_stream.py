"""
Charuco View — Stereo stream live (Faza 1).

Pornire:
  python3 stereo_stream.py

Feed-uri MJPEG pe portul 8092:
  http://<ip>:8092/        — LEFT | RIGHT | DISPARITY
  http://<ip>:8092/depth   — depth map + butoane focus

Daca exista stereo_calib.npz (dupa calibrare), imaginile sunt rectificate
automat inainte de SGBM → depth metric real.
Fara calibrare: ruleaza cu parametri estimati (F_PX=408, baseline=68mm).
"""

import os
import sys
import select
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
from picamera2 import Picamera2

from config import (
    CAM_W, CAM_H, CAM_LEFT, CAM_RIGHT, ROTATE_DEG,
    BASELINE_M,
)

STREAM_PORT = 8092
CALIB_FILE  = os.path.join(os.path.dirname(__file__), "stereo_calib.npz")

NDISP     = 96
BLOCK     = 9
P1        = 8  * 3 * BLOCK * BLOCK
P2        = 32 * 3 * BLOCK * BLOCK
UNIQ      = 7
SPECKLE_W = 150
SPECKLE_R = 2

LP_MIN, LP_MAX, LP_STEP = 0.0, 15.0, 0.25

# ── stare partajata ──────────────────────────────────────────────────────────
_stream_lock  = threading.Lock()
_depth_lock   = threading.Lock()
_stream_holder = [b""]
_depth_holder  = [b""]
_focus_lock    = threading.Lock()
_focus = {"L": 1.0, "R": 1.0, "dirty": False, "refocus": False}

PANEL_W = CAM_W // 2
PANEL_H = CAM_H // 2


def _push(bgr, lock, holder):
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if ok:
        with lock:
            holder[0] = buf.tobytes()


# ── calibrare ────────────────────────────────────────────────────────────────
def load_calib():
    if not os.path.exists(CALIB_FILE):
        print("stereo_calib.npz negasit — ruleaza fara rectificare.")
        print("  Ruleaza calibration/capture_calib.py + calibration/calibrate_stereo.py")
        return None
    d = np.load(CALIB_FILE)
    print(f"Calibrare incarcata: fx={d['P1'][0,0]:.1f}  baseline={abs(d['P2'][0,3]/d['P2'][0,0])*1000:.1f}mm")
    return d


# ── HTTP ─────────────────────────────────────────────────────────────────────
_DEPTH_HTML = b"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Depth</title>
<style>
 body{margin:0;background:#0a0a0a;color:#ddd;font-family:system-ui,sans-serif;
      display:flex;flex-direction:column;align-items:center}
 img{width:100%;max-width:960px}
 .bar{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;padding:10px}
 button{font-size:18px;padding:10px 16px;border:0;border-radius:8px;
        background:#2a2a2a;color:#eee;cursor:pointer}
 button:active{background:#444}
 .L{border-bottom:3px solid #4fc3f7}.R{border-bottom:3px solid #ff8a65}
 .af{background:#1b5e20}#msg{font-size:14px;color:#9e9e9e;min-height:18px}
</style></head><body>
<img src="/depth_stream">
<div class=bar>
 <button class=L onclick="c('Lm')">L &minus;</button>
 <button class=L onclick="c('Lp')">L &plus;</button>
 <button class=af onclick="c('af')">AUTO-FOCUS</button>
 <button class=R onclick="c('Rm')">R &minus;</button>
 <button class=R onclick="c('Rp')">R &plus;</button>
</div><div id=msg>...</div>
<script>
 function c(a){fetch('/ctl?act='+a).then(r=>r.text()).then(t=>{msg.innerText=t})}
 setInterval(()=>fetch('/ctl?act=q').then(r=>r.text()).then(t=>{msg.innerText=t}),1500);
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _mjpeg(self, holder, lock):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with lock:
                    data = holder[0]
                if data:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n")
                time.sleep(0.04)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _html(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/stream":
            self._mjpeg(_stream_holder, _stream_lock)
        elif path == "/depth_stream":
            self._mjpeg(_depth_holder, _depth_lock)
        elif path == "/":
            self._html(b"<html><body style='margin:0;background:#111'>"
                       b"<a href='/depth' style='color:#4fc3f7;font-family:sans-serif'>Depth map</a><br>"
                       b"<img src='/stream' style='width:100%'></body></html>")
        elif path == "/depth":
            self._html(_DEPTH_HTML)
        elif path == "/ctl":
            q = parse_qs(urlparse(self.path).query)
            act = q.get("act", [""])[0]
            with _focus_lock:
                if   act == "Lp": _focus["L"] = min(LP_MAX, _focus["L"] + LP_STEP); _focus["dirty"] = True
                elif act == "Lm": _focus["L"] = max(LP_MIN, _focus["L"] - LP_STEP); _focus["dirty"] = True
                elif act == "Rp": _focus["R"] = min(LP_MAX, _focus["R"] + LP_STEP); _focus["dirty"] = True
                elif act == "Rm": _focus["R"] = max(LP_MIN, _focus["R"] - LP_STEP); _focus["dirty"] = True
                elif act == "af": _focus["refocus"] = True
                msg = f"L={_focus['L']:.2f}  R={_focus['R']:.2f}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(msg.encode())
        else:
            self.send_error(404)


# ── camere ───────────────────────────────────────────────────────────────────
def open_cameras():
    cam_l = Picamera2(CAM_LEFT)
    cam_r = Picamera2(CAM_RIGHT)
    cfg = dict(main={"size": (CAM_W, CAM_H), "format": "BGR888"},
               controls={"FrameRate": 30})
    cam_l.configure(cam_l.create_preview_configuration(**cfg))
    cam_r.configure(cam_r.create_preview_configuration(**cfg))
    cam_l.start()
    cam_r.start()
    time.sleep(2.0)
    return cam_l, cam_r


def autofocus_each(cam_l, cam_r):
    for c in (cam_l, cam_r):
        try:
            c.set_controls({"AfMode": 1, "AfTrigger": 0})
        except Exception as e:
            print(f"  AF esuat: {e}")
    time.sleep(3.0)
    def lp(c, default=1.0):
        try:
            return float(c.capture_metadata().get("LensPosition", default))
        except Exception:
            return default
    lpL, lpR = lp(cam_l), lp(cam_r)
    cam_l.set_controls({"AfMode": 0, "LensPosition": lpL})
    cam_r.set_controls({"AfMode": 0, "LensPosition": lpR})
    print(f"Focus blocat: L={lpL:.2f}  R={lpR:.2f}")
    return lpL, lpR


def apply_focus(cam_l, cam_r):
    with _focus_lock:
        if _focus["refocus"]:
            _focus["refocus"] = False
            return "refocus"
        if _focus["dirty"]:
            _focus["dirty"] = False
            lpL, lpR = _focus["L"], _focus["R"]
        else:
            return None
    cam_l.set_controls({"AfMode": 0, "LensPosition": float(lpL)})
    cam_r.set_controls({"AfMode": 0, "LensPosition": float(lpR)})


# ── procesare ────────────────────────────────────────────────────────────────
def rotate(img):
    if ROTATE_DEG == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))


def preprocess(bgr):
    return clahe.apply(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))


def make_sgbm():
    return cv2.StereoSGBM_create(
        minDisparity=0, numDisparities=NDISP, blockSize=BLOCK,
        P1=P1, P2=P2, uniquenessRatio=UNIQ,
        speckleWindowSize=SPECKLE_W, speckleRange=SPECKLE_R,
        disp12MaxDiff=2, mode=cv2.StereoSGBM_MODE_SGBM_3WAY,
    )


def colorize_disp(disp16):
    disp_f = disp16.astype(np.float32) / 16.0
    valid  = disp_f > 0
    out    = np.zeros((*disp_f.shape, 3), dtype=np.uint8)
    if not valid.any():
        return out
    lo, hi = np.percentile(disp_f[valid], 2), np.percentile(disp_f[valid], 98)
    if hi <= lo:
        return out
    norm = np.clip((disp_f - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(norm, cv2.COLORMAP_MAGMA)
    colored[~valid] = 0
    return cv2.medianBlur(colored, 5)


def center_depth(disp16, f_px, baseline):
    cy, cx = disp16.shape[0] // 2, disp16.shape[1] // 2
    roi = disp16[cy-10:cy+10, cx-10:cx+10].astype(np.float32) / 16.0
    valid = roi[roi > 0]
    if valid.size == 0:
        return None
    d = float(np.median(valid))
    return f_px * baseline / d if d > 0 else None


def build_vis(left, right, disp16, fps, d_center, lpL, lpR, calibrated):
    d_str = f"{d_center:.2f}m" if d_center else "---"
    mode  = "CALIBRAT" if calibrated else "NECALIBRAT"
    pl = cv2.resize(left,  (PANEL_W, PANEL_H))
    pr = cv2.resize(right, (PANEL_W, PANEL_H))
    cv2.putText(pl, f"STANGA  f={lpL:.2f}", (6, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(pr, f"DREAPTA f={lpR:.2f}", (6, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    top = np.concatenate([pl, pr], axis=1)
    disp_col = cv2.resize(colorize_disp(disp16), (PANEL_W * 2, PANEL_H))
    cx, cy = PANEL_W, PANEL_H // 2
    cv2.drawMarker(disp_col, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
    cv2.putText(disp_col, f"DISPARITY [{mode}]  centru:{d_str}  {fps:.1f}fps",
                (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    div = np.full((2, PANEL_W * 2, 3), 60, dtype=np.uint8)
    return np.concatenate([top, div, disp_col], axis=0)


def build_depth(disp16, d_center, fps, lpL, lpR):
    depth = cv2.resize(colorize_disp(disp16), (CAM_W, CAM_H),
                       interpolation=cv2.INTER_NEAREST)
    cx, cy = CAM_W // 2, CAM_H // 2
    cv2.drawMarker(depth, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 26, 2)
    d_str = f"{d_center:.2f} m" if d_center else "---"
    cv2.rectangle(depth, (0, 0), (CAM_W, 30), (0, 0, 0), -1)
    cv2.putText(depth, f"DEPTH  centru:{d_str}  {fps:.1f}fps  L={lpL:.2f} R={lpR:.2f}",
                (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 120), 1)
    return depth


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    calib = load_calib()
    if calib is not None:
        map1x, map1y = calib["map1x"], calib["map1y"]
        map2x, map2y = calib["map2x"], calib["map2y"]
        P1_mat, P2_mat = calib["P1"], calib["P2"]
        f_px     = float(P1_mat[0, 0])
        baseline = abs(float(P2_mat[0, 3]) / float(P2_mat[0, 0]))
        calibrated = True
    else:
        f_px, baseline, calibrated = 408.0, BASELINE_M, False

    cam_l, cam_r = open_cameras()
    lpL, lpR = autofocus_each(cam_l, cam_r)
    with _focus_lock:
        _focus["L"], _focus["R"] = lpL, lpR

    sgbm = make_sgbm()

    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0", STREAM_PORT), _Handler).serve_forever(),
        daemon=True,
    ).start()
    print(f"Stream: http://localhost:{STREAM_PORT}/")
    print(f"Depth:  http://localhost:{STREAM_PORT}/depth")
    print("Q = opreste")

    fps, t_prev, frame_n = 0.0, time.time(), 0

    while True:
        r = apply_focus(cam_l, cam_r)
        if r == "refocus":
            lpL, lpR = autofocus_each(cam_l, cam_r)
            with _focus_lock:
                _focus["L"], _focus["R"] = lpL, lpR
        else:
            with _focus_lock:
                lpL, lpR = _focus["L"], _focus["R"]

        left  = rotate(cam_l.capture_array())
        right = rotate(cam_r.capture_array())

        if calibrated:
            left  = cv2.remap(left,  map1x, map1y, cv2.INTER_LINEAR)
            right = cv2.remap(right, map2x, map2y, cv2.INTER_LINEAR)

        disp16 = sgbm.compute(preprocess(left), preprocess(right))

        t_now  = time.time()
        fps    = 0.9 * fps + 0.1 / max(t_now - t_prev, 1e-6)
        t_prev = t_now
        frame_n += 1

        d_center = center_depth(disp16, f_px, baseline)
        if frame_n % 15 == 0:
            d_str = f"{d_center:.2f}m" if d_center else "---"
            print(f"\rFPS:{fps:.1f}  centru:{d_str}  L={lpL:.2f} R={lpR:.2f}  ", end="", flush=True)

        _push(build_vis(left, right, disp16, fps, d_center, lpL, lpR, calibrated),
              _stream_lock, _stream_holder)
        _push(build_depth(disp16, d_center, fps, lpL, lpR),
              _depth_lock, _depth_holder)

        if select.select([sys.stdin], [], [], 0)[0]:
            if sys.stdin.read(1).lower() == "q":
                break

    cam_l.stop()
    cam_r.stop()


if __name__ == "__main__":
    main()
