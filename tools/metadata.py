# Auto-ported from working Limpador de Metadados app into a Flask blueprint.
import os
import json
import uuid
import subprocess
import threading
import shutil
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file

bp = Blueprint("metadata", __name__)

UPLOAD_DIR = Path("/tmp/creativify/metadata/uploads")
OUTPUT_DIR = Path("/tmp/creativify/metadata/output")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

jobs = {}

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mts", ".3gp"}

META_FIELD_LABELS = {
    "title": "Título",
    "artist": "Artista",
    "author": "Autor",
    "album": "Álbum",
    "comment": "Comentário",
    "description": "Descrição",
    "copyright": "Copyright",
    "creation_time": "Data de criação",
    "date": "Data",
    "encoder": "Encoder / software",
    "handler_name": "Handler / câmera",
    "com.apple.quicktime.location.iso6709": "Localização GPS (Apple)",
    "location": "Localização GPS",
    "location-eng": "Localização GPS (eng)",
    "com.apple.quicktime.make": "Fabricante (Apple)",
    "com.apple.quicktime.model": "Modelo (Apple)",
    "com.apple.quicktime.software": "Software (Apple)",
    "com.apple.quicktime.author": "Autor (Apple)",
    "com.apple.quicktime.camera.identifier": "ID câmera (Apple)",
    "com.apple.quicktime.creationdate": "Data de criação (Apple)",
    "make": "Fabricante da câmera",
    "model": "Modelo da câmera",
    "software": "Software de edição",
    "device": "Dispositivo",
    "language": "Idioma",
    "genre": "Gênero",
    "track": "Faixa",
    "keywords": "Palavras-chave",
    "synopsis": "Sinopse",
    "network": "Rede",
    "show": "Show / programa",
    "episode_id": "Episódio",
    "season_number": "Temporada",
    "major_brand": "Formato/Brand",
    "minor_version": "Versão do formato",
    "compatible_brands": "Formatos compatíveis",
}

def check_ffmpeg():
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return True, r.stdout.split("\n")[0]
    except:
        pass
    return False, None

def check_ffprobe():
    try:
        r = subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except:
        return False

def extract_metadata(filepath):
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", str(filepath)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {}
        data = json.loads(r.stdout)
        all_tags = {}
        fmt = data.get("format", {})
        for k, v in fmt.get("tags", {}).items():
            all_tags[k.lower()] = {"value": str(v), "source": "container"}
        for i, stream in enumerate(data.get("streams", [])):
            codec_type = stream.get("codec_type", f"stream{i}")
            for k, v in stream.get("tags", {}).items():
                key = k.lower()
                if key not in all_tags:
                    all_tags[key] = {"value": str(v), "source": codec_type}
        return all_tags
    except:
        return {}

def get_file_duration(filepath):
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(filepath)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except:
        return 0

def process_video(job_id, file_id, input_path, output_path):
    job = jobs[job_id]
    file_state = next(f for f in job["files"] if f["id"] == file_id)

    try:
        file_state["status"] = "extracting"
        file_state["progress"] = 5
        file_state["log"] = []

        before_meta = extract_metadata(input_path)
        file_state["progress"] = 15

        # Force output to .mp4 always
        output_path = Path(str(output_path).rsplit(".", 1)[0] + ".mp4")
        file_state["output_path"] = str(output_path)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-map", "0",
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path)
        ]

        file_state["status"] = "processing"
        file_state["progress"] = 20

        proc = subprocess.Popen(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1
        )

        duration = get_file_duration(input_path)
        stderr_lines = []

        for line in proc.stderr:
            line = line.strip()
            stderr_lines.append(line)
            if "time=" in line and duration > 0:
                try:
                    t_str = line.split("time=")[1].split(" ")[0].strip()
                    parts = t_str.split(":")
                    t = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                    pct = min(90, 20 + int((t / duration) * 70))
                    file_state["progress"] = pct
                except:
                    pass

        proc.wait()

        if proc.returncode != 0:
            # Extract useful error from ffmpeg stderr
            error_lines = [l for l in stderr_lines if l and not l.startswith("frame=") and "error" in l.lower() or "invalid" in l.lower() or "failed" in l.lower()]
            error_msg = "\n".join(error_lines[-5:]) if error_lines else "\n".join(stderr_lines[-8:])
            raise RuntimeError(error_msg or "FFmpeg retornou erro desconhecido")

        file_state["progress"] = 92

        after_meta = extract_metadata(output_path)

        removed = []
        for key, info in before_meta.items():
            val = info["value"]
            label = META_FIELD_LABELS.get(key, key)
            removed.append({
                "field": key,
                "label": label,
                "value": val[:200] + ("…" if len(val) > 200 else ""),
                "source": info["source"]
            })

        kept = []
        for key, info in after_meta.items():
            val = info["value"]
            label = META_FIELD_LABELS.get(key, key)
            kept.append({
                "field": key,
                "label": label,
                "value": val[:200] + ("…" if len(val) > 200 else ""),
                "source": info["source"]
            })

        in_size = os.path.getsize(input_path)
        out_size = os.path.getsize(output_path)
        output_filename = Path(output_path).name

        file_state.update({
            "status": "done",
            "progress": 100,
            "removed": removed,
            "kept": kept,
            "removed_count": len(removed),
            "kept_count": len(kept),
            "in_size": in_size,
            "out_size": out_size,
            "output_filename": output_filename,
        })

    except Exception as e:
        file_state["status"] = "error"
        file_state["error"] = str(e)
        file_state["progress"] = 0
        op = Path(file_state.get("output_path", ""))
        if op.exists():
            op.unlink()


def run_job(job_id, max_workers=4):
    job = jobs[job_id]
    job["status"] = "running"
    semaphore = threading.Semaphore(max_workers)
    threads = []

    def worker(file_state):
        with semaphore:
            input_path = Path(file_state["input_path"])
            output_path = Path(file_state["output_path"])
            process_video(job_id, file_state["id"], input_path, output_path)

    for f in job["files"]:
        t = threading.Thread(target=worker, args=(f,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    job["status"] = "done"


@bp.route("/")
def index():
    ffmpeg_ok, ffmpeg_ver = check_ffmpeg()
    ffprobe_ok = check_ffprobe()
    return render_template("metadata.html", ffmpeg_ok=ffmpeg_ok, ffmpeg_ver=ffmpeg_ver, ffprobe_ok=ffprobe_ok)

@bp.route("/api/upload", methods=["POST"])
def api_upload():
    if "files" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    job_id = str(uuid.uuid4())[:8]
    job_upload_dir = UPLOAD_DIR / job_id
    job_output_dir = OUTPUT_DIR / job_id
    job_upload_dir.mkdir(parents=True)
    job_output_dir.mkdir(parents=True)

    file_states = []
    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in VIDEO_EXTS:
            continue

        fid = str(uuid.uuid4())[:8]
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in f.filename)
        input_path = job_upload_dir / safe_name
        stem = Path(safe_name).stem
        output_path = job_output_dir / f"{stem}_limpo.mp4"

        f.save(str(input_path))

        file_states.append({
            "id": fid,
            "original_name": f.filename,
            "safe_name": safe_name,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "status": "queued",
            "progress": 0,
            "removed": [],
            "kept": [],
            "removed_count": 0,
            "kept_count": 0,
            "in_size": os.path.getsize(str(input_path)),
            "out_size": 0,
            "error": None,
        })

    if not file_states:
        shutil.rmtree(str(job_upload_dir))
        shutil.rmtree(str(job_output_dir))
        return jsonify({"error": "Nenhum vídeo válido encontrado"}), 400

    jobs[job_id] = {"id": job_id, "status": "pending", "files": file_states}

    t = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "file_count": len(file_states)})

@bp.route("/api/job/<job_id>")
def api_job(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job não encontrado"}), 404
    job = jobs[job_id]
    files_out = []
    for f in job["files"]:
        files_out.append({
            "id": f["id"],
            "original_name": f["original_name"],
            "status": f["status"],
            "progress": f["progress"],
            "removed": f.get("removed", []),
            "kept": f.get("kept", []),
            "removed_count": f.get("removed_count", 0),
            "kept_count": f.get("kept_count", 0),
            "in_size": f.get("in_size", 0),
            "out_size": f.get("out_size", 0),
            "error": f.get("error"),
            "output_filename": f.get("output_filename"),
        })
    return jsonify({"id": job_id, "status": job["status"], "files": files_out})

@bp.route("/api/download/<job_id>/<file_id>")
def api_download(job_id, file_id):
    if job_id not in jobs:
        return jsonify({"error": "Job não encontrado"}), 404
    job = jobs[job_id]
    file_state = next((f for f in job["files"] if f["id"] == file_id), None)
    if not file_state or file_state["status"] != "done":
        return jsonify({"error": "Arquivo não disponível"}), 404
    output_path = Path(file_state["output_path"])
    if not output_path.exists():
        return jsonify({"error": "Arquivo não encontrado no disco"}), 404
    # Always send as .mp4
    download_name = Path(file_state["original_name"]).stem + "_limpo.mp4"
    return send_file(
        str(output_path),
        as_attachment=True,
        download_name=download_name,
        mimetype="video/mp4"
    )

@bp.route("/api/download-all/<job_id>")
def api_download_all(job_id):
    """Returns a list of download URLs — frontend downloads each file individually as MP4."""
    if job_id not in jobs:
        return jsonify({"error": "Job não encontrado"}), 404
    job = jobs[job_id]
    links = []
    for f in job["files"]:
        if f["status"] == "done":
            links.append({
                "url": f"/api/download/{job_id}/{f['id']}",
                "name": Path(f["original_name"]).stem + "_limpo.mp4"
            })
    return jsonify({"files": links})

