"""Utilitários de rastreabilidade: mapear uma posição no texto extraído do PDF
de volta para "página X, trecho: ...". Usado para que toda informação exibida
no Dashboard possa ser conferida na fonte, em vez de exigir confiança cega.
"""
import bisect
import re


def construir_indice_paginas(paginas: list) -> list:
    """Offset (no texto concatenado por '\\n'.join(paginas)) em que cada página começa."""
    offsets = []
    cursor = 0
    for pagina in paginas:
        offsets.append(cursor)
        cursor += len(pagina) + 1  # +1 pelo '\n' usado na concatenação
    return offsets


def pagina_do_offset(offsets: list, offset: int) -> int:
    idx = bisect.bisect_right(offsets, offset) - 1
    return max(1, idx + 1)


def trecho(texto: str, inicio: int, fim: int, contexto: int = 60) -> str:
    ini = max(0, inicio - contexto)
    fi = min(len(texto), fim + contexto)
    s = texto[ini:fi].strip()
    return re.sub(r"\s+", " ", s)


def fonte_do_match(texto: str, offsets: list, match) -> dict:
    """Constrói {pagina, trecho} a partir de um re.Match encontrado no texto concatenado."""
    return {
        "pagina": pagina_do_offset(offsets, match.start()),
        "trecho": trecho(texto, match.start(), match.end()),
    }


def _normalizar(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def verificar_citacao(paginas: list, pagina: int, trecho_citado: str) -> bool:
    """Confere se um trecho citado (ex.: por uma IA) realmente aparece na página
    informada — evita apresentar uma citação inventada como se fosse real.
    Aceita correspondência parcial (a IA pode citar com pequenas variações)."""
    if not (1 <= pagina <= len(paginas)) or not trecho_citado:
        return False
    texto_pagina = _normalizar(paginas[pagina - 1])
    alvo = _normalizar(trecho_citado)
    if len(alvo) < 8:
        return False
    if alvo[:80] in texto_pagina:
        return True
    # correspondência aproximada: fração de palavras (>3 letras) do trecho citado
    # que realmente aparece na página
    palavras = [w for w in re.findall(r"\w+", alvo) if len(w) > 3]
    if not palavras:
        return False
    encontradas = sum(1 for w in palavras if w in texto_pagina)
    return (encontradas / len(palavras)) >= 0.6
