import os
from pathlib import Path
from flask import Flask, render_template

# Tool blueprints (each isolated; one failing won't break the others)
from tools.downloader import bp as downloader_bp
from tools.metadata import bp as metadata_bp
from tools.imaging import bp as imaging_bp
from tools.video import bp as video_bp
from tools.pdf_tools import bp as pdf_bp
from tools.bgremove import bp as bgremove_bp

app = Flask(__name__)
# Evita que o Railway sirva versões antigas dos templates/estáticos
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.jinja_env.auto_reload = True

# Shared work area
Path("/tmp/creativify").mkdir(parents=True, exist_ok=True)

# Mount each tool under its own URL prefix
app.register_blueprint(downloader_bp, url_prefix="/t/downloader")
app.register_blueprint(metadata_bp, url_prefix="/t/metadata")
app.register_blueprint(imaging_bp, url_prefix="/t/imaging")
app.register_blueprint(video_bp, url_prefix="/t/video")
app.register_blueprint(pdf_bp, url_prefix="/t/pdf")
app.register_blueprint(bgremove_bp, url_prefix="/t/bgremove")

# Catalog used by the dashboard. `ready` = backend wired up and working.
TOOLS = [
    # Vídeo
    {"id": "downloader", "cat": "video", "name": "Downloader em massa",
     "desc": "Baixe vídeos de TikTok, YouTube, Instagram e +1000 sites",
     "icon": "Download", "ready": True, "popular": True, "url": "/t/downloader/"},
    {"id": "metadata", "cat": "video", "name": "Limpador de metadados",
     "desc": "Remova dados de rastreamento dos seus vídeos",
     "icon": "Eraser", "ready": True, "popular": True, "url": "/t/metadata/"},
    {"id": "vcompress", "cat": "video", "name": "Compressor de vídeo",
     "desc": "Reduza o tamanho sem perder qualidade", "icon": "Minimize2",
     "ready": True, "url": "/t/video/?tool=compress"},
    {"id": "vcut", "cat": "video", "name": "Cortador por tempo",
     "desc": "Corte trechos exatos do seu vídeo", "icon": "Scissors",
     "ready": True, "url": "/t/video/?tool=cut"},
    {"id": "vconvert", "cat": "video", "name": "Conversor de formato",
     "desc": "MP4, MOV, WebM, AVI e mais", "icon": "RefreshCw",
     "ready": True, "url": "/t/video/?tool=convert"},
    {"id": "vaudio", "cat": "video", "name": "Extrator de áudio",
     "desc": "Extraia o áudio em MP3 ou WAV", "icon": "Music",
     "ready": True, "url": "/t/video/?tool=audio"},
    {"id": "vresize", "cat": "video", "name": "Redimensionar p/ redes",
     "desc": "Gere 9:16, 16:9, 1:1 e 4:5 de um vídeo", "icon": "Crop", "popular": True},
    {"id": "vwatermark", "cat": "video", "name": "Removedor de marca d'água",
     "desc": "Remova logos e marcas em massa", "icon": "Droplet", "popular": True},
    {"id": "vsubsremove", "cat": "video", "name": "Removedor de legenda fixa",
     "desc": "Apague legendas queimadas com IA", "icon": "Captions"},
    # Imagens (these are wired up now)
    {"id": "iexif", "cat": "image", "name": "Limpador de EXIF",
     "desc": "Remova GPS e dados da câmera das fotos", "icon": "Eraser",
     "ready": True, "url": "/t/imaging/?tool=exif"},
    {"id": "icompress", "cat": "image", "name": "Compressor inteligente",
     "desc": "PNG, JPG e WebP menores sem perder nitidez", "icon": "Minimize2",
     "ready": True, "popular": True, "url": "/t/imaging/?tool=compress"},
    {"id": "ibg", "cat": "image", "name": "Removedor de fundo",
     "desc": "Remova o fundo com um clique usando IA", "icon": "Wand2",
     "popular": True, "ready": True, "url": "/t/bgremove/"},
    {"id": "iconvert", "cat": "image", "name": "Conversor universal",
     "desc": "Converta entre 200+ formatos de arquivo", "icon": "RefreshCw",
     "ready": True, "popular": True, "url": "/t/imaging/?tool=convert"},
    {"id": "iresize", "cat": "image", "name": "Redimensionador",
     "desc": "Ajuste o tamanho de imagens em massa", "icon": "Maximize2",
     "ready": True, "url": "/t/imaging/?tool=resize"},
    {"id": "iupscale", "cat": "image", "name": "Melhorar qualidade (IA)",
     "desc": "Aumente a resolução 2x ou 4x sem pixelar", "icon": "Sparkles", "popular": True},
    {"id": "iformat", "cat": "image", "name": "Conversor de formato",
     "desc": "JPG, PNG, WebP, AVIF e mais", "icon": "FileImage"},
    # PDF
    {"id": "pcompress", "cat": "pdf", "name": "Compressor de PDF",
     "desc": "Deixe seus PDFs mais leves para enviar", "icon": "Minimize2",
     "ready": True, "url": "/t/pdf/?tool=compress"},
    {"id": "pconvert", "cat": "pdf", "name": "PDF → Word/Excel",
     "desc": "Converta PDF em documentos editáveis", "icon": "FileOutput", "popular": True},
    {"id": "pmerge", "cat": "pdf", "name": "Juntar e dividir",
     "desc": "Combine ou separe páginas de PDF", "icon": "Combine",
     "ready": True, "url": "/t/pdf/?tool=merge"},
    {"id": "psign", "cat": "pdf", "name": "Assinador",
     "desc": "Assine documentos digitalmente", "icon": "PenTool"},
    {"id": "pedit", "cat": "pdf", "name": "Editor completo",
     "desc": "Edite texto, imagens e páginas do PDF", "icon": "Edit3",
     "popular": True, "ready": True, "url": "/t/pdf/?tool=edit"},
    # IA
    {"id": "atranscribe", "cat": "ai", "name": "Transcritor",
     "desc": "Transforme áudio e vídeo em texto", "icon": "Mic", "popular": True},
    {"id": "acaptions", "cat": "ai", "name": "Legendas automáticas",
     "desc": "Gere arquivos SRT automaticamente", "icon": "Subtitles", "popular": True},
    {"id": "asummary", "cat": "ai", "name": "Resumidor do YouTube",
     "desc": "Resuma vídeos longos em segundos", "icon": "Youtube"},
    {"id": "atranslate", "cat": "ai", "name": "Tradutor de legendas",
     "desc": "Traduza legendas para qualquer idioma", "icon": "Languages"},
    {"id": "asilence", "cat": "ai", "name": "Removedor de silêncio",
     "desc": "Corte pausas e silêncios do vídeo", "icon": "VolumeX"},
]

CATEGORIES = [
    {"id": "video", "label": "Vídeo", "color": "#7c6dff"},
    {"id": "image", "label": "Imagens", "color": "#22c97a"},
    {"id": "pdf", "label": "PDF", "color": "#ff7a59"},
    {"id": "ai", "label": "IA", "color": "#f5c451"},
]


@app.route("/")
def dashboard():
    return render_template("dashboard.html", tools=TOOLS, categories=CATEGORIES)


@app.route("/health")
def health():
    return {"ok": True, "tools": len(TOOLS),
            "ready": sum(1 for t in TOOLS if t.get("ready"))}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    ready = sum(1 for t in TOOLS if t.get("ready"))
    print(f"\n🎨 Creativify — porta {port}  ({ready}/{len(TOOLS)} ferramentas no ar)\n")
    app.run(host="0.0.0.0", port=port, threaded=True)
