# Image tools blueprint: compress, exif, convert, resize.
import os
import io
import uuid
import zipfile
import shutil
import threading
import time
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file, after_this_request

from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

bp = Blueprint("imaging", __name__)


@bp.route("/")
def imaging_index():
    return render_template("imaging.html")


WORK_DIR = Path("/tmp/creativify")
WORK_DIR.mkdir(exist_ok=True)

# Formats we can read/write through Pillow
OUTPUT_FORMATS = {
    "jpg": ("JPEG", "image/jpeg"),
    "jpeg": ("JPEG", "image/jpeg"),
    "png": ("PNG", "image/png"),
    "webp": ("WEBP", "image/webp"),
    "avif": ("AVIF", "image/avif"),
    "bmp": ("BMP", "image/bmp"),
    "tiff": ("TIFF", "image/tiff"),
    "gif": ("GIF", "image/gif"),
}

SOCIAL_SIZES = {
    "tiktok_reels": (1080, 1920, "9:16 TikTok/Reels"),
    "youtube": (1920, 1080, "16:9 YouTube"),
    "square": (1080, 1080, "1:1 Feed"),
    "portrait": (1080, 1350, "4:5 Feed vertical"),
}


# ---------- helpers ----------------------------------------------------------
def new_workdir():
    d = WORK_DIR / uuid.uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d


def schedule_cleanup(path, delay=600):
    def _rm():
        time.sleep(delay)
        shutil.rmtree(str(path), ignore_errors=True)
    threading.Thread(target=_rm, daemon=True).start()


def load_image(file_storage):
    img = Image.open(file_storage.stream)
    # normalise orientation from EXIF, then we can drop it
    img = ImageOps.exif_transpose(img)
    return img


def save_image(img, out_path, fmt_key, quality=82):
    pil_fmt, _ = OUTPUT_FORMATS[fmt_key]
    params = {}
    if pil_fmt in ("JPEG", "WEBP", "AVIF"):
        if img.mode in ("RGBA", "P", "LA"):
            if pil_fmt == "JPEG":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                img = bg
            else:
                img = img.convert("RGBA")
        params["quality"] = quality
        if pil_fmt == "WEBP":
            params["method"] = 6
    elif pil_fmt == "PNG":
        params["optimize"] = True
    img.save(out_path, pil_fmt, **params)


def zip_dir(folder, names=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in folder.glob("*"):
            if f.is_file() and f.suffix != ".json":
                zf.write(str(f), f.name)
    buf.seek(0)
    return buf


def respond_files(folder, single_mime=None):
    """Return either a single file or a zip, plus cleanup."""
    files = [f for f in folder.glob("*") if f.is_file()]
    schedule_cleanup(folder)
    if not files:
        return jsonify({"error": "Nenhum arquivo gerado"}), 400

    @after_this_request
    def _cleanup(resp):
        return resp

    if len(files) == 1:
        f = files[0]
        mime = single_mime or "application/octet-stream"
        return send_file(str(f), as_attachment=True, download_name=f.name, mimetype=mime)
    buf = zip_dir(folder)
    return send_file(buf, as_attachment=True,
                     download_name="creativify.zip", mimetype="application/zip")


def human_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n/1024:.1f} KB"
    return f"{n/1048576:.1f} MB"


# ---------- routes -----------------------------------------------------------
@bp.route("/api/image/compress", methods=["POST"])
def img_compress():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Envie pelo menos uma imagem"}), 400
    try:
        quality = int(request.form.get("quality", 75))
    except ValueError:
        quality = 75
    quality = max(20, min(95, quality))

    folder = new_workdir()
    report = []
    for fs in files[:50]:
        try:
            original_bytes = fs.read()
            fs.stream.seek(0)
            img = load_image(fs)
            ext = (fs.filename.rsplit(".", 1)[-1] or "jpg").lower()
            if ext not in OUTPUT_FORMATS or ext in ("png",):
                # keep png as png (lossless optimise) else default jpg
                ext = "png" if ext == "png" else "jpg"
            stem = Path(fs.filename).stem or "imagem"
            out = folder / f"{stem}.{ext}"
            save_image(img, out, ext, quality=quality)
            report.append({
                "name": fs.filename,
                "before": len(original_bytes),
                "after": out.stat().st_size,
            })
        except Exception as e:
            report.append({"name": fs.filename, "error": str(e)})
    # stash report for optional inspection (not strictly needed)
    return respond_files(folder, single_mime="image/jpeg")


@bp.route("/api/image/exif", methods=["POST"])
def img_exif():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Envie pelo menos uma imagem"}), 400
    folder = new_workdir()
    for fs in files[:50]:
        try:
            img = load_image(fs)          # exif_transpose keeps orientation
            data = list(img.getdata())
            clean = Image.new(img.mode, img.size)
            clean.putdata(data)           # new image carries no metadata
            ext = (fs.filename.rsplit(".", 1)[-1] or "jpg").lower()
            if ext not in OUTPUT_FORMATS:
                ext = "jpg"
            stem = Path(fs.filename).stem or "imagem"
            out = folder / f"{stem}_limpo.{ext}"
            save_image(clean, out, ext, quality=92)
        except Exception:
            continue
    return respond_files(folder, single_mime="image/jpeg")


@bp.route("/api/image/convert", methods=["POST"])
def img_convert():
    files = request.files.getlist("files")
    target = (request.form.get("format") or "webp").lower()
    if target not in OUTPUT_FORMATS:
        return jsonify({"error": "Formato de saída inválido"}), 400
    if not files:
        return jsonify({"error": "Envie pelo menos uma imagem"}), 400
    folder = new_workdir()
    for fs in files[:50]:
        try:
            img = load_image(fs)
            stem = Path(fs.filename).stem or "imagem"
            out = folder / f"{stem}.{target}"
            save_image(img, out, target, quality=90)
        except Exception:
            continue
    _, mime = OUTPUT_FORMATS[target]
    return respond_files(folder, single_mime=mime)


@bp.route("/api/image/resize", methods=["POST"])
def img_resize():
    files = request.files.getlist("files")
    mode = request.form.get("mode", "preset")  # preset | custom
    if not files:
        return jsonify({"error": "Envie pelo menos uma imagem"}), 400
    folder = new_workdir()

    targets = []
    if mode == "custom":
        try:
            w = int(request.form.get("width", 0))
            h = int(request.form.get("height", 0))
        except ValueError:
            w = h = 0
        if w <= 0 and h <= 0:
            return jsonify({"error": "Informe largura ou altura"}), 400
        targets.append(("custom", w, h, "Personalizado"))
    else:
        chosen = request.form.getlist("sizes") or list(SOCIAL_SIZES.keys())
        for key in chosen:
            if key in SOCIAL_SIZES:
                w, h, label = SOCIAL_SIZES[key]
                targets.append((key, w, h, label))

    for fs in files[:25]:
        try:
            img = load_image(fs).convert("RGB")
            stem = Path(fs.filename).stem or "imagem"
            for key, w, h, label in targets:
                if key == "custom":
                    if w and h:
                        resized = img.resize((w, h))
                    elif w:
                        ratio = w / img.width
                        resized = img.resize((w, int(img.height * ratio)))
                    else:
                        ratio = h / img.height
                        resized = img.resize((int(img.width * ratio), h))
                else:
                    # fit into target keeping aspect, pad with blur-free white
                    resized = ImageOps.fit(img, (w, h), Image.LANCZOS)
                out = folder / f"{stem}_{key}.jpg"
                save_image(resized, out, "jpg", quality=88)
        except Exception:
            continue
    return respond_files(folder, single_mime="image/jpeg")


