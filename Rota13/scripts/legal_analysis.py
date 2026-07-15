"""Análise jurídica heurística (determinística, sem IA) sobre o texto do edital.

Em vez de só listar leis/acórdãos genéricos, procura padrões de risco
específicos no próprio texto do edital e gera frases de análise, sempre
citando página + trecho (rastreabilidade) — nunca uma alegação solta.
"""
import re

from .citations import construir_indice_paginas, fonte_do_match


def _achar(texto, offsets, padrao, flags=re.IGNORECASE):
    return re.search(padrao, texto, flags)


def analisar_riscos_juridicos(paginas: list) -> list:
    """Retorna lista de achados: {analise, severidade, pagina, trecho}."""
    texto = "\n".join(paginas)
    offsets = construir_indice_paginas(paginas)
    achados = []

    # 1) Franquia / quilometragem
    tem_km = _achar(texto, offsets, r"franquia\s+de\s+(km|quilomet)")
    km_livre = _achar(texto, offsets, r"(?:quilometragem|km)\s+livre|livre\s+de\s+quilometragem")
    if km_livre:
        achados.append({
            "analise": "Quilometragem livre identificada no edital — o custo de uso não tem teto contratual; "
                       "precifique desgaste, manutenção e pneus para um cenário de uso intenso.",
            "severidade": "media",
            **fonte_do_match(texto, offsets, km_livre),
        })
    elif tem_km:
        achados.append({
            "analise": "Franquia de quilometragem mencionada no edital — confirme o valor exato "
                       "e o custo do KM excedente antes de precificar a proposta.",
            "severidade": "baixa",
            **fonte_do_match(texto, offsets, tem_km),
        })
    else:
        achados.append({
            "analise": "Não foi localizada menção explícita a franquia de quilometragem. "
                       "Isso pode indicar \"KM livre\" (risco de sobrecusto) ou apenas ausência de "
                       "detalhamento no texto disponível — recomenda-se confirmar diretamente no edital.",
            "severidade": "media",
            "pagina": None, "trecho": None,
        })

    # 2) Reajuste / reequilíbrio
    m_reajuste = _achar(texto, offsets, r"reajust(e|amento)|reequil[íi]brio\s+econ[ôo]mico")
    if not m_reajuste:
        achados.append({
            "analise": "Não foi localizada cláusula de reajuste ou reequilíbrio econômico-financeiro "
                       "no texto disponível. Em contratos acima de 12 meses, a ausência desse mecanismo "
                       "é um risco financeiro relevante (custos podem subir sem repasse contratual).",
            "severidade": "alta",
            "pagina": None, "trecho": None,
        })
    else:
        achados.append({
            "analise": "Cláusula de reajuste/reequilíbrio identificada — confira o índice usado "
                       "(ex.: IPCA, IGP-M) e a periodicidade.",
            "severidade": "baixa",
            **fonte_do_match(texto, offsets, m_reajuste),
        })

    # 3) Multa elevada
    m_multa = _achar(texto, offsets, r"multa[^.\n]{0,80}?(\d{1,2})\s*%")
    if m_multa:
        pct = int(m_multa.group(1))
        if pct >= 15:
            achados.append({
                "analise": f"Percentual de multa identificado ({pct}%) é elevado — avalie o impacto "
                           f"financeiro em cenários de descumprimento antes de propor preço agressivo.",
                "severidade": "media",
                **fonte_do_match(texto, offsets, m_multa),
            })

    # 4) Garantia contratual elevada
    m_garantia = _achar(texto, offsets, r"garantia\s+contratual[^.\n]{0,80}?(\d{1,2})\s*%")
    if m_garantia:
        pct = int(m_garantia.group(1))
        if pct > 5:
            achados.append({
                "analise": f"Garantia contratual de {pct}% está acima do limite usual de 5% "
                           f"(art. 96-98 da Lei 14.133/2021) — pode indicar erro de digitação no "
                           f"edital ou justificar pedido de esclarecimento.",
                "severidade": "media",
                **fonte_do_match(texto, offsets, m_garantia),
            })

    # 5) Exigência de balanço / capital social (afeta habilitação)
    m_balanco = _achar(texto, offsets, r"balan[çc]o\s+patrimonial|capital\s+social\s+m[íi]nimo|patrim[ôo]nio\s+l[íi]quido")
    if m_balanco:
        achados.append({
            "analise": "Edital exige comprovação de balanço patrimonial/capital social/patrimônio "
                       "líquido mínimo para habilitação — confirme se a empresa atende ao requisito "
                       "antes de investir tempo na proposta.",
            "severidade": "media",
            **fonte_do_match(texto, offsets, m_balanco),
        })

    # 6) Prazo de entrega muito curto
    m_entrega = _achar(texto, offsets, r"prazo\s+de\s+entrega[^.\n]{0,60}?(\d{1,3})\s*dias")
    if m_entrega:
        dias = int(m_entrega.group(1))
        if dias < 15:
            achados.append({
                "analise": f"Prazo de entrega de {dias} dias é bastante curto para aquisição/adaptação "
                           f"de frota — avalie a viabilidade operacional antes de participar.",
                "severidade": "alta",
                **fonte_do_match(texto, offsets, m_entrega),
            })

    # 7) Possível direcionamento de marca (marca citada sem "similar"/"equivalente" por perto)
    marcas = ["chevrolet", "volkswagen", "fiat", "toyota", "renault", "ford", "jeep", "hyundai", "honda"]
    for marca in marcas:
        m_marca = re.search(rf"\b{marca}\b", texto, re.IGNORECASE)
        if m_marca:
            janela = texto[max(0, m_marca.start() - 100):m_marca.end() + 100].lower()
            if "similar" not in janela and "equivalente" not in janela and "ou de qualidade" not in janela:
                achados.append({
                    "analise": f"A marca \"{marca.title()}\" é citada no edital sem termo de equivalência "
                               f"próximo (\"similar\", \"equivalente\") — pode configurar direcionamento "
                               f"de marca, o que é vedado sem justificativa técnica (passível de pedido "
                               f"de esclarecimento ou impugnação).",
                    "severidade": "media",
                    **fonte_do_match(texto, offsets, m_marca),
                })
            break  # reporta só a primeira ocorrência para não poluir a análise

    return achados


def itens_para_checklist_juridico(paginas: list) -> list:
    """Itens práticos de checklist derivados da análise de risco."""
    achados = analisar_riscos_juridicos(paginas)
    itens = []
    for a in achados:
        if a["severidade"] in ("media", "alta"):
            itens.append(a["analise"].split(" — ")[0].split(". ")[0])
    return itens
