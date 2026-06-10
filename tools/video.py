# Video tools blueprint: compress, cut, convert, extract audio.
import os
import uuid
import shutil
import threading
import time
import subprocess
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file, after_this_request

bp = Blueprint("video", __name__)

WORK_DIR = Path("/tmp/creativify/video")
WORK_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_FORMATS = {
    "mp4": "mp4", "mov": "mov", "webm": "webm",
    "mkv": "matroska", "avi": "avi", "gif": "gif",
}
AUDIO_FORMATS = {
    "mp3": ("libmp3lame", "audio/mpeg"),
    "wav": ("pcm_s16le", "audio/wav"),
    "aac": ("aac", "audio/aac"),
    "m4a": ("aac", "audio/mp4"),
}


def new_workdir():
    d = WORK_DIR / uuid.uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d


def schedule_cleanup(path, delay=600):
    def _rm():
        time.sleep(delay)
        shutil.rmtree(str(path), ignore_errors=True)
    threading.Thread(target=_rm, daemon=True).start()


def run_ffmpeg(cmd, timeout=600):
    """Run ffmpeg, return (ok, stderr_tail)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode != 0:
            tail = (proc.stderr or "")[-400:]
            return False, tail
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Tempo esgotado (vídeo muito grande)"
    except Exception as e:
        return False, str(e)


def save_upload(file_storage, folder):
    safe = Path(file_storage.filename).name or "video.mp4"
    in_path = folder / ("in_" + safe)
    file_storage.save(str(in_path))
    return in_path


def deliver(out_path, mime, folder):
    schedule_cleanup(folder)
    if not out_path.exists() or out_path.stat().st_size == 0:
        return jsonify({"error": "Falha ao processar o vídeo"}), 400
    return send_file(str(out_path), as_attachment=True,
                     download_name=out_path.name, mimetype=mime)


@bp.route("/")
def video_index():
    return render_template("video.html")


# ---- Compressor -------------------------------------------------------------
@bp.route("/api/video/compress", methods=["POST"])
def video_compress():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Envie um vídeo"}), 400
    level = request.form.get("level", "medium")  # light | medium | strong
    crf = {"light": "23", "medium": "28", "strong": "32"}.get(level, "28")

    folder = new_workdir()
    src = save_upload(f, folder)
    stem = Path(f.filename).stem or "video"
    out = folder / f"{stem}_comprimido.mp4"
    ok, err = run_ffmpeg([
        "ffmpeg", "-y", "-i", str(src),
        "-vcodec", "libx264", "-crf", crf, "-preset", "veryfast",
        "-acodec", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ])
    if not ok:
        schedule_cleanup(folder)
        return jsonify({"error": "Não foi possível comprimir: " + err[-150:]}), 400
    return deliver(out, "video/mp4", folder)


# ---- Cortador por tempo -----------------------------------------------------
@bp.route("/api/video/cut", methods=["POST"])
def video_cut():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Envie um vídeo"}), 400
    start = request.form.get("start", "").strip()
    end = request.form.get("end", "").strip()
    if not start and not end:
        return jsonify({"error": "Informe início e/ou fim do corte"}), 400

    folder = new_workdir()
    src = save_upload(f, folder)
    stem = Path(f.filename).stem or "video"
    out = folder / f"{stem}_cortado.mp4"

    cmd = ["ffmpeg", "-y"]
    if start:
        cmd += ["-ss", start]
    cmd += ["-i", str(src)]
    if end:
        cmd += ["-to", end]
    # re-encode to keep cuts accurate
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", str(out)]

    ok, err = run_ffmpeg(cmd)
    if not ok:
        schedule_cleanup(folder)
        return jsonify({"error": "Não foi possível cortar: " + err[-150:]}), 400
    return deliver(out, "video/mp4", folder)


# ---- Conversor de formato ---------------------------------------------------
@bp.route("/api/video/convert", methods=["POST"])
def video_convert():
    f = request.files.get("file")
    target = (request.form.get("format") or "mp4").lower()
    if target not in VIDEO_FORMATS:
        return jsonify({"error": "Formato inválido"}), 400
    if not f:
        return jsonify({"error": "Envie um vídeo"}), 400

    folder = new_workdir()
    src = save_upload(f, folder)
    stem = Path(f.filename).stem or "video"
    out = folder / f"{stem}.{target}"

    if target == "gif":
        # nice quality gif via palette
        palette = folder / "palette.png"
        run_ffmpeg(["ffmpeg", "-y", "-i", str(src),
                    "-vf", "fps=12,scale=480:-1:flags=lanczos,palettegen",
                    str(palette)])
        ok, err = run_ffmpeg(["ffmpeg", "-y", "-i", str(src), "-i", str(palette),
                              "-lavfi", "fps=12,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse",
                              str(out)])
        mime = "image/gif"
    else:
        ok, err = run_ffmpeg(["ffmpeg", "-y", "-i", str(src),
                              "-c:v", "libx264" if target in ("mp4", "mov", "mkv", "avi") else "libvpx-vp9",
                              "-preset", "veryfast", "-crf", "26",
                              "-c:a", "aac" if target != "webm" else "libopus",
                              str(out)])
        mime = f"video/{target if target != 'mkv' else 'x-matroska'}"

    if not ok:
        schedule_cleanup(folder)
        return jsonify({"error": "Não foi possível converter: " + err[-150:]}), 400
    return deliver(out, mime, folder)


# ---- Extrator de áudio ------------------------------------------------------
@bp.route("/api/video/audio", methods=["POST"])
def video_audio():
    f = request.files.get("file")
    target = (request.form.get("format") or "mp3").lower()
    if target not in AUDIO_FORMATS:
        return jsonify({"error": "Formato de áudio inválido"}), 400
    if not f:
        return jsonify({"error": "Envie um vídeo"}), 400

    codec, mime = AUDIO_FORMATS[target]
    folder = new_workdir()
    src = save_upload(f, folder)
    stem = Path(f.filename).stem or "audio"
    out = folder / f"{stem}.{target}"

    cmd = ["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", codec]
    if target == "mp3":
        cmd += ["-q:a", "0"]
    elif target in ("aac", "m4a"):
        cmd += ["-b:a", "192k"]
    cmd += [str(out)]

    ok, err = run_ffmpeg(cmd)
    if not ok:
        schedule_cleanup(folder)
        return jsonify({"error": "Não foi possível extrair o áudio: " + err[-150:]}), 400
    return deliver(out, mime, folder)
