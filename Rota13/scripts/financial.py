"""Motor financeiro — estrutura de DRE (Demonstrativo de Resultado).

Todo indicador (ROI, Payback, TIR, VPL, Margem) é calculado SOBRE O LUCRO
(fluxo de caixa líquido), nunca sobre a receita bruta. A cadeia de cálculo é:

    Receita Bruta
    (-) Tributos
    (-) Seguro
    (-) Manutenção
    (-) Pneus
    (-) Administração
    (-) Financeiro (parcela do financiamento)
    (-) Depreciação
    (-) Custos Operacionais
    =  Lucro Operacional

ROI/Payback/TIR/VPL usam o FLUXO DE CAIXA (Lucro Operacional + Depreciação,
já que depreciação é despesa contábil, não desembolso). Margem usa o Lucro
Operacional (contábil) sobre a Receita Bruta.

Quando não há dados suficientes para um cálculo confiável, o indicador é
retornado como None junto com um aviso em `avisos` — o Dashboard deve exibir
"Indicador não calculado por falta de informações" em vez de um número.
"""

PARAMS_PADRAO = {
    "desconto_montadora": 0.15,        # mínimo de 15% de desconto sobre a FIPE na compra (piso de negociação)
    "entrada_pct": 0.0,                # premissa: 100% financiado pelo banco, sem entrada própria
    "taxa_juros_am": 0.015,            # 1,5% a.m. no financiamento
    "prazo_financiamento_meses": 48,   # prazo comum de financiamento de veículos no Brasil; pode ser maior
                                        # que o prazo do contrato — nesse caso o aviso de saldo devedor final avisa
    "seguro_pct_am": 0.0035,           # 0,35% a.m. do valor do veículo
    "manutencao_mensal": None,         # None = usa tabela por categoria
    "pneus_mensal": None,              # None = usa tabela por categoria
    "tributos_pct": 0.12,              # tributação simplificada sobre receita bruta (12% flat)
    "administracao_pct": 0.05,         # overhead administrativo sobre receita bruta
    "custos_operacionais_mensal": 80.0,  # rastreamento/GPS, documentação, etc. (por veículo)
    "valor_residual_pct": None,        # None = calcula pela curva de depreciação padrão (ver valor_residual_padrao)
    "receita_pct_fipe_am": 0.06,       # usado só quando o edital NÃO tem valor estimado explícito — sobre 100% da FIPE
    "meses_capital_giro": 2,           # reserva de caixa sugerida, em meses de custo operacional
}

# Quando o edital não informa receita/locação, mostramos 3 cenários lado a lado
# em vez de um único chute silencioso — o usuário decide qual é razoável.
CENARIOS_RECEITA_FIPE_PCT = [
    {"pct": 0.05, "label": "Conservador"},
    {"pct": 0.06, "label": "Moderado"},
    {"pct": 0.07, "label": "Otimista"},
]

TAXA_DEPRECIACAO_ANUAL_PADRAO = 0.15  # ~15% a.a., médio para veículos populares/comerciais leves no Brasil


def valor_residual_padrao(prazo_meses: int, taxa_anual: float = TAXA_DEPRECIACAO_ANUAL_PADRAO) -> float:
    """Fração do valor do veículo preservada ao final do contrato, usando uma
    curva de depreciação composta (não uma % fixa, que distorce contratos
    curtos ou longos). Ex.: 24 meses a 15% a.a. -> ~72% preservado."""
    anos = max(0, prazo_meses) / 12
    return round((1 - taxa_anual) ** anos, 4)

MANUTENCAO_POR_CATEGORIA = {
    "hatch": 300.0, "sedan": 380.0, "suv": 450.0, "pickup": 550.0,
    "van": 700.0, "onibus": 1200.0, "caminhao": 900.0, "ambulancia": 900.0,
    "hibrido_phev": 480.0, "hibrido_hev": 420.0, "nao_especificado": 400.0,
}

PNEUS_POR_CATEGORIA = {
    "hatch": 60.0, "sedan": 70.0, "suv": 90.0, "pickup": 110.0,
    "van": 130.0, "onibus": 250.0, "caminhao": 200.0, "ambulancia": 130.0,
    "hibrido_phev": 90.0, "hibrido_hev": 80.0, "nao_especificado": 80.0,
}


def brl_curto(v) -> str:
    """Formata valor em R$ para uso dentro de mensagens de aviso (não é o
    formatador principal do Dashboard, só evita repetir essa lógica em avisos)."""
    neg = v < 0
    v = abs(v)
    s = f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{'-' if neg else ''}R$ {s}"


def pmt(taxa, nper, pv):
    """Parcela (Tabela Price) para um financiamento pv, à taxa mensal, em nper meses."""
    if nper <= 0:
        return 0.0
    if taxa == 0:
        return pv / nper
    return pv * taxa / (1 - (1 + taxa) ** -nper)


def amortizacao_price(taxa, nper_financiamento, pv, meses_periodo):
    """Simula a tabela Price mês a mês pelos primeiros `meses_periodo` meses (o
    prazo contratual, que pode ser menor que o prazo de financiamento) e separa
    juros (despesa de DRE) de amortização de principal (não é despesa contábil —
    só reduz o saldo devedor). Retorna também o saldo devedor remanescente ao
    final do contrato, caso o financiamento ainda não esteja quitado."""
    parcela = pmt(taxa, nper_financiamento, pv)
    saldo = pv
    juros_total = 0.0
    meses = max(0, min(meses_periodo, nper_financiamento))
    for _ in range(meses):
        juros_mes = saldo * taxa
        principal_mes = parcela - juros_mes
        saldo = max(0.0, saldo - principal_mes)
        juros_total += juros_mes
    return {"parcela_mensal": parcela, "juros_total": juros_total, "saldo_devedor_final": saldo}


def npv(taxa, fluxos):
    return sum(cf / (1 + taxa) ** t for t, cf in enumerate(fluxos))


def irr(fluxos):
    """TIR mensal via bisseção (evita dependência de numpy)."""
    baixo, alto = -0.9, 3.0
    if npv(baixo, fluxos) * npv(alto, fluxos) > 0:
        return None
    meio = 0
    for _ in range(200):
        meio = (baixo + alto) / 2
        v = npv(meio, fluxos)
        if abs(v) < 1e-6:
            return meio
        if npv(baixo, fluxos) * v < 0:
            alto = meio
        else:
            baixo = meio
    return meio


def classificar_risco(margem, payback_meses, prazo_meses):
    if margem is None or payback_meses is None:
        return "Alto"
    if margem >= 0.15 and payback_meses <= prazo_meses * 0.5:
        return "Baixo"
    if margem >= 0.06 and payback_meses <= prazo_meses * 0.8:
        return "Médio"
    return "Alto"


def compute_lote_financials(lote: dict, veiculo_ref: dict, prazo_meses: int,
                             valor_lote_estimado: float, valor_explicito: bool,
                             params: dict = None) -> dict:
    p = {**PARAMS_PADRAO, **(params or {})}
    quantidade = max(1, lote.get("quantidade", 1))
    categoria = lote.get("categoria_veiculo", "nao_especificado")
    fipe = (veiculo_ref or {}).get("fipe") or 80000.0

    manutencao_mensal_unit = p["manutencao_mensal"] or MANUTENCAO_POR_CATEGORIA.get(categoria, 400.0)
    pneus_mensal_unit = p["pneus_mensal"] or PNEUS_POR_CATEGORIA.get(categoria, 80.0)

    avisos = [
        f"Veículo de referência: {(veiculo_ref or {}).get('marca','—')} {(veiculo_ref or {}).get('modelo','')} "
        f"(o mais barato da categoria) — confirme que atende 100% das exigências técnicas do edital "
        f"antes de usar este número; se houver qualquer diferença de especificação, o custo real muda."
    ]
    if not valor_explicito:
        avisos.append(
            "Receita estimada com base em referência de mercado (não foi encontrado um "
            "valor estimado explícito no edital para este lote) — confira manualmente."
        )

    prazo_financiamento_meses = p["prazo_financiamento_meses"] or prazo_meses

    # --- Aquisição / capital ---
    # Desconto da montadora incide sobre o custo de compra (capital, depreciação,
    # financiamento) — mas a receita heurística abaixo usa 100% da FIPE, sem desconto,
    # porque é uma referência de preço de mercado da locação, não de custo de aquisição.
    preco_compra = fipe * (1 - p["desconto_montadora"])

    # --- Receita ---
    if valor_lote_estimado and valor_lote_estimado > 0 and prazo_meses > 0:
        receita_mensal_unit = valor_lote_estimado / (quantidade * prazo_meses)
    else:
        receita_mensal_unit = fipe * p["receita_pct_fipe_am"]
        avisos.append(
            f"Nenhum valor estimado disponível no edital — receita projetada em "
            f"{p['receita_pct_fipe_am']*100:.0f}% a.m. de 100% da FIPE do veículo 0km. "
            f"Veja os 3 cenários (5%/6%/7%) e ajuste no Simulador."
        )
    receita_bruta_total = receita_mensal_unit * quantidade * prazo_meses

    # --- DRE (por mês, por veículo, depois multiplicado) ---
    tributos_mensal_unit = receita_mensal_unit * p["tributos_pct"]
    seguro_mensal_unit = preco_compra * p["seguro_pct_am"]
    administracao_mensal_unit = receita_mensal_unit * p["administracao_pct"]

    valor_financiado = preco_compra * (1 - p["entrada_pct"])
    amort = amortizacao_price(p["taxa_juros_am"], prazo_financiamento_meses, valor_financiado, prazo_meses)
    parcela_mensal_unit = amort["parcela_mensal"]  # desembolso de caixa cheio (principal + juros)
    juros_total_unit = amort["juros_total"]        # só os juros contam como despesa na DRE
    saldo_devedor_final_unit = amort["saldo_devedor_final"]

    if saldo_devedor_final_unit > 1:
        avisos.append(
            f"O financiamento não estará quitado ao final do contrato: saldo devedor estimado de "
            f"{saldo_devedor_final_unit:,.2f} por veículo (prazo de financiamento de "
            f"{prazo_financiamento_meses} meses é maior que o prazo contratual de {prazo_meses} meses)."
            .replace(",", "§").replace(".", ",").replace("§", ".")
        )

    residual_pct_efetivo = p["valor_residual_pct"] if p["valor_residual_pct"] is not None else valor_residual_padrao(prazo_meses)
    valor_residual_unit = preco_compra * residual_pct_efetivo
    depreciacao_mensal_unit = (preco_compra - valor_residual_unit) / prazo_meses if prazo_meses > 0 else 0.0

    custos_operacionais_mensal_unit = p["custos_operacionais_mensal"]

    # --- Capital necessário: entrada (se houver) + capital de giro (reserva de
    # caixa para cobrir os primeiros meses de custo operacional antes da fatura
    # do órgão entrar) — com entrada 0% (100% financiado), o capital de giro
    # passa a ser o número que realmente importa pra decisão de GO/NO GO.
    entrada_total = preco_compra * p["entrada_pct"] * quantidade
    custo_operacional_mensal_unit_sem_financeiro = (
        seguro_mensal_unit + manutencao_mensal_unit + pneus_mensal_unit
        + administracao_mensal_unit + custos_operacionais_mensal_unit
    )
    capital_giro_sugerido = custo_operacional_mensal_unit_sem_financeiro * quantidade * p["meses_capital_giro"]
    capital_necessario = round(entrada_total + capital_giro_sugerido, 2)

    tributos_total = tributos_mensal_unit * quantidade * prazo_meses
    seguro_total = seguro_mensal_unit * quantidade * prazo_meses
    manutencao_total = manutencao_mensal_unit * quantidade * prazo_meses
    pneus_total = pneus_mensal_unit * quantidade * prazo_meses
    administracao_total = administracao_mensal_unit * quantidade * prazo_meses
    financeiro_total = juros_total_unit * quantidade  # despesa de DRE = só juros
    depreciacao_total = depreciacao_mensal_unit * quantidade * prazo_meses
    custos_operacionais_total = custos_operacionais_mensal_unit * quantidade * prazo_meses

    lucro_operacional_total = (
        receita_bruta_total - tributos_total - seguro_total - manutencao_total
        - pneus_total - administracao_total - financeiro_total - depreciacao_total
        - custos_operacionais_total
    )
    margem_operacional = (lucro_operacional_total / receita_bruta_total) if receita_bruta_total > 0 else None

    # --- Fluxo de caixa (para ROI / Payback / TIR / VPL): usa a PARCELA CHEIA
    # (principal + juros, o desembolso real de caixa) e NÃO a depreciação (não é caixa) ---
    fluxo_caixa_mensal = (
        receita_mensal_unit - tributos_mensal_unit - seguro_mensal_unit - manutencao_mensal_unit
        - pneus_mensal_unit - administracao_mensal_unit - parcela_mensal_unit
        - custos_operacionais_mensal_unit
    ) * quantidade
    valor_residual_total = valor_residual_unit * quantidade
    saldo_devedor_final_total = saldo_devedor_final_unit * quantidade
    # valor residual líquido: o que sobra ao vender/devolver o veículo, depois de quitar o saldo do financiamento
    valor_residual_liquido_total = valor_residual_total - saldo_devedor_final_total

    if lucro_operacional_total > 0 and fluxo_caixa_mensal < 0:
        avisos.append(
            f"Atenção: a DRE mostra lucro contábil positivo, mas o fluxo de caixa mensal é negativo "
            f"({brl_curto(fluxo_caixa_mensal)}/mês por veículo: {brl_curto(fluxo_caixa_mensal/quantidade)}). "
            f"Isso acontece quando a parcela do financiamento ({brl_curto(parcela_mensal_unit)}/mês/veículo) "
            f"amortiza principal mais rápido do que o veículo deprecia na contabilidade — o negócio pode "
            f"'dar lucro no papel' e ainda assim faltar caixa no dia a dia."
        )

    payback_meses = None
    if capital_necessario <= 0:
        avisos.append("Payback não calculado: capital necessário é zero ou indisponível.")
    elif fluxo_caixa_mensal <= 0:
        avisos.append("Payback não calculado: fluxo de caixa mensal é negativo ou nulo com as premissas atuais.")
    else:
        payback_meses = round(capital_necessario / fluxo_caixa_mensal, 1)

    roi = None
    if capital_necessario <= 0:
        avisos.append("ROI não calculado: capital necessário é zero ou indisponível.")
    else:
        roi = round(
            (fluxo_caixa_mensal * prazo_meses + valor_residual_liquido_total - capital_necessario) / capital_necessario,
            4,
        )

    tir_mensal = tir_anual = vpl = None
    if capital_necessario > 0:
        fluxos = [-capital_necessario] + [fluxo_caixa_mensal] * prazo_meses
        fluxos[-1] += valor_residual_liquido_total
        tir_mensal = irr(fluxos)
        vpl = round(npv(p["taxa_juros_am"], fluxos), 2)
        if tir_mensal is None:
            avisos.append("TIR não calculada: fluxo de caixa não converge (todos os valores positivos ou todos negativos).")
        else:
            tir_anual = round((1 + tir_mensal) ** 12 - 1, 4)
            tir_mensal = round(tir_mensal, 4)

    risco = classificar_risco(margem_operacional, payback_meses, prazo_meses)

    return {
        "premissas": {
            **p,
            "manutencao_mensal_aplicada": round(manutencao_mensal_unit, 2),
            "pneus_mensal_aplicado": round(pneus_mensal_unit, 2),
            "valor_residual_pct_aplicado": residual_pct_efetivo,
            "prazo_financiamento_meses": prazo_financiamento_meses,
        },
        "dre": {
            "receita_bruta": round(receita_bruta_total, 2),
            "tributos": round(-tributos_total, 2),
            "seguro": round(-seguro_total, 2),
            "manutencao": round(-manutencao_total, 2),
            "pneus": round(-pneus_total, 2),
            "administracao": round(-administracao_total, 2),
            "financeiro": round(-financeiro_total, 2),
            "depreciacao": round(-depreciacao_total, 2),
            "custos_operacionais": round(-custos_operacionais_total, 2),
            "lucro_operacional": round(lucro_operacional_total, 2),
        },
        "preco_compra_unitario": round(preco_compra, 2),
        "capital_necessario": round(capital_necessario, 2),
        "entrada_total": round(entrada_total, 2),
        "capital_giro_sugerido": round(capital_giro_sugerido, 2),
        "prazo_financiamento_meses_aplicado": prazo_financiamento_meses,
        "receita_mensal_unitaria": round(receita_mensal_unit, 2),
        "receita_estimada": round(receita_bruta_total, 2),
        "custo_total": round(receita_bruta_total - lucro_operacional_total, 2),
        "margem_estimada": round(margem_operacional, 4) if margem_operacional is not None else None,
        "roi": roi,
        "payback_meses": payback_meses,
        "tir_mensal": tir_mensal,
        "tir_anual": tir_anual,
        "vpl": vpl,
        # Números da "contraprova": por que o caixa pode divergir do lucro
        # contábil (financiamento amortiza principal mais rápido/devagar do
        # que o veículo deprecia) — mostrados explicitamente, não só embutidos
        # na DRE, porque é exatamente o tipo de coisa que precisa ficar visível.
        "parcela_financiamento_unitaria": round(parcela_mensal_unit, 2),
        "custo_mensal_unitario_sem_financeiro": round(custo_operacional_mensal_unit_sem_financeiro, 2),
        "fluxo_caixa_mensal": round(fluxo_caixa_mensal, 2),
        "fluxo_caixa_mensal_unitario": round(fluxo_caixa_mensal / quantidade, 2) if quantidade else None,
        "valor_residual_total": round(valor_residual_total, 2),
        "valor_residual_unitario": round(valor_residual_unit, 2),
        "valor_residual_liquido_total": round(valor_residual_liquido_total, 2),
        "saldo_devedor_final_total": round(saldo_devedor_final_total, 2),
        "risco": risco,
        "avisos": avisos,
    }


def compute_cenarios_lote(lote: dict, veiculo_ref: dict, prazo_meses: int) -> list:
    """Quando o edital não tem receita/locação explícita, calcula 3 cenários
    (5%/6%/7% da FIPE 0km ao mês) lado a lado, em vez de um único chute."""
    cenarios = []
    for c in CENARIOS_RECEITA_FIPE_PCT:
        fin = compute_lote_financials(
            lote, veiculo_ref, prazo_meses, valor_lote_estimado=0, valor_explicito=False,
            params={"receita_pct_fipe_am": c["pct"]},
        )
        cenarios.append({"pct": c["pct"], "label": c["label"], "financeiro": fin})
    return cenarios


def compute_consolidado(lotes_financeiro: list) -> dict:
    capital_total = sum(l["capital_necessario"] for l in lotes_financeiro)
    receita_total = sum(l["receita_estimada"] for l in lotes_financeiro)
    lucro_total = sum(l["dre"]["lucro_operacional"] for l in lotes_financeiro)
    vpl_total = sum(l["vpl"] for l in lotes_financeiro if l["vpl"] is not None)
    residual_total = sum(l["valor_residual_total"] for l in lotes_financeiro)
    residual_liquido_total = sum(l["valor_residual_liquido_total"] for l in lotes_financeiro)
    saldo_devedor_total = sum(l["saldo_devedor_final_total"] for l in lotes_financeiro)

    dre_consolidado = {}
    for chave in ["receita_bruta", "tributos", "seguro", "manutencao", "pneus",
                  "administracao", "financeiro", "depreciacao", "custos_operacionais",
                  "lucro_operacional"]:
        dre_consolidado[chave] = round(sum(l["dre"][chave] for l in lotes_financeiro), 2)

    margem_media = (lucro_total / receita_total) if receita_total > 0 else None

    rois = [l["roi"] for l in lotes_financeiro if l["roi"] is not None]
    roi_medio = sum(rois) / len(rois) if rois else None

    paybacks = [l["payback_meses"] for l in lotes_financeiro if l["payback_meses"]]
    payback_medio = sum(paybacks) / len(paybacks) if paybacks else None

    tires = [l["tir_anual"] for l in lotes_financeiro if l["tir_anual"] is not None]
    tir_media = sum(tires) / len(tires) if tires else None

    return {
        "dre": dre_consolidado,
        "capital_investido": round(capital_total, 2),
        "receita_estimada": round(receita_total, 2),
        "custo_total": round(receita_total - lucro_total, 2),
        "margem_media": round(margem_media, 4) if margem_media is not None else None,
        "roi_medio": round(roi_medio, 4) if roi_medio is not None else None,
        "payback_medio_meses": round(payback_medio, 1) if payback_medio else None,
        "tir_media_anual": round(tir_media, 4) if tir_media is not None else None,
        "vpl_total": round(vpl_total, 2),
        "valor_residual_total": round(residual_total, 2),
        "valor_residual_liquido_total": round(residual_liquido_total, 2),
        "saldo_devedor_final_total": round(saldo_devedor_total, 2),
        "reserva_tecnica_sugerida": round((receita_total - lucro_total) * 0.10, 2),
    }
