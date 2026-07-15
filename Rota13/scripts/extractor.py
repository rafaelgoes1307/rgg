"""Extração heurística de informações de editais de locação de veículos.

Editais brasileiros não têm um layout padronizado, então a extração aqui é
baseada em expressões regulares e palavras-chave. Quando uma informação não
é encontrada, o campo retorna um valor padrão explícito (nunca None solto),
para que o Dashboard sempre tenha algo exibível.

Toda informação encontrada vem acompanhada de uma "fonte" (página + trecho
do PDF onde foi localizada), para rastreabilidade — ver scripts/citations.py.
Este é o motor "defensável": determinístico, sem alucinação, 100% auditável.
"""
import re
import unicodedata

from .citations import construir_indice_paginas, fonte_do_match, pagina_do_offset, trecho as _trecho

CATEGORIAS_VEICULO = {
    "hatch": ["hatch", "popular", "compacto"],
    "sedan": ["sedan", "sedã"],
    "suv": ["suv", "utilitário esportivo"],
    "pickup": ["pick-up", "pickup", "caminhonete", "cabine dupla"],
    "van": ["van", "utilitário de carga", "furgão"],
    "onibus": ["ônibus", "micro-ônibus", "microônibus"],
    "caminhao": ["caminhão", "caminhao", "basculante", "baú"],
    "ambulancia": ["ambulância", "ambulancia"],
    "hibrido": ["híbrido", "hibrido", "hybrid", "hev", "phev"],
}


def _primeiras_linhas(texto, n=60):
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    return linhas[:n]


def extract_orgao(texto: str, offsets: list):
    # [^\S\n] = espaço/tab mas nunca quebra de linha, para não engolir o
    # cabeçalho inteiro do edital quando várias linhas seguidas estão em maiúsculas.
    padroes = [
        # Órgãos estaduais costumam aparecer no cabeçalho com essa forma. Os
        # padrões específicos vêm antes dos genéricos para não capturar uma
        # referência administrativa perdida nas páginas seguintes.
        r"SECRETARIA\s+DA\s+ADMINISTRA[CÇ][ÃA]O(?:\s+DO\s+ESTADO\s+DA\s+BAHIA)?",
        r"PREFEITURA MUNICIPAL DE [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"MUNIC[IÍ]PIO DE [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"GOVERNO DO ESTADO D[AEO][S]? [A-ZÀ-Ú][A-ZÀ-Ú \-]{1,50}",
        r"SECRETARIA[A-ZÀ-Ú \-]{1,40}D[AEO][S]?[A-ZÀ-Ú \-]{1,50}",
        r"TRIBUNAL DE [A-ZÀ-Ú][A-ZÀ-Ú \-]{1,50}",
        r"UNIVERSIDADE [A-ZÀ-Ú][A-ZÀ-Ú \-]{1,50}",
        r"INSTITUTO FEDERAL [A-ZÀ-Ú][A-ZÀ-Ú \-]{1,50}",
        r"MINIST[ÉE]RIO D[AEO][S]? [A-ZÀ-Ú][A-ZÀ-Ú \-]{1,50}",
        r"C[ÂA]MARA MUNICIPAL DE [A-ZÀ-Ú][A-ZÀ-Ú \-]{1,50}",
    ]
    texto_upper = texto.upper()
    # Considera o casamento mais à esquerda (mais próximo do início do
    # documento) entre TODOS os padrões, em vez de "primeiro padrão da lista
    # que casar em qualquer lugar" — evita pegar um trecho garbled lá pela
    # página 40 quando o cabeçalho real e limpo está na página 1-2.
    # Prefira identificadores institucionais específicos mesmo quando uma
    # frase genérica aparece algumas linhas antes (ex.: "Secretaria indicado
    # no item..."). Só depois use a heurística de ocorrência mais à esquerda.
    candidatos_prioritarios = [re.search(p, texto_upper) for p in padroes[:1]]
    candidatos_prioritarios = [m for m in candidatos_prioritarios if m]
    candidatos = candidatos_prioritarios or [m for p in padroes[1:] for m in [re.search(p, texto_upper)] if m]
    if candidatos:
        m = min(candidatos, key=lambda m: m.start())
        valor = texto[m.start():m.end()].title().strip()
        return valor, fonte_do_match(texto, offsets, m)
    return "Órgão não identificado", None


def extract_numero_processo(texto: str, offsets: list):
    m = re.search(
        r"PREG[ÃA]O\s*(ELETR[ÔO]NICO)?\s*(SRP)?\s*N[º°oO.\s]*[:\-]?\s*([\d]{1,5}\s*/\s*\d{4})",
        texto.upper(),
    )
    if m:
        valor = f"Pregão Eletrônico nº {m.group(3).replace(' ', '')}"
        return valor, fonte_do_match(texto, offsets, m)
    m = re.search(r"PROCESSO\s*(ADMINISTRATIVO)?\s*N[º°oO.\s]*[:\-]?\s*([\d./\-]{4,20})", texto.upper())
    if m:
        valor = f"Processo nº {m.group(2)}"
        return valor, fonte_do_match(texto, offsets, m)
    return "Não identificado", None


_OBJETO_STOP = (
    r"(?:\n\s*\n|\d\.\d\s|CL[ÁA]USULA|VALOR ESTIMADO|DA DOTA[ÇC][ÃA]O|"
    r"\n\s*DA\s+[A-ZÀ-Ú]{3,}[:\s])"
)
_OBJETO_VERBOS_TIPICOS = re.compile(
    r"^\s*(LOCA[ÇC][ÃA]O|CONTRATA[ÇC][ÃA]O|AQUISI[ÇC][ÃA]O|PRESTA[ÇC][ÃA]O|FORNECIMENTO)",
    re.IGNORECASE,
)


def extract_objeto(texto: str, offsets: list):
    # A palavra "objeto" costuma aparecer duas vezes perto uma da outra em
    # editais formais: primeiro como rótulo de um campo de formulário
    # ("Objeto da licitação/Codificação..."), depois como a frase real
    # ("Objeto: Locação de..."). Por isso pegamos TODAS as ocorrências e
    # preferimos a que começa com um verbo típico de objeto de licitação —
    # nunca a primeira ocorrência cega da palavra.
    # Cada ocorrência da palavra "OBJETO" (não só a primeira) é um ponto de
    # partida candidato — a 2ª ocorrência normalmente fica dentro do trecho
    # capturado pela 1ª, então isso não pode ser um único finditer global.
    candidatos = []
    for pos in re.finditer(r"OBJETO", texto, re.IGNORECASE):
        m = re.match(r"OBJETO[:\s\-]+(.{40,900}?)" + _OBJETO_STOP, texto[pos.start():], re.IGNORECASE | re.DOTALL)
        if m:
            candidatos.append((pos.start(), m))
    if not candidatos:
        return "Objeto não identificado — revisar edital manualmente.", None

    offset, m_local = next(
        ((offset, m) for offset, m in candidatos if _OBJETO_VERBOS_TIPICOS.search(m.group(1))),
        candidatos[0],
    )
    inicio, fim = offset + m_local.start(), offset + m_local.end()
    objeto = re.sub(r"\s+", " ", m_local.group(1)).strip(" .:-")
    fonte = {"pagina": pagina_do_offset(offsets, inicio), "trecho": _trecho(texto, inicio, fim)}
    return objeto[:700], fonte


def extract_prazo_contratual_meses(texto: str, offsets: list):
    padrao_contexto = re.compile(
        r"(vig[êe]ncia|prazo\s+de\s+execu[çc][ãa]o|prazo\s+contratual)[^.\n]{0,120}",
        re.IGNORECASE,
    )
    for m in padrao_contexto.finditer(texto):
        trecho_c = m.group(0)
        m_meses = re.search(r"(\d{1,3})\s*\(?[\wÀ-ú\s]*\)?\s*meses", trecho_c, re.IGNORECASE)
        if m_meses:
            return int(m_meses.group(1)), fonte_do_match(texto, offsets, m)
        m_dias = re.search(r"(\d{1,4})\s*\(?[\wÀ-ú\s]*\)?\s*dias", trecho_c, re.IGNORECASE)
        if m_dias:
            return max(1, round(int(m_dias.group(1)) / 30)), fonte_do_match(texto, offsets, m)
    m = re.search(r"(\d{1,3})\s*meses", texto, re.IGNORECASE)
    if m:
        return int(m.group(1)), fonte_do_match(texto, offsets, m)
    return 12, None


def _parse_valor_br(s: str) -> float:
    s = s.strip().replace("R$", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def extract_valor_estimado(texto: str, offsets: list):
    m_contexto = re.search(
        r"(valor\s+estimado|valor\s+global|valor\s+m[áa]ximo\s+admitido|valor\s+total\s+estimado)[^\n]{0,200}",
        texto,
        re.IGNORECASE,
    )
    if m_contexto:
        m_valor = re.search(r"R\$\s*([\d.,]+)", m_contexto.group(0))
        if m_valor:
            valor = _parse_valor_br(m_valor.group(1))
            if valor > 0:
                return valor, fonte_do_match(texto, offsets, m_contexto), True

    candidatos = list(re.finditer(r"R\$\s*([\d.,]+)", texto))
    melhor = None
    for m in candidatos:
        v = _parse_valor_br(m.group(1))
        if v > 100 and (melhor is None or v > melhor[1]):
            melhor = (m, v)
    if melhor:
        m, v = melhor
        return v, fonte_do_match(texto, offsets, m), False
    return 0.0, None, False


def detectar_categoria(descricao: str) -> str:
    desc = descricao.lower()
    for categoria, palavras in CATEGORIAS_VEICULO.items():
        if any(p in desc for p in palavras):
            return categoria
    return "nao_especificado"


def _maior_quantidade(bloco: str) -> int:
    candidatos = re.findall(r"QUANT(?:IDADE)?[:\.\s]*(\d{1,4})", bloco, re.IGNORECASE)
    candidatos += re.findall(r"(\d{1,4})\s*\(?[\wÀ-ú\s]*\)?\s*ve[íi]culos?", bloco, re.IGNORECASE)
    valores = [int(c) for c in candidatos if 0 < int(c) <= 500]
    return max(valores) if valores else 1


def extract_lotes(texto: str, offsets: list) -> list:
    """Extrai lotes da tabela de itens, evitando referências em cláusulas.

    A palavra ``lote`` também aparece em regras de habilitação, reserva de
    frota e textos-modelo. Um marcador só é considerado lote licitável quando
    estiver no cabeçalho de uma tabela que contenha participação, quantitativo
    e unidade de fornecimento. Se o documento não tiver essa estrutura, o
    fallback antigo é preservado, mas o resultado fica explicitamente marcado
    como revisão manual pela ausência de fonte estruturada.
    """
    todos = list(re.finditer(r"\bLOTE\s*(?:N[º°oO.]?\s*)?(\d{1,3})\b", texto, re.IGNORECASE))

    def eh_cabecalho_tabela(match) -> bool:
        janela = texto[match.start():match.start() + 700].lower()
        janela = unicodedata.normalize("NFD", janela).encode("ascii", "ignore").decode("ascii")
        janela = re.sub(r"\s+", " ", janela)
        formato_bahia = all(termo in janela for termo in ("participacao", "quantitativo")) and (
            "unidade de fornecimento" in janela or "(uf)" in janela
        )
        # Alguns editais usam cabeçalho compacto (UND/QTD/DESCRIÇÃO), sem a
        # coluna de participação. Ainda exigimos os três campos de tabela.
        formato_compacto = all(termo in janela for termo in ("qtd", "descri")) and (
            "und de medida" in janela or "unidade" in janela
        )
        return formato_bahia or formato_compacto

    estruturados = [m for m in todos if eh_cabecalho_tabela(m)]
    marcadores = estruturados or todos
    lotes = []

    if not marcadores:
        qtd = _maior_quantidade(texto)
        lotes.append({
            "numero": 1,
            "descricao": "Lote único (não segmentado no edital)",
            "quantidade": qtd,
            "categoria_veiculo": detectar_categoria(texto),
            "fonte": None,
        })
        return lotes

    for i, m in enumerate(marcadores):
        numero = int(m.group(1))
        inicio = m.end()
        fim = marcadores[i + 1].start() if i + 1 < len(marcadores) else min(len(texto), inicio + 3000)
        bloco = texto[inicio:fim]
        # Em PDFs, a tabela frequentemente vira uma única linha. A unidade
        # (UN/UND) seguida da quantidade é o sinal mais confiável nesse caso.
        qtd_tabela = re.search(r"\b(?:UN|UND|UNIDADE)\s+(\d{1,4})\b", bloco, re.IGNORECASE)
        if not qtd_tabela:
            # Layout compacto: a quantidade vem após a unidade, no fim da
            # linha que descreve o item (ex.: "Diária 4.880").
            qtd_tabela = re.search(r"\b(?:DI[ÁA]RIA|M[ÊE]S|SERVI[ÇC]O)\s+(\d{1,6})\b", bloco, re.IGNORECASE)
        qtd = int(qtd_tabela.group(1)) if qtd_tabela else _maior_quantidade(bloco)

        desc_fim = qtd_tabela.start() if qtd_tabela else min(len(bloco), 400)
        descricao_bruta = bloco[:desc_fim]
        # Remove os cabeçalhos repetidos, preservando a especificação do item.
        descricao_bruta = re.sub(
            r"^\s*(participa[çc][ãa]o.*?(?:\(uf\)|unidade de fornecimento).*?(?:descri[çc][ãa]o)?)",
            "", descricao_bruta, flags=re.IGNORECASE | re.DOTALL,
        )
        descricao = re.sub(r"\s+", " ", descricao_bruta).strip(" .:-")
        if len(descricao) < 10:
            descricao = f"Lote {numero} — especificação a conferir no TR"
        lotes.append({
            "numero": numero,
            "descricao": re.sub(r"\s+", " ", descricao)[:250],
            "quantidade": qtd,
            "categoria_veiculo": detectar_categoria(bloco),
            "fonte": fonte_do_match(texto, offsets, m),
            "estruturado": bool(estruturados),
        })

    vistos = set()
    unicos = []
    for l in lotes:
        if l["numero"] not in vistos:
            vistos.add(l["numero"])
            unicos.append(l)
    return unicos


def extract_all(paginas: list) -> dict:
    """Ponto de entrada do motor por regex. Recebe o texto já dividido por
    página (ver pdf_reader.extract_pages) e devolve os dados extraídos junto
    com um dicionário `fontes` para rastreabilidade."""
    texto = "\n".join(paginas)
    offsets = construir_indice_paginas(paginas)

    orgao, fonte_orgao = extract_orgao(texto, offsets)
    numero_processo, fonte_processo = extract_numero_processo(texto, offsets)
    objeto, fonte_objeto = extract_objeto(texto, offsets)
    prazo, fonte_prazo = extract_prazo_contratual_meses(texto, offsets)
    valor_estimado, fonte_valor, valor_explicito = extract_valor_estimado(texto, offsets)
    lotes = extract_lotes(texto, offsets)

    return {
        "orgao": orgao,
        "numero_processo": numero_processo,
        "objeto": objeto,
        "prazo_contratual_meses": prazo,
        "valor_estimado": valor_estimado,
        "valor_estimado_explicito": valor_explicito,
        "lotes": lotes,
        "qtd_lotes": len(lotes),
        "qtd_itens": sum(l["quantidade"] for l in lotes),
        "fontes": {
            "orgao": fonte_orgao,
            "numero_processo": fonte_processo,
            "objeto": fonte_objeto,
            "prazo_contratual_meses": fonte_prazo,
            "valor_estimado": fonte_valor,
        },
        "motor": "regex",
    }
