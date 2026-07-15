"""Busca web leve (sem API paga) usada como ferramenta pela IA local.

Faz scraping do endpoint HTML "lite" do DuckDuckGo (não precisa de chave de
API). É best-effort: se a rede estiver indisponível ou o layout mudar, a
busca simplesmente retorna uma lista vazia e a IA segue com o que já tem.
"""
import re
import urllib.parse
import urllib.request

DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
TIMEOUT_SEGUNDOS = 8
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Rota13BidIntelligence/1.0"

RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)


def _limpar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = texto.replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"')
    return re.sub(r"\s+", " ", texto).strip()


def search_web(query: str, max_resultados: int = 4) -> list:
    """Retorna até max_resultados dicts {titulo, url, resumo}. Lista vazia em caso de erro."""
    try:
        dados = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            DUCKDUCKGO_URL, data=dados, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    resultados = []
    for m in RESULT_RE.finditer(html):
        url, titulo, resumo = m.group(1), _limpar_html(m.group(2)), _limpar_html(m.group(3))
        if url.startswith("//"):
            url = "https:" + url
        resultados.append({"titulo": titulo, "url": url, "resumo": resumo})
        if len(resultados) >= max_resultados:
            break
    return resultados
