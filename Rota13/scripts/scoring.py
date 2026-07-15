"""Motor de pontuação, decisão (GO/GO COM RESSALVAS/NO GO), semáforo,
decisão por lote, confiança da extração, checklist prático e timeline.

Filosofia: todo número e toda cor no Dashboard precisa ter uma justificativa
em texto ao lado. Nada aparece "porque sim" — sempre há um motivo rastreável.
"""
import re

from . import vehicles

PESO_FINANCEIRO = 40
PESO_JURIDICO = 20
PESO_OPERACIONAL = 20
PESO_DOCUMENTACAO = 10
PESO_RISCOS = 10
SCORE_MAXIMO_TETO = 95  # o score nunca chega a 100 — sempre há incerteza residual


def _score_financeiro(consolidado: dict, prazo_meses: int) -> dict:
    motivos = []
    pontos = 0

    margem = consolidado.get("margem_media")
    if margem is None:
        motivos.append("Margem operacional não calculável com os dados disponíveis (0/20).")
    else:
        pct = margem * 100
        if margem >= 0.20:
            sub = 20
        elif margem >= 0.10:
            sub = 12
        elif margem >= 0:
            sub = 6
        else:
            sub = 0
        motivos.append(f"Margem operacional de {pct:.1f}% ({sub}/20 pontos).")
        pontos += sub

    payback = consolidado.get("payback_medio_meses")
    if payback is None:
        motivos.append("Payback não calculável com os dados disponíveis (0/10).")
    else:
        frac = (payback / prazo_meses) if prazo_meses else 1
        if frac <= 0.5:
            sub = 10
        elif frac <= 0.8:
            sub = 6
        else:
            sub = 2
        motivos.append(f"Payback de {payback:.1f} meses em um contrato de {prazo_meses} meses ({sub}/10 pontos).")
        pontos += sub

    tir = consolidado.get("tir_media_anual")
    if tir is None:
        motivos.append("TIR não calculável com os dados disponíveis (0/10).")
    else:
        pct = tir * 100
        if tir >= 0.25:
            sub = 10
        elif tir >= 0.12:
            sub = 6
        else:
            sub = 2
        motivos.append(f"TIR anual de {pct:.1f}% ({sub}/10 pontos).")
        pontos += sub

    return {"pontos": min(pontos, PESO_FINANCEIRO), "maximo": PESO_FINANCEIRO, "motivos": motivos}


def _score_juridico(achados_juridicos: list) -> dict:
    pontos = PESO_JURIDICO
    motivos = []
    altos = [a for a in achados_juridicos if a["severidade"] == "alta"]
    medios = [a for a in achados_juridicos if a["severidade"] == "media"]

    pontos -= len(altos) * 6
    pontos -= len(medios) * 3
    pontos = max(0, pontos)

    if not altos and not medios:
        motivos.append("Nenhum risco jurídico relevante identificado na análise automática.")
    else:
        motivos.append(f"{len(altos)} risco(s) de severidade alta e {len(medios)} de severidade média identificados.")
        for a in (altos + medios)[:4]:
            motivos.append(a["analise"].split(" — ")[0].split(". ")[0] + ".")

    return {"pontos": min(pontos, PESO_JURIDICO), "maximo": PESO_JURIDICO, "motivos": motivos}


def _score_operacional(lotes_resultado: list, achados_juridicos: list) -> dict:
    pontos = PESO_OPERACIONAL
    motivos = []

    total_lotes = len(lotes_resultado) or 1
    nao_especificados = sum(1 for l in lotes_resultado if l["categoria_veiculo"] == "nao_especificado")
    fracao_ok = 1 - (nao_especificados / total_lotes)
    perda_categoria = round((1 - fracao_ok) * 8)
    pontos -= perda_categoria
    if nao_especificados:
        motivos.append(f"{nao_especificados} de {total_lotes} lote(s) sem categoria de veículo identificada automaticamente.")
    else:
        motivos.append("Categoria de veículo identificada em todos os lotes.")

    entrega_curta = [a for a in achados_juridicos if "entrega" in a["analise"].lower() and a["severidade"] == "alta"]
    if entrega_curta:
        pontos -= 6
        motivos.append("Prazo de entrega identificado como curto para o porte da frota.")

    pontos = max(0, pontos)
    return {"pontos": min(pontos, PESO_OPERACIONAL), "maximo": PESO_OPERACIONAL, "motivos": motivos}


def _score_documentacao(dados: dict) -> dict:
    pontos = 0
    motivos = []
    checks = [
        ("orgao", dados["orgao"] != "Órgão não identificado", "Órgão licitante"),
        ("numero_processo", dados["numero_processo"] != "Não identificado", "Número do processo/pregão"),
        ("objeto", not dados["objeto"].startswith("Objeto não identificado"), "Objeto do edital"),
        ("valor_estimado", dados["valor_estimado"] > 0, "Valor estimado"),
        ("qtd_lotes", dados["qtd_lotes"] > 0, "Segmentação em lotes"),
    ]
    sub = PESO_DOCUMENTACAO / len(checks)
    for _, ok, label in checks:
        if ok:
            pontos += sub
        else:
            motivos.append(f"{label} não identificado no documento.")
    if not motivos:
        motivos.append("Todos os campos-chave do edital foram identificados no documento.")
    return {"pontos": round(min(pontos, PESO_DOCUMENTACAO), 1), "maximo": PESO_DOCUMENTACAO, "motivos": motivos}


def _score_riscos(lotes_resultado: list) -> dict:
    total_alertas = sum(len(l["alertas"]) for l in lotes_resultado)
    pontos = max(0, PESO_RISCOS - total_alertas * 2)
    if total_alertas == 0:
        motivos = ["Nenhum alerta identificado nos lotes."]
    else:
        motivos = [f"{total_alertas} alerta(s) identificado(s) somando todos os lotes."]
    return {"pontos": min(pontos, PESO_RISCOS), "maximo": PESO_RISCOS, "motivos": motivos}


def compute_score(dados: dict, lotes_resultado: list, consolidado: dict,
                   achados_juridicos: list, prazo_meses: int) -> dict:
    categorias = {
        "financeiro": _score_financeiro(consolidado, prazo_meses),
        "juridico": _score_juridico(achados_juridicos),
        "operacional": _score_operacional(lotes_resultado, achados_juridicos),
        "documentacao": _score_documentacao(dados),
        "riscos": _score_riscos(lotes_resultado),
    }
    soma = sum(c["pontos"] for c in categorias.values())
    total = round(min(soma, SCORE_MAXIMO_TETO), 1)
    return {"total": total, "categorias": categorias}


def decisao_go_no_go(score: dict, consolidado: dict, bloqueios: list = None) -> dict:
    """Emite recomendação somente quando os dados mínimos foram confirmados.

    Um score calculado sobre lotes ou preços incertos parece preciso, mas pode
    induzir uma proposta errada. Nesses casos a saída correta é pedir
    validação humana, não forçar GO/NO GO.
    """
    bloqueios = bloqueios or []
    if bloqueios:
        return {
            "decisao": "ANÁLISE PENDENTE",
            "motivos": bloqueios,
            "bloqueada": True,
        }

    total = score["total"]
    cat = score["categorias"]
    margem = consolidado.get("margem_media")

    motivos = []
    for nome, label in [("financeiro", "Financeiro"), ("juridico", "Jurídico"),
                         ("operacional", "Operacional"), ("riscos", "Riscos")]:
        c = cat[nome]
        fracao = c["pontos"] / c["maximo"] if c["maximo"] else 0
        if fracao < 0.5:
            motivos.append(f"{label} abaixo do esperado ({c['pontos']:.0f}/{c['maximo']} pontos).")

    prejuizo = margem is not None and margem < 0

    if prejuizo:
        decisao = "NO GO"
        motivos.insert(0, "Margem operacional negativa nas premissas atuais — o contrato dá prejuízo.")
    elif total < 40:
        decisao = "NO GO"
    elif total >= 70 and not motivos:
        decisao = "GO"
        motivos = ["Indicadores financeiros, jurídicos, operacionais e de risco dentro do esperado."]
    else:
        decisao = "GO COM RESSALVAS"
        if not motivos:
            motivos = ["Score consolidado moderado — recomenda-se revisão pontual antes de decidir."]

    return {"decisao": decisao, "motivos": motivos, "bloqueada": False}


def _cor(fracao: float) -> str:
    if fracao >= 0.7:
        return "verde"
    if fracao >= 0.4:
        return "amarelo"
    return "vermelho"


def compute_semaforo(score: dict, prazo_entrega_info: dict) -> dict:
    cat = score["categorias"]
    painel = {}
    for chave, label in [("financeiro", "Financeiro"), ("juridico", "Jurídico"),
                          ("operacional", "Operacional"), ("documentacao", "Documentação")]:
        c = cat[chave]
        fracao = c["pontos"] / c["maximo"] if c["maximo"] else 0
        painel[chave] = {
            "label": label,
            "cor": _cor(fracao),
            "justificativa": c["motivos"][0] if c["motivos"] else "",
        }

    painel["entrega"] = {
        "label": "Entrega",
        "cor": prazo_entrega_info["cor"],
        "justificativa": prazo_entrega_info["justificativa"],
    }
    return painel


def avaliar_prazo_entrega(paginas: list) -> dict:
    """Avalia o prazo de entrega independentemente de ele ser um risco ou não —
    diferente de analisar_riscos_juridicos, que só reporta quando é curto demais."""
    texto = "\n".join(paginas)
    m = re.search(r"prazo\s+de\s+entrega[^.\n]{0,60}?(\d{1,3})\s*dias", texto, re.IGNORECASE)
    if not m:
        return {"cor": "amarelo", "justificativa": "Prazo de entrega não identificado no texto — confirmar diretamente no edital."}
    dias = int(m.group(1))
    if dias < 15:
        return {"cor": "vermelho",
                "justificativa": f"Prazo de entrega de {dias} dias é curto para o porte da frota — avalie a viabilidade operacional."}
    return {"cor": "verde",
            "justificativa": f"Prazo de entrega de {dias} dias identificado no edital — compatível com aquisição/adaptação de frota."}


def decisao_por_lote(lote_resultado: dict) -> dict:
    fin = lote_resultado["financeiro"]
    margem = fin["margem_estimada"]
    risco = fin["risco"]
    motivos = []

    if margem is None:
        decisao = "TALVEZ"
        motivos.append("Margem não calculável com os dados disponíveis — avaliar manualmente.")
    elif margem < 0:
        decisao = "NÃO"
        motivos.append(f"Margem operacional negativa ({margem*100:.1f}%) nas premissas atuais.")
    elif margem >= 0.15 and risco == "Baixo":
        decisao = "SIM"
        motivos.append(f"Margem de {margem*100:.1f}% com risco classificado como Baixo.")
    elif margem >= 0.06 and risco != "Alto":
        decisao = "TALVEZ"
        motivos.append(f"Margem de {margem*100:.1f}% com risco {risco} — viável, mas vale revisar premissas.")
    else:
        decisao = "NÃO"
        motivos.append(f"Margem de {margem*100:.1f}% com risco {risco} — pouco atrativo nas premissas atuais.")

    if fin["payback_meses"] is None:
        motivos.append("Payback não calculável.")
    if lote_resultado["alertas"] and lote_resultado["alertas"][0] != "Nenhum alerta identificado.":
        motivos.append(f"{len(lote_resultado['alertas'])} alerta(s) identificado(s) neste lote.")

    return {"decisao": decisao, "motivos": motivos}


def score_lote(lote_resultado: dict, prazo_meses: int) -> int:
    """Score simplificado (0-100, nunca 100) de um lote individual, usado nos
    cards da seção Análise por Lote."""
    fin = lote_resultado["financeiro"]
    pontos = 0

    margem = fin["margem_estimada"]
    if margem is not None:
        pontos += max(0, min(50, (margem / 0.25) * 50))

    payback = fin["payback_meses"]
    if payback is not None and prazo_meses:
        frac = payback / prazo_meses
        pontos += 30 if frac <= 0.5 else 15 if frac <= 0.8 else 5

    pontos += {"Baixo": 20, "Médio": 10, "Alto": 0}.get(fin["risco"], 0)

    return round(min(pontos, 95))


def semaforo_lote(decisao_participar: dict) -> str:
    return {"SIM": "verde", "TALVEZ": "amarelo", "NÃO": "vermelho"}.get(decisao_participar["decisao"], "amarelo")


CAMPOS_CHAVE = [
    ("orgao", "Órgão licitante"),
    ("numero_processo", "Número do processo/pregão"),
    ("objeto", "Objeto do edital"),
    ("prazo_contratual_meses", "Prazo contratual"),
    ("valor_estimado", "Valor estimado"),
]

VALORES_PADRAO_NAO_ENCONTRADO = {
    "orgao": "Órgão não identificado",
    "numero_processo": "Não identificado",
}


def confianca_extracao(dados: dict) -> dict:
    encontrados, pendentes, revisados = [], [], []
    fontes = dados.get("fontes", {})

    for campo, label in CAMPOS_CHAVE:
        valor = dados.get(campo)
        vazio = (
            valor in ("Órgão não identificado", "Não identificado") or
            (campo == "objeto" and str(valor).startswith("Objeto não identificado")) or
            (campo == "valor_estimado" and not valor)
        )
        if vazio:
            pendentes.append(label)
        elif fontes.get(campo) is None:
            revisados.append(label)
            encontrados.append(label)
        else:
            encontrados.append(label)

    if dados.get("motor") == "regex" and not dados.get("valor_estimado_explicito", True):
        if "Valor estimado" not in revisados:
            revisados.append("Valor estimado (não veio de um rótulo explícito no texto)")

    base = len(encontrados) / len(CAMPOS_CHAVE) * 100
    penalidade = len(revisados) * 5
    percentual = max(0, min(100, round(base - penalidade)))

    return {
        "percentual": percentual,
        "campos_encontrados": encontrados,
        "campos_pendentes": pendentes,
        "campos_revisados": revisados,
        "motor": dados.get("motor", "regex"),
    }


def checklist_pratico(conn, lotes_resultado: list, achados_juridicos: list, confianca: dict) -> list:
    itens = [
        "Confirmar franquia de KM e valor do KM excedente diretamente no edital",
        "Confirmar exigências específicas de seguro (cobertura, franquia)",
        "Conferir prazo de entrega inicial da frota",
    ]

    for lote in lotes_resultado:
        marcas = vehicles.marcas_por_categoria(conn, lote["categoria_veiculo"], limite=2)
        if marcas:
            itens.append(f"Solicitar cotação para o Lote {lote['numero']} ({lote['categoria_veiculo']}): {', '.join(marcas)}")

    for a in achados_juridicos:
        if a["severidade"] in ("media", "alta"):
            resumo = a["analise"].split(" — ")[0].split(". ")[0]
            if resumo not in itens:
                itens.append(resumo)

    for pendente in confianca["campos_pendentes"]:
        itens.append(f"Confirmar manualmente no PDF: {pendente}")

    # remove duplicados preservando ordem
    vistos = set()
    unicos = []
    for i in itens:
        if i not in vistos:
            vistos.add(i)
            unicos.append(i)
    return unicos


TIMELINE_FASES = [
    ("publicacao", "Publicação do edital", r"public(a[çc][ãa]o|ado)[^.\n]{0,60}"),
    ("esclarecimentos", "Pedidos de esclarecimento", r"esclarecimentos?[^.\n]{0,80}at[ée][^.\n]{0,40}"),
    ("impugnacoes", "Impugnações", r"impugna[çc][ãa]o[^.\n]{0,80}at[ée][^.\n]{0,40}"),
    ("sessao", "Sessão pública", r"sess[ãa]o\s+p[úu]blica[^.\n]{0,80}"),
    ("homologacao", "Homologação", r"homologa[çc][ãa]o[^.\n]{0,80}"),
    ("assinatura", "Assinatura do contrato", r"assinatura\s+do\s+contrato[^.\n]{0,80}"),
    ("entrega", "Entrega da frota", r"prazo\s+de\s+entrega[^.\n]{0,80}"),
    ("reajuste", "Reajuste contratual", r"reajust(e|amento)[^.\n]{0,80}"),
    ("encerramento", "Encerramento do contrato", r"vig[êe]ncia[^.\n]{0,80}"),
]


def resumo_narrativo(score: dict, decisao: dict, consolidado: dict,
                      achados_juridicos: list, lotes_resultado: list) -> dict:
    """Gera o resumo executivo em linguagem direta: pontos fortes/fracos, riscos,
    oportunidades, decisões necessárias e ações recomendadas."""
    cat = score["categorias"]
    pontos_fortes, pontos_fracos, riscos, oportunidades = [], [], [], []

    margem = consolidado.get("margem_media")
    if margem is not None and margem >= 0.15:
        pontos_fortes.append(f"Margem operacional saudável ({margem*100:.1f}%).")
    elif margem is not None and margem < 0.06:
        pontos_fracos.append(f"Margem operacional apertada ou negativa ({margem*100:.1f}%).")

    payback = consolidado.get("payback_medio_meses")
    if payback is not None:
        pontos_fortes.append(f"Payback estimado em {payback:.1f} meses.") if payback <= 24 else \
            pontos_fracos.append(f"Payback longo, {payback:.1f} meses.")

    if cat["juridico"]["pontos"] >= PESO_JURIDICO * 0.8:
        pontos_fortes.append("Poucos riscos jurídicos identificados no texto do edital.")
    else:
        riscos.append("Riscos jurídicos relevantes identificados — ver seção Jurídico.")

    if cat["documentacao"]["pontos"] < PESO_DOCUMENTACAO * 0.6:
        pontos_fracos.append("Vários campos do edital não foram identificados automaticamente — exige leitura manual.")

    lotes_sim = [l for l in lotes_resultado if l.get("decisao_participar", {}).get("decisao") == "SIM"]
    if lotes_sim:
        oportunidades.append(f"{len(lotes_sim)} de {len(lotes_resultado)} lote(s) com recomendação SIM para participar.")

    altos = [a for a in achados_juridicos if a["severidade"] == "alta"]
    for a in altos[:3]:
        riscos.append(a["analise"].split(" — ")[0].split(". ")[0] + ".")

    decisoes_necessarias = [
        "Confirmar premissas financeiras (desconto de montadora, taxa de juros) com fornecedores reais antes de propor preço.",
    ]
    if decisao["decisao"] != "GO":
        decisoes_necessarias.append("Avaliar se as ressalvas identificadas inviabilizam a participação.")

    acoes_recomendadas = ["Revisar o checklist prático (seção \"O que preciso fazer\") antes da sessão pública."]
    if riscos:
        acoes_recomendadas.append("Considerar pedido de esclarecimento sobre os pontos jurídicos levantados.")

    return {
        "pontos_fortes": pontos_fortes or ["Nenhum ponto forte destacado pela análise automática."],
        "pontos_fracos": pontos_fracos or ["Nenhum ponto fraco relevante identificado."],
        "riscos": riscos or ["Nenhum risco crítico identificado pela análise automática."],
        "oportunidades": oportunidades or ["Avaliar cada lote individualmente na seção Análise por Lote."],
        "decisoes_necessarias": decisoes_necessarias,
        "acoes_recomendadas": acoes_recomendadas,
    }


def construir_timeline(paginas: list) -> list:
    texto = "\n".join(paginas)
    linha_do_tempo = []
    for chave, label, padrao in TIMELINE_FASES:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            info = re.sub(r"\s+", " ", m.group(0)).strip()
            linha_do_tempo.append({"fase": label, "info": info[:180], "identificado": True})
        else:
            linha_do_tempo.append({"fase": label, "info": "Não identificado no edital — conferir manualmente.", "identificado": False})
    return linha_do_tempo
