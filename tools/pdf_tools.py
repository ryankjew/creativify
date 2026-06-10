# PDF tools blueprint: visual editor (stamp text/shapes/images), merge, split, compress, rotate.
import os
import io
import json
import base64
import uuid
import shutil
import threading
import time
import subprocess
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from PIL import Image

bp = Blueprint("pdf", __name__)

WORK_DIR = Path("/tmp/creativify/pdf")
WORK_DIR.mkdir(parents=True, exist_ok=True)


def new_workdir():
    d = WORK_DIR / uuid.uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d


def schedule_cleanup(path, delay=600):
    def _rm():
        time.sleep(delay)
        shutil.rmtree(str(path), ignore_errors=True)
    threading.Thread(target=_rm, daemon=True).start()


def send_pdf(path, folder, name="resultado.pdf"):
    schedule_cleanup(folder)
    if not path.exists() or path.stat().st_size == 0:
        return jsonify({"error": "Falha ao gerar o PDF"}), 400
    return send_file(str(path), as_attachment=True,
                     download_name=name, mimetype="application/pdf")


@bp.route("/")
def pdf_index():
    return render_template("pdf.html")


# ---- Editor: stamp edits onto the PDF ---------------------------------------
@bp.route("/api/pdf/edit", methods=["POST"])
def pdf_edit():
    """
    Receives the original PDF + a JSON list of edits with coordinates already
    converted to PDF points (origin bottom-left). Each edit:
      {type:'text', page, x, y, text, size, color}
      {type:'rect', page, x, y, w, h, color, fill}
      {type:'image', page, x, y, w, h, data(base64 png)}
    """
    f = request.files.get("file")
    edits_raw = request.form.get("edits", "[]")
    if not f:
        return jsonify({"error": "Envie um PDF"}), 400
    try:
        edits = json.loads(edits_raw)
    except Exception:
        return jsonify({"error": "Edições inválidas"}), 400

    folder = new_workdir()
    src = folder / "in.pdf"
    f.save(str(src))

    try:
        reader = PdfReader(str(src))
    except Exception:
        schedule_cleanup(folder)
        return jsonify({"error": "Não foi possível ler o PDF"}), 400

    n_pages = len(reader.pages)

    # group edits per page
    by_page = {}
    for e in edits:
        p = int(e.get("page", 0))
        by_page.setdefault(p, []).append(e)

    writer = PdfWriter()

    for idx in range(n_pages):
        page = reader.pages[idx]
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)
        page_edits = by_page.get(idx, [])

        if page_edits:
            # build an overlay the same size as the page
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(pw, ph))
            for e in page_edits:
                etype = e.get("type")
                try:
                    if etype == "text":
                        color = e.get("color", "#111111")
                        size = float(e.get("size", 16))
                        c.setFillColor(HexColor(color))
                        c.setFont("Helvetica", size)
                        # support multi-line
                        lines = str(e.get("text", "")).split("\n")
                        ly = float(e["y"])
                        for ln in lines:
                            c.drawString(float(e["x"]), ly, ln)
                            ly -= size * 1.2
                    elif etype == "rect":
                        color = e.get("color", "#ff3b30")
                        c.setStrokeColor(HexColor(color))
                        c.setLineWidth(float(e.get("line", 2)))
                        fill = e.get("fill")
                        if fill:
                            c.setFillColor(HexColor(fill))
                            c.rect(float(e["x"]), float(e["y"]),
                                   float(e["w"]), float(e["h"]), fill=1, stroke=1)
                        else:
                            c.rect(float(e["x"]), float(e["y"]),
                                   float(e["w"]), float(e["h"]), fill=0, stroke=1)
                    elif etype == "image":
                        data = e.get("data", "")
                        if "," in data:
                            data = data.split(",", 1)[1]
                        img_bytes = base64.b64decode(data)
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                        tmp = folder / f"ov_{uuid.uuid4().hex[:6]}.png"
                        img.save(str(tmp))
                        c.drawImage(str(tmp), float(e["x"]), float(e["y"]),
                                    width=float(e["w"]), height=float(e["h"]),
                                    mask="auto")
                except Exception:
                    continue
            c.save()
            buf.seek(0)
            overlay = PdfReader(buf).pages[0]
            page.merge_page(overlay)

        writer.add_page(page)

    out = folder / "editado.pdf"
    with open(out, "wb") as fh:
        writer.write(fh)
    return send_pdf(out, folder, "editado.pdf")


# ---- Merge ------------------------------------------------------------------
@bp.route("/api/pdf/merge", methods=["POST"])
def pdf_merge():
    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Envie pelo menos 2 PDFs"}), 400
    folder = new_workdir()
    writer = PdfWriter()
    for fs in files:
        p = folder / Path(fs.filename).name
        fs.save(str(p))
        try:
            reader = PdfReader(str(p))
            for pg in reader.pages:
                writer.add_page(pg)
        except Exception:
            continue
    out = folder / "unido.pdf"
    with open(out, "wb") as fh:
        writer.write(fh)
    return send_pdf(out, folder, "unido.pdf")


# ---- Split ------------------------------------------------------------------
@bp.route("/api/pdf/split", methods=["POST"])
def pdf_split():
    f = request.files.get("file")
    ranges = request.form.get("ranges", "").strip()  # e.g. "1-3,5,8-10"
    if not f:
        return jsonify({"error": "Envie um PDF"}), 400
    folder = new_workdir()
    src = folder / "in.pdf"
    f.save(str(src))
    try:
        reader = PdfReader(str(src))
    except Exception:
        schedule_cleanup(folder)
        return jsonify({"error": "Não foi possível ler o PDF"}), 400
    n = len(reader.pages)

    wanted = []
    if ranges:
        for part in ranges.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                try:
                    a, b = int(a), int(b)
                    wanted.extend(range(a, b + 1))
                except ValueError:
                    pass
            elif part.isdigit():
                wanted.append(int(part))
    else:
        wanted = list(range(1, n + 1))
    wanted = [p for p in wanted if 1 <= p <= n]
    if not wanted:
        schedule_cleanup(folder)
        return jsonify({"error": "Páginas inválidas"}), 400

    writer = PdfWriter()
    for p in wanted:
        writer.add_page(reader.pages[p - 1])
    out = folder / "paginas.pdf"
    with open(out, "wb") as fh:
        writer.write(fh)
    return send_pdf(out, folder, "paginas.pdf")


# ---- Compress (via ghostscript if available, else pypdf re-save) ------------
@bp.route("/api/pdf/compress", methods=["POST"])
def pdf_compress():
    f = request.files.get("file")
    level = request.form.get("level", "ebook")  # screen | ebook | printer
    if not f:
        return jsonify({"error": "Envie um PDF"}), 400
    if level not in ("screen", "ebook", "printer"):
        level = "ebook"
    folder = new_workdir()
    src = folder / "in.pdf"
    f.save(str(src))
    out = folder / "comprimido.pdf"

    gs = shutil.which("gs")
    if gs:
        try:
            subprocess.run([
                gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS=/{level}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                f"-sOutputFile={out}", str(src),
            ], check=True, timeout=300)
        except Exception:
            shutil.copy(str(src), str(out))
    else:
        # fallback: re-write with pypdf (modest savings)
        try:
            reader = PdfReader(str(src))
            writer = PdfWriter()
            for pg in reader.pages:
                writer.add_page(pg)
            for pg in writer.pages:
                try:
                    pg.compress_content_streams()
                except Exception:
                    pass
            with open(out, "wb") as fh:
                writer.write(fh)
        except Exception:
            schedule_cleanup(folder)
            return jsonify({"error": "Não foi possível comprimir"}), 400
    return send_pdf(out, folder, "comprimido.pdf")
