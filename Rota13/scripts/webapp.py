"""Servidor web local e interativo do Rota13 (stdlib puro, sem Flask/Django).

Fluxo: usuário abre o navegador, entra com a senha de acesso, arrasta um
edital em PDF, e recebe o Dashboard renderizado na mesma tela — sem precisar
copiar arquivo para pasta nem rodar comando de novo.

Protegido por uma senha única (não é um sistema de login/multiusuário — é
uma trava simples porque o servidor pode ficar exposto na internet pública,
conforme decidido para este projeto). A senha é definida por
ROTA13_PASSWORD; se não for definida, uma senha aleatória é gerada e
impressa no console a cada início.
"""
import html
import json
import os
import secrets
import socket
import threading
import time
import traceback
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
HISTORICAL_DIR = BASE_DIR / "historical"

HOST = os.environ.get("ROTA13_HOST", "0.0.0.0")
PORT = int(os.environ.get("ROTA13_PORT", "8000"))
SENHA = os.environ.get("ROTA13_PASSWORD") or secrets.token_urlsafe(9)
SESSAO_HORAS = 12
JOB_TTL_SEGUNDOS = 3600  # jobs concluídos são descartados da memória depois de 1h

_sessoes_validas = {}  # token -> expira_em (epoch seconds)


class _Job:
    """Acompanha o progresso de uma análise rodando em background. O navegador
    consulta o status por polling (GET /status/<id> a cada ~1,5s) em vez de
    manter uma conexão de streaming aberta — proxies (ex.: o do Codespaces)
    costumam derrubar conexões de streaming (SSE), então polling simples é
    o mecanismo que funciona de forma confiável atrás de qualquer proxy."""

    def __init__(self, nome_arquivo: str):
        self.nome_arquivo = nome_arquivo
        self.historico = []
        self.status = "processando"  # processando | concluido | erro
        self.resultado_html = None
        self.erro = None
        self.criado_em = time.time()
        self._lock = threading.Lock()

    def log(self, mensagem: str):
        print(f"   {mensagem}")
        with self._lock:
            self.historico.append(mensagem)

    def concluir(self, resultado_html: str):
        self.resultado_html = resultado_html
        with self._lock:
            self.status = "concluido"

    def falhar(self, erro: str):
        self.erro = erro
        with self._lock:
            self.status = "erro"

    def snapshot(self) -> dict:
        with self._lock:
            return {"historico": list(self.historico), "status": self.status, "erro": self.erro}


_jobs = {}  # job_id -> _Job
_jobs_lock = threading.Lock()


def _limpar_jobs_antigos():
    limite = time.time() - JOB_TTL_SEGUNDOS
    with _jobs_lock:
        expirados = [jid for jid, j in _jobs.items() if j.status != "processando" and j.criado_em < limite]
        for jid in expirados:
            del _jobs[jid]

CSS_BASE = """
:root{--bg:#0b0f14;--bg-card:#12181f;--border:#233040;--text:#e6edf3;--text-dim:#8b98a5;
  --accent:#3b82f6;--ok:#22c55e;--bad:#ef4444}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;align-items:center}
header{padding:24px;text-align:center}
header .brand{color:var(--accent);font-weight:800;font-size:22px;letter-spacing:.5px}
header p{color:var(--text-dim);margin:4px 0 0}
main{width:100%;max-width:640px;padding:0 20px 60px}
.card{background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:28px;margin-bottom:20px}
h2{margin-top:0;font-size:18px}
input[type=password],input[type=file]{width:100%;padding:12px;border-radius:8px;border:1px solid var(--border);
  background:var(--bg);color:var(--text);font-size:14px}
button{background:var(--accent);color:#fff;border:none;padding:12px 20px;border-radius:8px;font-size:15px;
  font-weight:600;cursor:pointer;margin-top:14px;width:100%}
button:hover{opacity:.9}
.drop{border:2px dashed var(--border);border-radius:12px;padding:40px 20px;text-align:center;color:var(--text-dim);
  cursor:pointer;transition:.2s}
.drop.drag{border-color:var(--accent);color:var(--text)}
.msg-erro{color:var(--bad);font-size:13px;margin-top:10px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.hist-item{display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid var(--border)}
.hist-item:last-child{border-bottom:none}
.hist-meta{color:var(--text-dim);font-size:12px}
#overlay{position:fixed;inset:0;background:rgba(11,15,20,.92);display:none;align-items:center;justify-content:center;
  flex-direction:column;z-index:50;gap:16px}
#overlay.show{display:flex}
.spinner{width:44px;height:44px;border:4px solid var(--border);border-top-color:var(--accent);border-radius:50%;
  animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.progress-log{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:14px;
  font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;line-height:1.7;max-height:340px;
  overflow-y:auto;text-align:left;white-space:pre-wrap}
.progress-log .linha{color:var(--text-dim)}
.progress-log .linha:last-child{color:var(--text)}
"""


def _pagina(corpo: str, titulo: str = "Rota13 Bid Intelligence") -> bytes:
    html_doc = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{titulo}</title><style>{CSS_BASE}</style></head><body>
<header><div class="brand">ROTA13</div><p>Bid Intelligence — Análise de Editais de Locação de Veículos</p></header>
<main>{corpo}</main></body></html>"""
    return html_doc.encode("utf-8")


def _pagina_login(erro: bool = False) -> bytes:
    erro_html = '<div class="msg-erro">Senha incorreta.</div>' if erro else ""
    corpo = f"""
    <div class="card">
      <h2>Acesso</h2>
      <form method="POST" action="/login">
        <input type="password" name="senha" placeholder="Senha de acesso" autofocus required>
        {erro_html}
        <button type="submit">Entrar</button>
      </form>
    </div>"""
    return _pagina(corpo, "Rota13 — Acesso")


def _pagina_upload() -> bytes:
    corpo = """
    <div class="card">
      <h2>Analisar novo edital</h2>
      <form id="form-upload" method="POST" action="/analisar" enctype="multipart/form-data">
        <div class="drop" id="drop" onclick="document.getElementById('arquivo').click()">
          📄 Clique ou arraste o edital em PDF aqui
          <div id="nome-arquivo" style="margin-top:8px;font-size:12px"></div>
        </div>
        <input type="file" id="arquivo" name="edital" accept="application/pdf" style="display:none" required>
        <button type="submit">Analisar edital</button>
      </form>
    </div>
    <div class="card">
      <a href="/historico">📁 Ver histórico de análises anteriores</a>
    </div>
    <div id="overlay"><div class="spinner"></div>
      <div>Analisando edital — isso pode levar alguns minutos com a IA local...</div>
    </div>
    <script>
      const input = document.getElementById('arquivo');
      const drop = document.getElementById('drop');
      const nome = document.getElementById('nome-arquivo');
      const form = document.getElementById('form-upload');
      const overlay = document.getElementById('overlay');

      input.addEventListener('change', () => { if(input.files[0]) nome.textContent = input.files[0].name; });
      ['dragover','dragenter'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); }));
      ['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); }));
      drop.addEventListener('drop', e => {
        if(e.dataTransfer.files[0]){ input.files = e.dataTransfer.files; nome.textContent = input.files[0].name; }
      });
      form.addEventListener('submit', () => { overlay.classList.add('show'); });
    </script>
    """
    return _pagina(corpo, "Rota13 — Analisar edital")


def _pagina_progresso(job_id: str, nome_arquivo: str) -> bytes:
    corpo = f"""
    <div class="card">
      <h2>Analisando: {html.escape(nome_arquivo)}</h2>
      <div style="text-align:center;margin-bottom:14px"><div class="spinner" style="margin:0 auto"></div></div>
      <div class="progress-log" id="log">Iniciando...</div>
      <p id="msg-erro" class="msg-erro" style="display:none"></p>
      <a href="/" id="link-voltar" style="display:none">← Voltar</a>
    </div>
    <script>
      const logEl = document.getElementById('log');
      const linhas = [];
      let indiceVisto = 0;
      function render(){{ logEl.innerHTML = linhas.map(l => '<div class="linha">'+l+'</div>').join(''); logEl.scrollTop = logEl.scrollHeight; }}

      function consultar(){{
        fetch('/status/{job_id}')
          .then(r => r.json())
          .then(dados => {{
            for(let i = indiceVisto; i < dados.historico.length; i++){{
              linhas.push(dados.historico[i].replace(/</g,'&lt;'));
            }}
            indiceVisto = dados.historico.length;
            render();
            if(dados.status === 'concluido'){{
              window.location = '/resultado/{job_id}';
            }} else if(dados.status === 'erro'){{
              document.querySelector('.spinner').style.display = 'none';
              const erroEl = document.getElementById('msg-erro');
              erroEl.textContent = dados.erro;
              erroEl.style.display = 'block';
              document.getElementById('link-voltar').style.display = 'block';
            }} else {{
              setTimeout(consultar, 1500);
            }}
          }})
          .catch(() => setTimeout(consultar, 2500)); // proxy instável: tenta de novo
      }}
      consultar();
    </script>
    """
    return _pagina(corpo, "Rota13 — Analisando...")


def _pagina_historico() -> bytes:
    itens = []
    if HISTORICAL_DIR.exists():
        pastas = sorted(HISTORICAL_DIR.glob("*/*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for pasta in pastas:
            dash = pasta / "dashboard.html"
            if not dash.exists():
                continue
            ano = pasta.parent.name
            link = f"/historico/{urllib.parse.quote(ano)}/{urllib.parse.quote(pasta.name)}/dashboard.html"
            mtime = datetime.fromtimestamp(dash.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            itens.append(
                f'<div class="hist-item"><div><a href="{link}">{html.escape(pasta.name)}</a>'
                f'<div class="hist-meta">Ano {html.escape(ano)}</div></div>'
                f'<div class="hist-meta">{mtime}</div></div>'
            )
    lista_html = "".join(itens) or '<p style="color:var(--text-dim)">Nenhuma análise ainda.</p>'
    corpo = f"""
    <div class="card">
      <h2>Histórico de análises</h2>
      {lista_html}
    </div>
    <div class="card"><a href="/">← Analisar novo edital</a></div>
    """
    return _pagina(corpo, "Rota13 — Histórico")


def _parse_multipart(body: bytes, content_type: str):
    if "boundary=" not in content_type:
        return None, None
    boundary = content_type.split("boundary=")[-1].strip().strip('"').encode()
    partes = body.split(b"--" + boundary)
    for parte in partes:
        if b"Content-Disposition" not in parte:
            continue
        if b'name="edital"' not in parte:
            continue
        cabecalho, _, conteudo = parte.partition(b"\r\n\r\n")
        if conteudo.endswith(b"\r\n"):
            conteudo = conteudo[:-2]
        nome_arquivo = "edital.pdf"
        m = cabecalho.decode("latin-1")
        if 'filename="' in m:
            nome_arquivo = m.split('filename="')[1].split('"')[0] or "edital.pdf"
        return nome_arquivo, conteudo
    return None, None


def _make_handler():
    from . import db
    from .pipeline import processar_pdf

    class Handler(BaseHTTPRequestHandler):
        server_version = "Rota13/1.0"

        def log_message(self, fmt, *args):
            print(f"   [web] {self.address_string()} - {fmt % args}")

        def _cookie_token(self):
            cookie = self.headers.get("Cookie", "")
            for parte in cookie.split(";"):
                if "=" in parte:
                    k, v = parte.strip().split("=", 1)
                    if k == "rota13_sessao":
                        return v
            return None

        def _autenticado(self):
            token = self._cookie_token()
            if not token:
                return False
            expira = _sessoes_validas.get(token)
            return bool(expira and expira > time.time())

        def _enviar(self, corpo: bytes, status=200, content_type="text/html; charset=utf-8", extra_headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(corpo)))
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(corpo)

        def _redirect(self, local: str, extra_headers=None):
            self.send_response(303)
            self.send_header("Location", local)
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            if path == "/" :
                if not self._autenticado():
                    return self._enviar(_pagina_login())
                return self._enviar(_pagina_upload())
            if path == "/historico":
                if not self._autenticado():
                    return self._redirect("/")
                return self._enviar(_pagina_historico())
            if path.startswith("/historico/"):
                if not self._autenticado():
                    return self._redirect("/")
                return self._servir_arquivo_historico(path)
            if path.startswith("/status/"):
                if not self._autenticado():
                    return self._redirect("/")
                return self._status_job(path[len("/status/"):])
            if path.startswith("/resultado/"):
                if not self._autenticado():
                    return self._redirect("/")
                return self._servir_resultado(path[len("/resultado/"):])
            self._enviar(b"Nao encontrado", status=404)

        def _status_job(self, job_id):
            job = _jobs.get(job_id)
            if job is None:
                return self._enviar(
                    json.dumps({"historico": [], "status": "erro", "erro": "Job não encontrado."}).encode("utf-8"),
                    status=404, content_type="application/json; charset=utf-8",
                )
            payload = json.dumps(job.snapshot(), ensure_ascii=False).encode("utf-8")
            return self._enviar(payload, content_type="application/json; charset=utf-8")

        def _servir_resultado(self, job_id):
            job = _jobs.get(job_id)
            if job is None or job.status != "concluido":
                return self._enviar(b"Resultado nao encontrado ou ainda processando", status=404)
            return self._enviar(job.resultado_html.encode("utf-8"))

        def _servir_arquivo_historico(self, path):
            rel = path[len("/historico/"):]
            alvo = (HISTORICAL_DIR / urllib.parse.unquote(rel)).resolve()
            if HISTORICAL_DIR.resolve() not in alvo.parents and alvo != HISTORICAL_DIR.resolve():
                return self._enviar(b"Acesso negado", status=403)
            if not alvo.exists() or not alvo.is_file():
                return self._enviar(b"Nao encontrado", status=404)
            tipo = "application/pdf" if alvo.suffix == ".pdf" else \
                   "application/json; charset=utf-8" if alvo.suffix == ".json" else \
                   "text/html; charset=utf-8"
            self._enviar(alvo.read_bytes(), content_type=tipo)

        def do_POST(self):
            path = urllib.parse.urlsplit(self.path).path
            tamanho = int(self.headers.get("Content-Length", 0))
            corpo = self.rfile.read(tamanho) if tamanho else b""

            if path == "/login":
                dados = urllib.parse.parse_qs(corpo.decode("utf-8"))
                senha = (dados.get("senha") or [""])[0]
                if senha == SENHA:
                    token = secrets.token_urlsafe(24)
                    _sessoes_validas[token] = time.time() + SESSAO_HORAS * 3600
                    return self._redirect("/", {"Set-Cookie": f"rota13_sessao={token}; Path=/; HttpOnly"})
                return self._enviar(_pagina_login(erro=True))

            if path == "/analisar":
                if not self._autenticado():
                    return self._redirect("/")
                content_type = self.headers.get("Content-Type", "")
                nome_arquivo, conteudo_pdf = _parse_multipart(corpo, content_type)
                if not conteudo_pdf:
                    return self._enviar(_pagina("<div class='card'><h2>Erro</h2><p>Nenhum arquivo recebido.</p>"
                                                 "<a href='/'>Voltar</a></div>"), status=400)

                UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                nome_seguro = "".join(c for c in Path(nome_arquivo).name if c.isalnum() or c in "._-") or "edital.pdf"
                destino = UPLOADS_DIR / f"{int(time.time())}_{nome_seguro}"
                destino.write_bytes(conteudo_pdf)

                _limpar_jobs_antigos()
                job_id = secrets.token_hex(12)
                job = _Job(nome_arquivo)
                with _jobs_lock:
                    _jobs[job_id] = job

                def _rodar():
                    conn = db.get_conn()
                    try:
                        resultado = processar_pdf(conn, destino, log=job.log)
                        job.concluir(resultado["dashboard_html"])
                    except Exception as e:
                        traceback.print_exc()
                        job.falhar(str(e))
                    finally:
                        conn.close()

                threading.Thread(target=_rodar, daemon=True).start()
                return self._enviar(_pagina_progresso(job_id, nome_arquivo))

            self._enviar(b"Nao encontrado", status=404)

    return Handler


def _ip_local() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def run_server():
    handler = _make_handler()
    servidor = ThreadingHTTPServer((HOST, PORT), handler)

    print("\n" + "=" * 60)
    print(" SERVIDOR WEB ROTA13 NO AR")
    print("=" * 60)
    print(f" Local:        http://127.0.0.1:{PORT}")
    print(f" Rede/Internet: http://{_ip_local()}:{PORT}  (depende do firewall/roteador liberar a porta {PORT})")
    print(f" Senha de acesso: {SENHA}")
    print("=" * 60)
    print(" Pressione Ctrl+C para encerrar.\n")

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor...")
        servidor.shutdown()
