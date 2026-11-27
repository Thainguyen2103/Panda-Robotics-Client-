"""Tay cam dien thoai: trang web do chinh laptop phat, dien thoai vao CUNG hotspot roi mo
http://192.168.137.1:8080 (dia chi in ra luc chay chay-demo.bat).

Khong deploy len internet: robot noi voi laptop qua hotspot, dien thoai cung vao hotspot do nen
lenh di thang dien thoai -> laptop -> robot trong mang noi bo: tre vai chuc ms, khong can mang
ngoai, nguoi la khong dieu khien duoc robot.

Duong dan:
  GET  /           trang tay cam (remote.html)
  GET  /cam.mjpg   video camera dau robot (MJPEG: chuoi anh JPEG lien tiep, the <img> tu hien)
  GET  /status     trang thai than (JSON)
  POST /drive      {"mode": "run|back|left|right|fl|fr|bl|br|stop"}  — fl = giu ▲ + ◀ cung luc
                   (tien + re trai, xe cua vong khong dung). Nut dang GIU thi trang gui lai moi
                   150ms; ngung gui 0,5 giay (tha nut, mat song) -> than tu phanh.
  POST /speed      {"step": 25 | -25}
  POST /trim       {"delta": 0.02 | -0.02}
  POST /talk       bat dau nghe (giong phim SPACE)
  POST /auto       {"on": true|false} — bat/tat TU DI DAO (tools/auto_drive.py). /drive cung tat no.
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from body_link import MODES  # run/back/left/right + fl/fr/bl/br (vua chay vua re)

PAGE = Path(__file__).with_name("remote.html")
PORT = 8080


def lan_urls(port=PORT):
    """Dia chi dien thoai can mo. Hotspot Windows luon la 192.168.137.1 -> dung no.
    Hotspot tat thi lay dia chi cua mang chinh (laptop co nhieu card ao: VPN, VMware... in ra
    het se roi mat)."""
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        ips = []
    hotspot = [ip for ip in ips if ip.startswith("192.168.137.")]
    if hotspot:
        return [f"http://{hotspot[0]}:{port}"]
    try:
        # "Noi" UDP toi 1 dia chi ngoai: khong gui goi nao, chi de Windows chon card mang
        # chinh -> doc ra IP cua card do.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return [f"http://{ip}:{port}"]
    except OSError:
        return []


def start(shared, voice, port=PORT):
    """Chay server o luong nen. Tra ve danh sach dia chi de in ra."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # khong in moi lan dien thoai goi (150ms/lan) ra cua so den

        def _json(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return {}

        def do_GET(self):
            if self.path == "/":
                data = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path.startswith("/cam.mjpg"):
                self._mjpeg()
            elif self.path == "/status":
                self._json(status())
            else:
                self.send_error(404)

        def do_POST(self):
            body, req = voice.body, self._body()
            if self.path == "/talk":
                voice.talk()
                return self._json({"ok": True})
            if not body:
                return self._json({"ok": False, "error": "chua co phan than"}, 503)
            auto = getattr(voice, "auto", None)
            if self.path == "/auto":  # nut "Tu di dao" (bat/tat)
                if not auto:
                    return self._json({"ok": False, "error": "chua co che do tu di"}, 503)
                why = ""
                if req.get("on"):
                    why = auto.start()
                else:
                    auto.stop("tay cam dien thoai")
                return self._json({"ok": not why, "error": why, **status()})
            if self.path == "/drive":
                mode = req.get("mode", "stop")
                if mode not in MODES + ("stop",):
                    return self._json({"ok": False}, 400)
                if auto:
                    auto.stop("lai bang dien thoai")  # nguoi cam lai -> thoi tu di
                ok = body.drive(mode, hold=True)
                return self._json({"ok": ok, **status()})
            if self.path == "/speed":
                body.faster(int(req.get("step", 0)))
                return self._json(status())
            if self.path == "/trim":
                body.nudge(float(req.get("delta", 0)))
                return self._json(status())
            self.send_error(404)

        def _mjpeg(self):
            # Anh thu nho (rong 320) + JPEG 60%: dien thoai chi can xem duong, khong can net nhu
            # cua so AI. Gui to se chiem song WiFi cua hotspot, lenh lai than bi tre.
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while not shared.stop:
                    with shared.lock:
                        frame, fid = shared.frame, shared.frame_id
                    if frame is None or fid == last:
                        time.sleep(0.03)
                        continue
                    last = fid
                    h, w = frame.shape[:2]
                    small = cv2.resize(frame, (320, int(h * 320 / w)))
                    ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 60])
                    if not ok:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg.tobytes() + b"\r\n")
                    time.sleep(0.1)  # toi da ~10 anh/giay
            except OSError:
                pass  # dien thoai dong trang / mat song

    def status():
        b = voice.body
        with shared.lock:
            fps = shared.cam_fps
        if not b:
            return {"online": False, "text": "Chua noi phan than", "cam_fps": fps}
        auto = getattr(voice, "auto", None)
        left = int(auto.remaining()) if auto else 0
        return {
            "auto_on": bool(auto and auto.running), "auto_state": auto.state if auto else "",
            "auto_left": f"{left // 60}:{left % 60:02d}",
            "online": b.online, "mode": b.mode, "blocked": b.blocked,
            "dist": b.dist, "speed": b.speed, "trim": b.trim_text(),
            "wheels": list(b.wheels), "cam_fps": round(fps, 1),
        }

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return lan_urls(port)
