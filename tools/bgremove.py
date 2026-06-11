# Background remover blueprint using rembg (U2-Net).
import os
import io
import uuid
import shutil
import threading
import time
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file

from PIL import Image

bp = Blueprint("bgremove", __name__)

WORK_DIR = Path("/tmp/creativify/bgremove")
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Lazy-loaded session so the app boots instantly; model loads on first use.
_session = None
_session_lock = threading.Lock()


def get_session():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                from rembg import new_session
                # u2net = best quality; u2netp = lighter/faster
                model = os.environ.get("REMBG_MODEL", "u2net")
                _session = new_session(model)
    return _session


def new_workdir():
    d = WORK_DIR / uuid.uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d


def schedule_cleanup(path, delay=600):
    def _rm():
        time.sleep(delay)
        shutil.rmtree(str(path), ignore_errors=True)
    threading.Thread(target=_rm, daemon=True).start()


@bp.route("/")
def bg_index():
    return render_template("bgremove.html")


@bp.route("/api/bg/remove", methods=["POST"])
def bg_remove():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Envie uma imagem"}), 400

    bg_mode = request.form.get("bg", "transparent")  # transparent | color | white
    bg_color = request.form.get("color", "#ffffff")

    try:
        from rembg import remove
        input_bytes = f.read()
        session = get_session()
        out_bytes = remove(input_bytes, session=session)
        result = Image.open(io.BytesIO(out_bytes)).convert("RGBA")
    except Exception as e:
        return jsonify({"error": "Falha ao remover o fundo: " + str(e)[:140]}), 500

    # Optional solid background behind the cutout
    if bg_mode in ("color", "white"):
        hexv = "#ffffff" if bg_mode == "white" else bg_color
        hexv = hexv.lstrip("#")
        try:
            rgb = tuple(int(hexv[i:i+2], 16) for i in (0, 2, 4))
        except Exception:
            rgb = (255, 255, 255)
        bg = Image.new("RGBA", result.size, rgb + (255,))
        bg.paste(result, mask=result.split()[-1])
        result = bg

    folder = new_workdir()
    out_path = folder / "sem_fundo.png"
    result.save(str(out_path), "PNG")
    schedule_cleanup(folder)

    return send_file(str(out_path), as_attachment=True,
                     download_name="sem_fundo.png", mimetype="image/png")
