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

from .citations import construir_indice_paginas, fonte_do_match

CATEGORIAS_VEICULO = {
    "hatch": ["hatch", "popular", "compacto"],
    "sedan": ["sedan", "sedã"],
    "suv": ["suv", "utilitário esportivo"],
    "pickup": ["pick-up", "pickup", "caminhonete", "cabine dupla"],
    "van": ["van", "utilitário de carga", "furgão"],
    "onibus": ["ônibus", "micro-ônibus", "microônibus"],
    "caminhao": ["caminhão", "caminhao", "basculante", "baú"],
    "ambulancia": ["ambulância", "ambulancia"],
}


def _primeiras_linhas(texto, n=60):
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    return linhas[:n]


def extract_orgao(texto: str, offsets: list):
    # [^\S\n] = espaço/tab mas nunca quebra de linha, para não engolir o
    # cabeçalho inteiro do edital quando várias linhas seguidas estão em maiúsculas.
    padroes = [
        r"PREFEITURA MUNICIPAL DE [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"MUNIC[IÍ]PIO DE [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"GOVERNO DO ESTADO D[EO] [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"SECRETARIA[A-ZÀ-Ú \-]+DE[A-ZÀ-Ú \-]+",
        r"TRIBUNAL DE [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"UNIVERSIDADE [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"INSTITUTO FEDERAL [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"MINIST[ÉE]RIO D[AO] [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
        r"C[ÂA]MARA MUNICIPAL DE [A-ZÀ-Ú][A-ZÀ-Ú \-]+",
    ]
    texto_upper = texto.upper()
    for p in padroes:
        m = re.search(p, texto_upper)
        if m:
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


def extract_objeto(texto: str, offsets: list):
    m = re.search(
        r"OBJETO[:\s\-]+(.{40,900}?)"
        r"(?:\n\s*\n|\d\.\d\s|CL[ÁA]USULA|VALOR ESTIMADO|DA DOTA[ÇC][ÃA]O|"
        r"\n\s*DA\s+[A-ZÀ-Ú]{3,}[:\s])",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        objeto = re.sub(r"\s+", " ", m.group(1)).strip(" .:-")
        return objeto[:700], fonte_do_match(texto, offsets, m)
    return "Objeto não identificado — revisar edital manualmente.", None


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
    """Divide o texto em blocos de LOTE e extrai dados básicos de cada um, com fonte."""
    marcadores = list(re.finditer(r"\bLOTE\s*(?:N[º°oO.]?\s*)?(\d{1,3})\b", texto, re.IGNORECASE))
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
        descricao_m = re.search(r"([^\n]{10,250})", bloco)
        descricao = descricao_m.group(1).strip() if descricao_m else f"Lote {numero}"
        qtd = _maior_quantidade(bloco)
        lotes.append({
            "numero": numero,
            "descricao": re.sub(r"\s+", " ", descricao)[:250],
            "quantidade": qtd,
            "categoria_veiculo": detectar_categoria(bloco),
            "fonte": fonte_do_match(texto, offsets, m),
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
