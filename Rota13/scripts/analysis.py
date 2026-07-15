"""Monta a estrutura completa de análise (analise.json) combinando extração,
base de conhecimento, base de veículos, motor financeiro (DRE) e motor de
pontuação/decisão. Este é o orquestrador central da Sprint 2: nenhum número
chega ao Dashboard sem ter passado por aqui com sua justificativa.
"""
from . import financial
from . import knowledge as kb
from . import legal_analysis
from . import scoring
from . import vehicles as veh

PARAMS_SIMULACAO_PADRAO = financial.PARAMS_PADRAO


def _alertas_lote(lote: dict, fin: dict, prazo_meses: int) -> list:
    alertas = list(fin.get("avisos", []))
    if lote["categoria_veiculo"] == "nao_especificado":
        alertas.append("Categoria de veículo não identificada automaticamente — revisar descrição do lote.")
    if lote["quantidade"] <= 1:
        alertas.append("Quantidade do lote pode não ter sido extraída corretamente — conferir no PDF original.")
    return alertas or ["Nenhum alerta identificado."]


def _pendencias_lote(lote: dict) -> list:
    return [
        "Confirmar franquia de KM e valor do excedente para este lote",
        "Confirmar prazo de entrega inicial da frota deste lote",
    ]


def build_analise(arquivo_pdf: str, paginas: list, dados: dict, conn) -> dict:
    prazo_meses = dados["prazo_contratual_meses"]
    valor_estimado_total = dados["valor_estimado"]
    valor_explicito = dados.get("valor_estimado_explicito", True)
    qtd_itens_total = max(1, dados["qtd_itens"])

    lotes_resultado = []
    for lote in dados["lotes"]:
        veiculo_ref = veh.veiculo_referencia(conn, lote["categoria_veiculo"])
        proporcao = lote["quantidade"] / qtd_itens_total
        valor_lote_estimado = valor_estimado_total * proporcao

        fin = financial.compute_lote_financials(
            lote, veiculo_ref, prazo_meses, valor_lote_estimado, valor_explicito
        )
        # fin já usa o cenário "Moderado" (6% da FIPE/mês) como padrão quando o
        # edital não informa receita — aqui calculamos os outros 2 cenários
        # (5%/7%) só para exibição lado a lado, nunca escondendo a incerteza.
        cenarios_receita = None if valor_explicito else financial.compute_cenarios_lote(lote, veiculo_ref, prazo_meses)

        lote_resultado = {
            **lote,
            "veiculo_referencia": veiculo_ref,
            "financeiro": fin,
            "cenarios_receita": cenarios_receita,
            "alertas": _alertas_lote(lote, fin, prazo_meses),
            "pendencias": _pendencias_lote(lote),
        }
        lote_resultado["decisao_participar"] = scoring.decisao_por_lote(lote_resultado)
        lote_resultado["score"] = scoring.score_lote(lote_resultado, prazo_meses)
        lote_resultado["semaforo"] = scoring.semaforo_lote(lote_resultado["decisao_participar"])
        lotes_resultado.append(lote_resultado)

    consolidado = financial.compute_consolidado([l["financeiro"] for l in lotes_resultado])

    achados_juridicos = legal_analysis.analisar_riscos_juridicos(paginas)
    juridico_kb = kb.match_juridico(conn, "\n".join(paginas))

    score = scoring.compute_score(dados, lotes_resultado, consolidado, achados_juridicos, prazo_meses)
    decisao = scoring.decisao_go_no_go(score, consolidado)
    prazo_entrega_info = scoring.avaliar_prazo_entrega(paginas)
    semaforo = scoring.compute_semaforo(score, prazo_entrega_info)
    confianca = scoring.confianca_extracao(dados)
    checklist = scoring.checklist_pratico(conn, lotes_resultado, achados_juridicos, confianca)
    timeline = scoring.construir_timeline(paginas)
    resumo_narrativo = scoring.resumo_narrativo(score, decisao, consolidado, achados_juridicos, lotes_resultado)

    operacional = {
        "veiculos": [
            {
                "lote": l["numero"],
                "categoria": l["categoria_veiculo"],
                "referencia": l["veiculo_referencia"],
                "quantidade": l["quantidade"],
                "valor_residual_unitario": l["financeiro"]["valor_residual_unitario"],
            }
            for l in lotes_resultado
        ],
        "prazo_entrega": prazo_entrega_info["justificativa"],
        "manutencao": "Preventiva conforme manual do fabricante + corretiva sob demanda, sem custo adicional ao órgão.",
        "seguro": "Cobertura compreensiva (colisão, roubo/furto, incêndio) + RCF terceiros, conforme exigência do edital.",
        "documentacao": ["CRLV em dia", "Licenciamento anual", "IPVA quitado", "Comprovante de seguro vigente"],
        "exigencias": [
            "Frota nova ou com idade máxima conforme edital",
            "Substituição de veículo em pane dentro do prazo definido",
            "Identificação visual conforme exigência do órgão (se aplicável)",
        ],
        "checklist_operacional": [
            "Confirmar disponibilidade de frota compatível com o prazo de entrega exigido",
            "Confirmar capacidade de manutenção/suporte na região do órgão",
            "Confirmar cobertura de seguro compatível com a exigência do edital",
            "Confirmar documentação da frota (CRLV, licenciamento, IPVA) antes da entrega",
        ],
    }

    juridico = {
        **juridico_kb,
        "achados": achados_juridicos,
    }

    resumo_executivo = {
        "decisao": decisao["decisao"],
        "motivos_decisao": decisao["motivos"],
        "score_geral": score["total"],
        "score_categorias": score["categorias"],
        "orgao": dados["orgao"],
        "numero_processo": dados["numero_processo"],
        "objeto": dados["objeto"],
        "prazo_contratual_meses": prazo_meses,
        "valor_estimado": valor_estimado_total,
        "valor_estimado_explicito": valor_explicito,
        "qtd_lotes": dados["qtd_lotes"],
        "qtd_itens": qtd_itens_total,
        **resumo_narrativo,
    }

    return {
        "meta": {
            "arquivo_pdf": arquivo_pdf,
            "sistema": "Rota13 Bid Intelligence — Sprint 2",
        },
        "resumo_executivo": resumo_executivo,
        "semaforo": semaforo,
        "lotes": lotes_resultado,
        "financeiro": consolidado,
        "juridico": juridico,
        "operacional": operacional,
        "checklist_pratico": checklist,
        "timeline": timeline,
        "confianca_extracao": confianca,
        "market_intelligence": {
            "disponivel": False,
            "mensagem": "Benchmark de Mercado disponível na Versão 2.",
        },
        "simulacao_base": {
            "parametros_padrao": PARAMS_SIMULACAO_PADRAO,
            "prazo_contratual_meses": prazo_meses,
        },
    }
