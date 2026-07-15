"""Motor de análise por IA local (Ollama), com fallback automático para o
extractor por regex (scripts/extractor.py) quando a IA está indisponível.

Separação de responsabilidades: a IA só faz a LEITURA/ENTENDIMENTO do edital
(extração estruturada). Todo o cálculo financeiro continua 100% determinístico
em Python (scripts/financial.py) — nunca pedimos matemática para o modelo.

Rastreabilidade: pedimos à IA que cite página + trecho para cada campo. Cada
citação é depois VERIFICADA contra o texto real da página (scripts/citations)
— se o trecho citado não for encontrado na página informada, a citação é
descartada (mostrando o valor sem fonte, nunca uma fonte inventada).

A IA pode usar a ferramenta `buscar_na_internet` quando precisar de uma
informação que não está no texto do edital nem é de conhecimento geral.
"""
import json
import os
import re
import urllib.request

from .citations import verificar_citacao
from .web_search import search_web

OLLAMA_HOST = os.environ.get("ROTA13_OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = os.environ.get("ROTA13_AI_MODEL", "qwen2.5:7b-instruct")
NUM_CTX = int(os.environ.get("ROTA13_AI_NUM_CTX", "8192"))
TIMEOUT_DISPONIBILIDADE = 2
TIMEOUT_GERACAO = 240
MAX_ITERACOES_FERRAMENTA = 3
# Cada chamada preserva um contexto manejável para modelos locais modestos,
# mas o edital inteiro é percorrido por segmentos relevantes; nunca apenas o
# começo do arquivo.
MAX_CHARS_SEGMENTO = 14000
MAX_SEGMENTOS_IA = 8

CATEGORIAS_VALIDAS = [
    "hatch", "sedan", "suv", "pickup", "van", "onibus", "caminhao",
    "ambulancia", "hibrido_phev", "hibrido_hev", "nao_especificado",
]

FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_na_internet",
            "description": (
                "Busca na internet uma informação que não está no texto do edital "
                "fornecido nem é de conhecimento geral confiável (ex.: jurisprudência "
                "recente do TCU, valor atual de mercado de um veículo, notícia recente). "
                "Use com moderação, só quando realmente necessário."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo de busca em português"}
                },
                "required": ["query"],
            },
        },
    }
]

PROMPT_SISTEMA = """Você é um analista sênior de licitações públicas brasileiras, \
especializado em contratos de locação de veículos. O texto do edital abaixo está \
marcado com [PAGINA N] antes do conteúdo de cada página. Leia com atenção e devolva \
APENAS um JSON válido, sem nenhum texto antes ou depois, com esta estrutura exata:

{
  "orgao": {"valor": "nome do órgão licitante", "pagina": <int>, "trecho": "cópia literal de um trecho da página que comprova esse dado"},
  "numero_processo": {"valor": "identificação do pregão/processo", "pagina": <int>, "trecho": "..."},
  "objeto": {"valor": "resumo do objeto em até 3 frases", "pagina": <int>, "trecho": "..."},
  "prazo_contratual_meses": {"valor": <inteiro>, "pagina": <int>, "trecho": "..."},
  "valor_estimado": {"valor": <número, em reais, sem R$ nem separador de milhar>, "pagina": <int>, "trecho": "..."},
  "lotes": [
    {"numero": <inteiro>, "descricao": "...", "quantidade": <inteiro>,
     "categoria_veiculo": "hatch|sedan|suv|pickup|van|onibus|caminhao|ambulancia|hibrido_phev|hibrido_hev|nao_especificado",
     "pagina": <int>, "trecho": "..."}
  ],
  "riscos_juridicos_identificados": ["lista curta de riscos/cláusulas críticas, cada uma citando a página"]
}

Regras importantes:
- "trecho" deve ser uma CÓPIA LITERAL (copiar e colar) de um pedaço real do texto da \
página indicada — nunca invente ou parafraseie. Se não tiver certeza da página exata, \
não invente: use pagina 0 e trecho vazio.
- Responda em português do Brasil.
- Se não encontrar uma informação, use "Não identificado" (texto) ou 0 (número), com pagina 0.
- "categoria_veiculo" deve ser exatamente uma das opções da lista, nunca invente outra.
- Se o edital não usa a palavra "lote", trate o objeto inteiro como um lote único (numero 1).
- Use buscar_na_internet apenas para contexto externo real, nunca para inventar dados do edital.
- Sua resposta final deve ser SOMENTE o JSON, nada mais.
"""


def ollama_disponivel() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=TIMEOUT_DISPONIBILIDADE)
        return True
    except Exception:
        return False


def _chamar_ollama(mensagens: list) -> dict:
    payload = {
        "model": MODEL_NAME,
        "messages": mensagens,
        "tools": FERRAMENTAS,
        "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.1},
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_GERACAO) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extrair_json(texto: str):
    texto = texto.strip()
    texto = re.sub(r"^```(json)?", "", texto).strip()
    texto = re.sub(r"```$", "", texto).strip()
    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio == -1 or fim == -1:
        return None
    try:
        return json.loads(texto[inicio:fim + 1])
    except json.JSONDecodeError:
        return None


def _texto_paginado(paginas: list) -> str:
    partes = [f"[PAGINA {i + 1}]\n{p}" for i, p in enumerate(paginas)]
    return "\n\n".join(partes)


def _segmentos_relevantes(paginas: list) -> list:
    """Agrupa páginas relevantes sem truncar o edital no começo.

    O preâmbulo contém órgão e processo, enquanto tabelas de lotes e valores
    normalmente ficam no TR/anexos. Selecionamos ambos e conservamos os
    marcadores de página para a verificação posterior das citações.
    """
    padrao_prioritario = re.compile(
        r"\b(lote|quantitativo|valor\s+(?:estimado|global)|or[çc]amento|"
        r"termo\s+de\s+refer[êe]ncia)\b", re.IGNORECASE,
    )
    padrao_contexto = re.compile(r"\b(objeto|vig[êe]ncia|prazo\s+de\s+execu[çc][ãa]o)\b", re.IGNORECASE)
    iniciais = list(range(min(5, len(paginas))))
    prioritarias = [i for i, pagina in enumerate(paginas) if padrao_prioritario.search(pagina) and i not in iniciais]
    contexto = [i for i, pagina in enumerate(paginas) if padrao_contexto.search(pagina) and i not in iniciais and i not in prioritarias]
    # A ordem é intencional: não deixe dezenas de ocorrências de cláusulas de
    # vigência expulsarem as tabelas do TR do limite de chamadas locais.
    indices = iniciais + prioritarias + contexto

    segmentos, atual = [], []
    tamanho_atual = 0
    for i in indices:
        pagina_marcada = f"[PAGINA {i + 1}]\n{paginas[i]}"
        if atual and tamanho_atual + len(pagina_marcada) > MAX_CHARS_SEGMENTO:
            segmentos.append("\n\n".join(atual))
            atual, tamanho_atual = [], 0
        atual.append(pagina_marcada)
        tamanho_atual += len(pagina_marcada) + 2
    if atual:
        segmentos.append("\n\n".join(atual))

    # Evita muitas chamadas em um edital excepcionalmente longo. As páginas
    # iniciais e as últimas continuam representadas nos segmentos selecionados.
    return segmentos[:MAX_SEGMENTOS_IA]


def _campo_com_fonte(bruto, paginas: list, tipo=str):
    """Recebe {"valor":..., "pagina":..., "trecho":...} e devolve (valor_tipado, fonte|None),
    verificando a citação contra o texto real da página antes de aceitá-la."""
    if not isinstance(bruto, dict):
        return (tipo(bruto) if bruto not in (None, "") else (tipo() if tipo is not str else "Não identificado")), None
    try:
        valor = tipo(bruto.get("valor"))
    except (TypeError, ValueError):
        valor = tipo() if tipo is not str else "Não identificado"
    pagina = bruto.get("pagina") or 0
    trecho_citado = (bruto.get("trecho") or "").strip()
    fonte = None
    try:
        pagina = int(pagina)
    except (TypeError, ValueError):
        pagina = 0
    if pagina and 1 <= pagina <= len(paginas) and trecho_citado:
        if verificar_citacao(paginas, pagina, trecho_citado):
            fonte = {"pagina": pagina, "trecho": trecho_citado[:200]}
    return valor, fonte


def _normalizar(dados: dict, paginas: list) -> dict:
    orgao, fonte_orgao = _campo_com_fonte(dados.get("orgao"), paginas, str)
    numero_processo, fonte_processo = _campo_com_fonte(dados.get("numero_processo"), paginas, str)
    objeto, fonte_objeto = _campo_com_fonte(dados.get("objeto"), paginas, str)
    prazo, fonte_prazo = _campo_com_fonte(dados.get("prazo_contratual_meses"), paginas, int)
    valor_estimado, fonte_valor = _campo_com_fonte(dados.get("valor_estimado"), paginas, float)

    lotes_norm = []
    for lote in dados.get("lotes") or []:
        categoria = str(lote.get("categoria_veiculo", "nao_especificado")).lower()
        if categoria not in CATEGORIAS_VALIDAS:
            categoria = "nao_especificado"
        try:
            numero = int(lote.get("numero", len(lotes_norm) + 1))
        except (TypeError, ValueError):
            numero = len(lotes_norm) + 1
        try:
            quantidade = max(1, int(lote.get("quantidade", 1)))
        except (TypeError, ValueError):
            quantidade = 1

        pagina = lote.get("pagina") or 0
        trecho_citado = (lote.get("trecho") or "").strip()
        fonte_lote = None
        try:
            pagina = int(pagina)
        except (TypeError, ValueError):
            pagina = 0
        if pagina and 1 <= pagina <= len(paginas) and trecho_citado and verificar_citacao(paginas, pagina, trecho_citado):
            fonte_lote = {"pagina": pagina, "trecho": trecho_citado[:200]}

        lotes_norm.append({
            "numero": numero,
            "descricao": str(lote.get("descricao", f"Lote {numero}"))[:250],
            "quantidade": quantidade,
            "categoria_veiculo": categoria,
            "fonte": fonte_lote,
        })

    if not lotes_norm:
        lotes_norm = [{"numero": 1, "descricao": "Lote único (IA não segmentou o edital)",
                        "quantidade": 1, "categoria_veiculo": "nao_especificado", "fonte": None}]

    return {
        "orgao": orgao or "Órgão não identificado",
        "numero_processo": numero_processo or "Não identificado",
        "objeto": objeto or "Objeto não identificado — revisar edital manualmente.",
        "prazo_contratual_meses": prazo or 12,
        "valor_estimado": valor_estimado or 0.0,
        "valor_estimado_explicito": fonte_valor is not None,
        "lotes": lotes_norm,
        "qtd_lotes": len(lotes_norm),
        "qtd_itens": sum(l["quantidade"] for l in lotes_norm),
        "fontes": {
            "orgao": fonte_orgao, "numero_processo": fonte_processo, "objeto": fonte_objeto,
            "prazo_contratual_meses": fonte_prazo, "valor_estimado": fonte_valor,
        },
        "riscos_juridicos_ia": dados.get("riscos_juridicos_identificados") or [],
        "motor": "ia",
    }


def _extrair_segmento_com_ia(texto_segmento: str, paginas: list):
    """Executa uma chamada de extração e mantém o protocolo de ferramentas."""
    mensagens = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": f"Trecho do edital (pode ser parcial):\n\n{texto_segmento}"},
    ]
    for _ in range(MAX_ITERACOES_FERRAMENTA):
        resposta = _chamar_ollama(mensagens)
        msg = resposta.get("message", {})
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            dados = _extrair_json(msg.get("content", ""))
            return _normalizar(dados, paginas) if dados else None

        mensagens.append(msg)
        for call in tool_calls:
            nome = call.get("function", {}).get("name")
            args = call.get("function", {}).get("arguments", {})
            if nome == "buscar_na_internet":
                conteudo_ferramenta = json.dumps(search_web(args.get("query", "")), ensure_ascii=False)
            else:
                conteudo_ferramenta = "Ferramenta desconhecida."
            mensagens.append({"role": "tool", "content": conteudo_ferramenta})
    return None


def _unir_extracoes(extracoes: list) -> dict | None:
    """Consolida extrações parciais, sempre preferindo valores com citação."""
    if not extracoes:
        return None

    campos_texto = {"orgao": "Órgão não identificado", "numero_processo": "Não identificado"}
    resultado = {
        **campos_texto,
        "objeto": "Objeto não identificado — revisar edital manualmente.",
        "prazo_contratual_meses": 12,
        "valor_estimado": 0.0,
        "valor_estimado_explicito": False,
        "lotes": [],
        "fontes": {"orgao": None, "numero_processo": None, "objeto": None,
                    "prazo_contratual_meses": None, "valor_estimado": None},
        "riscos_juridicos_ia": [], "motor": "ia",
    }
    lotes_por_numero = {}
    for dados in extracoes:
        for campo, padrao in campos_texto.items():
            if resultado[campo] == padrao and dados.get(campo) != padrao:
                resultado[campo] = dados[campo]
                resultado["fontes"][campo] = dados.get("fontes", {}).get(campo)
        if resultado["objeto"].startswith("Objeto não identificado") and not dados.get("objeto", "").startswith("Objeto não identificado"):
            resultado["objeto"] = dados["objeto"]
            resultado["fontes"]["objeto"] = dados.get("fontes", {}).get("objeto")
        if resultado["prazo_contratual_meses"] == 12 and dados.get("prazo_contratual_meses", 12) != 12:
            resultado["prazo_contratual_meses"] = dados["prazo_contratual_meses"]
            resultado["fontes"]["prazo_contratual_meses"] = dados.get("fontes", {}).get("prazo_contratual_meses")
        if not resultado["valor_estimado_explicito"] and dados.get("valor_estimado_explicito"):
            resultado["valor_estimado"] = dados["valor_estimado"]
            resultado["valor_estimado_explicito"] = True
            resultado["fontes"]["valor_estimado"] = dados.get("fontes", {}).get("valor_estimado")

        for lote in dados.get("lotes", []):
            numero = lote["numero"]
            atual = lotes_por_numero.get(numero)
            if atual is None or (not atual.get("fonte") and lote.get("fonte")):
                lotes_por_numero[numero] = lote
        resultado["riscos_juridicos_ia"].extend(dados.get("riscos_juridicos_ia", []))

    resultado["lotes"] = [lotes_por_numero[n] for n in sorted(lotes_por_numero)]
    resultado["qtd_lotes"] = len(resultado["lotes"])
    resultado["qtd_itens"] = sum(l["quantidade"] for l in resultado["lotes"])
    return resultado


def extract_with_ai(paginas: list):
    """Tenta extrair os dados estruturados do edital usando o Ollama local.
    Retorna None (silenciosamente) se a IA estiver indisponível ou falhar —
    quem chama deve cair de volta para o extractor por regex."""
    if not ollama_disponivel():
        return None

    try:
        extracoes = [
            dados for segmento in _segmentos_relevantes(paginas)
            if (dados := _extrair_segmento_com_ia(segmento, paginas)) is not None
        ]
        return _unir_extracoes(extracoes)
    except Exception:
        return None
