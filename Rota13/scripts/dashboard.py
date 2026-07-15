"""Gera o Dashboard HTML executivo (dark mode, responsivo, single-page).

Sprint 2: o Dashboard deixa de ser um relatório bonito e passa a ser um
painel de decisão. Todo indicador financeiro vem de uma DRE explícita, todo
score tem categorias com justificativa, toda decisão jurídica cita
página/trecho do edital, e nenhum indicador é exibido quando não há dados
suficientes para calculá-lo com confiança.

O HTML é 100% autocontido (CSS e JS inline, sem CDN). A maior parte do
conteúdo é renderizada com os números já calculados em Python; a seção de
Simulação usa JavaScript para recalcular os indicadores em tempo real,
espelhando exatamente as fórmulas de scripts/financial.py.
"""
import json
from pathlib import Path


def _brl(v) -> str:
    if v is None:
        return "—"
    neg = v < 0
    v = abs(v)
    s = f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{'-' if neg else ''}R$ {s}"


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%".replace(".", ",")


def _num(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}".replace(",", ".")


def _meses(v) -> str:
    if v is None:
        return "—"
    return f"{v:.1f} meses".replace(".", ",")


def _indicador(valor, formatador, avisos: list, palavra_chave: str) -> str:
    """Mostra o valor formatado, ou a mensagem de indisponibilidade se valor é None."""
    if valor is not None:
        return formatador(valor)
    for a in avisos:
        if palavra_chave.lower() in a.lower():
            return "Não calculado — dados insuficientes"
    return "Não calculado por falta de informações."


DECISAO_CLASSE = {"GO": "ok", "GO COM RESSALVAS": "warn", "NO GO": "bad", "ANÁLISE PENDENTE": "warn"}
RISCO_CLASSE = {"Baixo": "ok", "Médio": "warn", "Alto": "bad"}
COR_CLASSE = {"verde": "ok", "amarelo": "warn", "vermelho": "bad"}
COR_EMOJI = {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴"}
SEVERIDADE_CLASSE = {"baixa": "ok", "media": "warn", "alta": "bad"}
SEVERIDADE_LABEL = {"baixa": "Baixa", "media": "Média", "alta": "Alta"}
DECISAO_LOTE_CLASSE = {"SIM": "ok", "TALVEZ": "warn", "NÃO": "bad"}

CATEGORIA_LABEL = {
    "hatch": "Hatch", "sedan": "Sedã", "suv": "SUV", "pickup": "Picape",
    "van": "Van/Furgão", "onibus": "Ônibus/Micro-ônibus", "caminhao": "Caminhão",
    "ambulancia": "Ambulância", "hibrido": "Híbrido", "nao_especificado": "Não especificado",
}

DRE_LABELS = [
    ("receita_bruta", "Receita Bruta"),
    ("tributos", "(-) Tributos"),
    ("seguro", "(-) Seguro"),
    ("manutencao", "(-) Manutenção"),
    ("pneus", "(-) Pneus"),
    ("administracao", "(-) Administração"),
    ("financeiro", "(-) Financeiro"),
    ("depreciacao", "(-) Depreciação"),
    ("custos_operacionais", "(-) Custos Operacionais"),
    ("lucro_operacional", "= Lucro Operacional"),
]


def _svg_gauge(score: float, cor_classe: str) -> str:
    if score is None:
        return '''<div class="gauge-indisponivel"><strong>—</strong><span>Score bloqueado</span></div>'''
    raio = 54
    circ = 2 * 3.14159265 * raio
    frac = max(0, min(score, 100)) / 100
    offset = circ * (1 - frac)
    return f'''<svg width="140" height="140" viewBox="0 0 140 140" class="gauge">
      <circle cx="70" cy="70" r="{raio}" class="gauge-track"/>
      <circle cx="70" cy="70" r="{raio}" class="gauge-fill gauge-{cor_classe}"
        stroke-dasharray="{circ:.1f}" stroke-dashoffset="{offset:.1f}"/>
      <text x="70" y="64" class="gauge-score">{score:.0f}</text>
      <text x="70" y="86" class="gauge-label">/ 100</text>
    </svg>'''


def _barra_categoria(nome_label: str, cat: dict) -> str:
    frac = cat["pontos"] / cat["maximo"] if cat["maximo"] else 0
    classe = "ok" if frac >= 0.7 else "warn" if frac >= 0.4 else "bad"
    motivo = cat["motivos"][0] if cat["motivos"] else ""
    return f'''<div class="cat-row">
      <div class="cat-row-top"><span>{nome_label}</span><span>{cat["pontos"]:.0f}/{cat["maximo"]}</span></div>
      <div class="bar-track"><div class="bar-fill {classe}" style="width:{frac*100:.0f}%"></div></div>
      <div class="cat-motivo">{motivo}</div>
    </div>'''


def _lista(itens: list) -> str:
    return "".join(f"<li>{i}</li>" for i in itens)


def _checklist(itens: list, prefix: str) -> str:
    linhas = []
    for i, item in enumerate(itens):
        cid = f"{prefix}-{i}"
        linhas.append(f'<li class="checklist-item"><label><input type="checkbox" id="{cid}"> {item}</label></li>')
    return "".join(linhas)


def _svg_barras_lote(fin: dict) -> str:
    valores = {"Capital": fin["capital_necessario"], "Receita": fin["receita_estimada"],
               "Custo": fin["custo_total"]}
    maximo = max(valores.values()) or 1
    cores = {"Capital": "#3b82f6", "Receita": "#22c55e", "Custo": "#ef4444"}
    linhas = []
    for label, valor in valores.items():
        largura = max(2, (valor / maximo) * 100)
        linhas.append(f'''
        <div class="bar-row">
          <span class="bar-label">{label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:{largura:.1f}%;background:{cores[label]}"></div></div>
          <span class="bar-value">{_brl(valor)}</span>
        </div>''')
    return "".join(linhas)


def _tabela_cenarios(cenarios: list) -> str:
    if not cenarios:
        return ""
    linhas = "".join(
        f'''<div class="cenario-col">
          <div class="cenario-pct">{c["pct"]*100:.0f}% <span class="cenario-label">{c["label"]}</span></div>
          <div class="cenario-item"><span>Receita/mês (unid.)</span><b>{_brl(c["financeiro"]["receita_mensal_unitaria"])}</b></div>
          <div class="cenario-item"><span>Margem</span><b>{_indicador(c["financeiro"]["margem_estimada"], _pct, [], "margem")}</b></div>
          <div class="cenario-item"><span>ROI</span><b>{_indicador(c["financeiro"]["roi"], _pct, [], "roi")}</b></div>
        </div>'''
        for c in cenarios
    )
    return f'''<div class="cenarios-box">
      <div class="cenarios-titulo">⚠️ Edital sem valor de locação explícito — 3 cenários estimados a partir da FIPE 0km (edite no Simulador):</div>
      <div class="cenarios-grid">{linhas}</div>
    </div>'''


def _card_lote(lote: dict, prazo_meses: int) -> str:
    fin = lote["financeiro"]
    dp = lote["decisao_participar"]
    risco_classe = RISCO_CLASSE.get(fin["risco"], "warn")
    decisao_classe = DECISAO_LOTE_CLASSE.get(dp["decisao"], "warn")
    veic = lote.get("veiculo_referencia") or {}

    alertas_html = "".join(f'<li>⚠️ {a}</li>' for a in lote["alertas"])
    pendencias_html = "".join(f'<li>☐ {p}</li>' for p in lote["pendencias"])
    motivos_html = "".join(f"<li>{m}</li>" for m in dp["motivos"])

    margem_txt = _indicador(fin["margem_estimada"], _pct, fin["avisos"], "margem")
    payback_txt = _indicador(fin["payback_meses"], _meses, fin["avisos"], "payback")
    roi_txt = _indicador(fin["roi"], _pct, fin["avisos"], "roi")
    tir_txt = _indicador(fin["tir_anual"], _pct, fin["avisos"], "tir")
    fonte = lote.get("fonte") or {}
    evidencia_html = (
        f'<p class="doc-fonte">Evidência: página {fonte["pagina"]} — "{fonte.get("trecho", "")}"</p>'
        if fonte.get("pagina") else
        '<p class="doc-fonte">Evidência do lote não confirmada — revise o TR.</p>'
    )

    return f'''
    <div class="card lote-card">
      <div class="card-header">
        <h3>{COR_EMOJI.get(lote["semaforo"],"")} Lote {lote["numero"]} <span class="lote-score">Score {lote["score"]}/100</span></h3>
        <span class="badge {decisao_classe}">Participar? {dp["decisao"]}</span>
      </div>
      <p class="lote-desc">{lote["descricao"]}</p>
      {evidencia_html}
      <div class="lote-meta">
        <span>🚗 {_num(lote["quantidade"])} veículo(s)</span>
        <span>🏷️ {CATEGORIA_LABEL.get(lote["categoria_veiculo"], lote["categoria_veiculo"])}</span>
        <span>📋 Ref.: {veic.get("marca", "—")} {veic.get("modelo", "")}</span>
        <span class="badge {risco_classe}">Risco {fin["risco"]}</span>
      </div>
      <div class="stat-grid">
        <div class="stat"><span class="stat-label">Capital necessário</span><span class="stat-value">{_brl(fin["capital_necessario"])}</span></div>
        <div class="stat"><span class="stat-label">Receita bruta</span><span class="stat-value">{_brl(fin["receita_estimada"])}</span></div>
        <div class="stat"><span class="stat-label">Margem operacional</span><span class="stat-value small">{margem_txt}</span></div>
        <div class="stat"><span class="stat-label">ROI (período)</span><span class="stat-value small">{roi_txt}</span></div>
        <div class="stat"><span class="stat-label">Payback</span><span class="stat-value small">{payback_txt}</span></div>
        <div class="stat"><span class="stat-label">TIR anual</span><span class="stat-value small">{tir_txt}</span></div>
      </div>
      <div class="bar-chart">{_svg_barras_lote(fin)}</div>
      {_tabela_cenarios(lote.get("cenarios_receita"))}
      <div class="lote-lists">
        <div><strong>Por que "{dp["decisao"]}"?</strong><ul>{motivos_html}</ul></div>
        <div><strong>Alertas</strong><ul>{alertas_html}</ul>
             <strong>Pendências</strong><ul>{pendencias_html}</ul></div>
      </div>
    </div>'''


def _card_lei(lei: dict) -> str:
    return f'''<div class="doc-card">
      <h4>{lei["nome"]}</h4>
      <p>{lei["resumo"]}</p>
      <p class="doc-fonte">Fonte: {lei["fonte"]}</p>
    </div>'''


def _card_acordao(a: dict) -> str:
    return f'''<div class="doc-card">
      <h4>{a["numero"]}</h4>
      <p class="doc-tema">{a["tema"]}</p>
      <p>{a["resumo"]}</p>
      <p class="doc-fonte">Fonte: {a["fonte"]}</p>
    </div>'''


def _card_achado_juridico(a: dict) -> str:
    classe = SEVERIDADE_CLASSE.get(a["severidade"], "warn")
    label = SEVERIDADE_LABEL.get(a["severidade"], "Média")
    if a.get("pagina"):
        citacao = f'📄 Página {a["pagina"]}: "{a["trecho"]}"'
    else:
        citacao = "📄 Não localizado no texto disponível — confirmar manualmente no edital."
    return f'''<div class="doc-card">
      <div class="card-header" style="margin-bottom:6px"><span class="badge {classe}">{label}</span></div>
      <p>{a["analise"]}</p>
      <p class="doc-fonte">{citacao}</p>
    </div>'''


def _linha_dre(chave: str, label: str, valor: float, destaque: bool) -> str:
    classe = "dre-destaque" if destaque else ""
    sinal_classe = "dre-negativo" if valor < 0 and not destaque else ""
    return f'<div class="dre-row {classe} {sinal_classe}"><span>{label}</span><span>{_brl(valor)}</span></div>'


def _bloco_dre(dre: dict) -> str:
    linhas = []
    for chave, label in DRE_LABELS:
        destaque = chave == "lucro_operacional"
        linhas.append(_linha_dre(chave, label, dre[chave], destaque))
    return "".join(linhas)


def _timeline_html(timeline: list) -> str:
    itens = []
    for t in timeline:
        classe = "ok" if t["identificado"] else "muted"
        itens.append(f'''<div class="tl-item">
          <div class="tl-dot {classe}"></div>
          <div><strong>{t["fase"]}</strong><div class="tl-info">{t["info"]}</div></div>
        </div>''')
    return "".join(itens)


def _semaforo_html(semaforo: dict) -> str:
    ordem = ["financeiro", "juridico", "operacional", "entrega", "documentacao"]
    itens = []
    for k in ordem:
        item = semaforo[k]
        itens.append(f'''<div class="sem-item">
          <div class="sem-emoji">{COR_EMOJI.get(item["cor"], "🟡")}</div>
          <div class="sem-label">{item["label"]}</div>
          <div class="sem-just">{item["justificativa"]}</div>
        </div>''')
    return "".join(itens)


def _validacao_html(validacao: dict) -> str:
    if not validacao.get("bloqueada"):
        return ""
    bloqueios = "".join(f"<li>{b}</li>" for b in validacao.get("bloqueios", []))
    return f'''<div class="card validacao-card">
      <div class="card-header"><h3>⛔ Recomendação automática bloqueada</h3><span class="badge warn">VALIDAÇÃO NECESSÁRIA</span></div>
      <p>Os dados abaixo impedem um GO/NO GO confiável. O simulador e os números exibidos devem ser tratados apenas como cenário exploratório.</p>
      <ul>{bloqueios}</ul>
    </div>'''


def render(analise: dict, out_path: Path) -> str:
    r = analise["resumo_executivo"]
    fin = analise["financeiro"]
    jur = analise["juridico"]
    op = analise["operacional"]
    lotes = analise["lotes"]
    semaforo = analise["semaforo"]
    confianca = analise["confianca_extracao"]
    validacao = analise.get("validacao_decisao", {"bloqueada": False, "bloqueios": []})
    prazo_meses = r["prazo_contratual_meses"]

    lotes_html = "".join(_card_lote(l, prazo_meses) for l in lotes)
    leis_html = "".join(_card_lei(l) for l in jur["leis_aplicaveis"]) or "<p>Nenhuma lei específica casada automaticamente.</p>"
    acordaos_html = "".join(_card_acordao(a) for a in jur["acordaos_relevantes"])
    achados_html = "".join(_card_achado_juridico(a) for a in jur["achados"]) or "<p>Nenhum achado de risco na análise heurística.</p>"
    checklist_juridico_html = _checklist(jur["checklist_juridico"], "jur")
    esclarecimentos_html = _lista(jur["itens_esclarecimento"])

    veiculos_op_html = "".join(
        f'''<div class="doc-card">
          <h4>Lote {v["lote"]} — {CATEGORIA_LABEL.get(v["categoria"], v["categoria"])}</h4>
          <p><strong>{(v["referencia"] or {}).get("marca","—")} {(v["referencia"] or {}).get("modelo","")}</strong> · {v["quantidade"]} unidade(s)</p>
          <p>FIPE ref.: {_brl((v["referencia"] or {}).get("fipe"))} · Consumo: {(v["referencia"] or {}).get("consumo","—")}</p>
          <p>Pneu: {(v["referencia"] or {}).get("pneu","—")} · Valor residual estimado: {_brl(v["valor_residual_unitario"])}</p>
          <p>Garantia: {(v["referencia"] or {}).get("garantia","—")}</p>
          <p class="doc-fonte">{(v["referencia"] or {}).get("observacoes","")}</p>
        </div>'''
        for v in op["veiculos"]
    )
    documentacao_html = _lista(op["documentacao"])
    exigencias_html = _lista(op["exigencias"])
    checklist_operacional_html = _checklist(op["checklist_operacional"], "op")
    checklist_pratico_html = _checklist(analise["checklist_pratico"], "prat")

    lote_options = "".join(
        f'<option value="{l["numero"]}">Lote {l["numero"]} ({_num(l["quantidade"])} veíc.)</option>' for l in lotes
    )

    categorias_score_html = "".join(
        _barra_categoria(label, r["score_categorias"][chave])
        for chave, label in [("financeiro", "Financeiro (40)"), ("juridico", "Jurídico (20)"),
                              ("operacional", "Operacional (20)"), ("documentacao", "Documentação (10)"),
                              ("riscos", "Riscos (10)")]
    )
    if validacao.get("bloqueada"):
        categorias_score_html = '<p class="score-provisorio">Score preliminar indisponível para decisão até a validação dos dados críticos.</p>'

    motivos_decisao_html = _lista(r["motivos_decisao"])
    pontos_fortes_html = _lista(r["pontos_fortes"])
    pontos_fracos_html = _lista(r["pontos_fracos"])
    riscos_html = _lista(r["riscos"])
    oportunidades_html = _lista(r["oportunidades"])
    decisoes_necessarias_html = _lista(r["decisoes_necessarias"])
    acoes_recomendadas_html = _lista(r["acoes_recomendadas"])

    campos_encontrados_html = "".join(f'<span class="chip ok">{c}</span>' for c in confianca["campos_encontrados"])
    campos_pendentes_html = "".join(f'<span class="chip bad">{c}</span>' for c in confianca["campos_pendentes"])
    campos_revisados_html = "".join(f'<span class="chip warn">{c}</span>' for c in confianca["campos_revisados"])

    timeline_html = _timeline_html(analise["timeline"])
    semaforo_html = _semaforo_html(semaforo)

    dre_consolidado_html = _bloco_dre(fin["dre"])
    margem_txt = _indicador(fin["margem_media"], _pct, [], "margem")
    roi_txt = _indicador(fin["roi_medio"], _pct, [], "roi")
    payback_txt = _indicador(fin["payback_medio_meses"], _meses, [], "payback")
    tir_txt = _indicador(fin["tir_media_anual"], _pct, [], "tir")

    analise_json = json.dumps(analise, ensure_ascii=False)

    html = _TEMPLATE
    html = html.replace("__TITULO__", f'{r["orgao"]} — {r["numero_processo"]}')
    html = html.replace("__ORGAO__", r["orgao"])
    html = html.replace("__NUMERO_PROCESSO__", r["numero_processo"])
    html = html.replace("__OBJETO__", r["objeto"])
    html = html.replace("__DECISAO__", r["decisao"])
    html = html.replace("__DECISAO_CLASSE__", DECISAO_CLASSE.get(r["decisao"], "warn"))
    html = html.replace("__MOTIVOS_DECISAO__", motivos_decisao_html)
    score_geral = r["score_geral"]
    cor_score = "ok" if score_geral is not None and score_geral >= 70 else "warn" if score_geral is not None and score_geral >= 40 else "bad"
    html = html.replace("__SCORE_GAUGE__", _svg_gauge(score_geral, cor_score))
    html = html.replace("__CATEGORIAS_SCORE__", categorias_score_html)
    html = html.replace("__VALIDACAO_HTML__", _validacao_html(validacao))
    html = html.replace("__SEMAFORO_HTML__", semaforo_html)
    html = html.replace("__PRAZO__", str(prazo_meses))
    valor_txt = _brl(r["valor_estimado"]) + ("" if r["valor_estimado_explicito"] else " (estimado — não explícito no edital)")
    html = html.replace("__VALOR_ESTIMADO__", valor_txt)
    html = html.replace("__QTD_LOTES__", _num(r["qtd_lotes"]))
    html = html.replace("__QTD_ITENS__", _num(r["qtd_itens"]))
    html = html.replace("__PONTOS_FORTES__", pontos_fortes_html)
    html = html.replace("__PONTOS_FRACOS__", pontos_fracos_html)
    html = html.replace("__RISCOS__", riscos_html)
    html = html.replace("__OPORTUNIDADES__", oportunidades_html)
    html = html.replace("__DECISOES_NECESSARIAS__", decisoes_necessarias_html)
    html = html.replace("__ACOES_RECOMENDADAS__", acoes_recomendadas_html)
    html = html.replace("__LOTES_HTML__", lotes_html)

    html = html.replace("__CONFIANCA_PCT__", str(confianca["percentual"]))
    cor_confianca = "ok" if confianca["percentual"] >= 80 else "warn" if confianca["percentual"] >= 50 else "bad"
    html = html.replace("__CONFIANCA_CLASSE__", cor_confianca)
    html = html.replace("__CONFIANCA_MOTOR__", "IA local (Ollama)" if confianca["motor"] == "ia" else "Regex (determinístico)")
    html = html.replace("__CAMPOS_ENCONTRADOS__", campos_encontrados_html or "<span class='chip'>—</span>")
    html = html.replace("__CAMPOS_PENDENTES__", campos_pendentes_html or "<span class='chip'>Nenhum</span>")
    html = html.replace("__CAMPOS_REVISADOS__", campos_revisados_html or "<span class='chip'>Nenhum</span>")

    html = html.replace("__DRE_CONSOLIDADO__", dre_consolidado_html)
    html = html.replace("__MARGEM_MEDIA__", margem_txt)
    html = html.replace("__ROI_MEDIO__", roi_txt)
    html = html.replace("__PAYBACK_MEDIO__", payback_txt)
    html = html.replace("__TIR_MEDIA__", tir_txt)
    html = html.replace("__VPL_TOTAL__", _brl(fin["vpl_total"]))
    html = html.replace("__RESERVA_TECNICA__", _brl(fin["reserva_tecnica_sugerida"]))
    residual_label = _brl(fin["valor_residual_liquido_total"])
    if fin["saldo_devedor_final_total"] > 1:
        residual_label += f' (bruto {_brl(fin["valor_residual_total"])} - saldo devedor {_brl(fin["saldo_devedor_final_total"])})'
    html = html.replace("__VALOR_RESIDUAL__", residual_label)
    html = html.replace("__CAPITAL_INVESTIDO__", _brl(fin["capital_investido"]))

    html = html.replace("__LEIS_HTML__", leis_html)
    html = html.replace("__ACORDAOS_HTML__", acordaos_html)
    html = html.replace("__ACHADOS_JURIDICOS_HTML__", achados_html)
    html = html.replace("__CHECKLIST_JURIDICO__", checklist_juridico_html)
    html = html.replace("__ESCLARECIMENTOS__", esclarecimentos_html)

    html = html.replace("__VEICULOS_OP_HTML__", veiculos_op_html)
    html = html.replace("__PRAZO_ENTREGA__", op["prazo_entrega"])
    html = html.replace("__MANUTENCAO_TXT__", op["manutencao"])
    html = html.replace("__SEGURO_TXT__", op["seguro"])
    html = html.replace("__DOCUMENTACAO_HTML__", documentacao_html)
    html = html.replace("__EXIGENCIAS_HTML__", exigencias_html)
    html = html.replace("__CHECKLIST_OPERACIONAL__", checklist_operacional_html)
    html = html.replace("__CHECKLIST_PRATICO__", checklist_pratico_html)
    html = html.replace("__TIMELINE_HTML__", timeline_html)

    html = html.replace("__LOTE_OPTIONS__", lote_options)
    html = html.replace("__MARKET_MSG__", analise["market_intelligence"]["mensagem"])
    html = html.replace("__ANALISE_JSON__", analise_json)

    out_path.write_text(html, encoding="utf-8")
    return html


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rota13 — __TITULO__</title>
<style>
  :root{
    --bg:#0b0f14; --bg-card:#12181f; --bg-card-hover:#161e27; --border:#233040;
    --text:#e6edf3; --text-dim:#8b98a5; --accent:#3b82f6;
    --ok:#22c55e; --ok-bg:rgba(34,197,94,.12);
    --warn:#f59e0b; --warn-bg:rgba(245,158,11,.12);
    --bad:#ef4444; --bad-bg:rgba(239,68,68,.12);
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:var(--bg);color:var(--text);line-height:1.5}
  header.topbar{padding:20px 28px;border-bottom:1px solid var(--border);
    display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;
    position:sticky;top:0;background:rgba(11,15,20,.92);backdrop-filter:blur(6px);z-index:10}
  header.topbar h1{font-size:18px;margin:0;font-weight:600}
  header.topbar .brand{color:var(--accent);font-weight:800;letter-spacing:.5px}
  nav.tabs{display:flex;gap:4px;padding:0 28px;border-bottom:1px solid var(--border);
    overflow-x:auto;background:var(--bg)}
  nav.tabs a{padding:12px 16px;color:var(--text-dim);text-decoration:none;font-size:14px;
    border-bottom:2px solid transparent;white-space:nowrap}
  nav.tabs a:hover{color:var(--text)}
  main{max-width:1300px;margin:0 auto;padding:24px 28px 80px}
  section{margin-bottom:48px;scroll-margin-top:110px}
  section h2{font-size:20px;margin:0 0 16px;display:flex;align-items:center;gap:8px}
  .grid{display:grid;gap:16px}
  .grid-2{grid-template-columns:repeat(auto-fit,minmax(420px,1fr))}
  .grid-3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
  .grid-4{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
  .card{background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:20px}
  .card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:6px}
  .card-header h3{margin:0;font-size:16px;display:flex;align-items:center;gap:8px}
  .lote-score{font-size:11px;color:var(--text-dim);font-weight:400}
  .badge{padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
  .badge.ok{background:var(--ok-bg);color:var(--ok)}
  .badge.warn{background:var(--warn-bg);color:var(--warn)}
  .badge.bad{background:var(--bad-bg);color:var(--bad)}
  .chip{display:inline-block;padding:3px 9px;border-radius:999px;font-size:11px;margin:2px;background:var(--border);color:var(--text-dim)}
  .chip.ok{background:var(--ok-bg);color:var(--ok)}
  .chip.warn{background:var(--warn-bg);color:var(--warn)}
  .chip.bad{background:var(--bad-bg);color:var(--bad)}
  .resumo-top{display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:center}
  @media(max-width:700px){.resumo-top{grid-template-columns:1fr}}
  .gauge{display:block;margin:0 auto}
  .gauge-track{fill:none;stroke:var(--border);stroke-width:10}
  .gauge-fill{fill:none;stroke-width:10;stroke-linecap:round;transform:rotate(-90deg);
    transform-origin:70px 70px;transition:stroke-dashoffset .6s ease}
  .gauge-ok{stroke:var(--ok)} .gauge-warn{stroke:var(--warn)} .gauge-bad{stroke:var(--bad)}
  .gauge-score{font-size:30px;font-weight:800;fill:var(--text);text-anchor:middle}
  .gauge-label{font-size:11px;fill:var(--text-dim);text-anchor:middle}
  .gauge-indisponivel{width:140px;height:140px;border:10px solid var(--warn);border-radius:50%;margin:0 auto;
    display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
  .gauge-indisponivel strong{font-size:38px;line-height:1}.gauge-indisponivel span{font-size:11px;color:var(--text-dim);margin-top:6px}
  .go-badge{display:inline-block;font-size:20px;font-weight:800;padding:8px 22px;border-radius:10px;margin-bottom:10px}
  .go-badge.ok{background:var(--ok-bg);color:var(--ok)}
  .go-badge.warn{background:var(--warn-bg);color:var(--warn)}
  .go-badge.bad{background:var(--bad-bg);color:var(--bad)}
  .resumo-stats{display:flex;flex-wrap:wrap;gap:22px;margin-top:14px}
  .resumo-stats .stat{min-width:140px}
  .stat-label{display:block;font-size:12px;color:var(--text-dim);margin-bottom:2px}
  .stat-value{display:block;font-size:17px;font-weight:700}
  .stat-value.small{font-size:13px;font-weight:600}
  .stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}
  ul{margin:6px 0 0;padding-left:18px}
  li{margin-bottom:4px;font-size:14px}
  .obj-box{color:var(--text-dim);font-size:14px;margin-top:6px}
  .lote-card .lote-desc{color:var(--text-dim);font-size:13px;margin:6px 0}
  .lote-meta{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:13px;color:var(--text-dim);margin-bottom:8px}
  .bar-chart{margin-top:10px}
  .bar-row{display:grid;grid-template-columns:60px 1fr 110px;align-items:center;gap:8px;margin-bottom:6px;font-size:12px}
  .bar-track{background:var(--border);border-radius:6px;height:10px;overflow:hidden}
  .bar-fill{height:100%;border-radius:6px}
  .bar-fill.ok{background:var(--ok)} .bar-fill.warn{background:var(--warn)} .bar-fill.bad{background:var(--bad)}
  .lote-lists{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px;font-size:13px}
  @media(max-width:600px){.lote-lists{grid-template-columns:1fr}}
  .cenarios-box{background:var(--warn-bg);border:1px solid var(--warn);border-radius:10px;padding:12px;margin-top:12px}
  .cenarios-titulo{font-size:12px;color:var(--warn);margin-bottom:10px;font-weight:600}
  .cenarios-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .cenario-col{background:var(--bg-card);border-radius:8px;padding:10px;font-size:12px}
  .cenario-pct{font-weight:800;margin-bottom:6px}
  .cenario-label{font-weight:400;color:var(--text-dim);font-size:11px}
  .cenario-item{display:flex;justify-content:space-between;padding:2px 0;color:var(--text-dim)}
  .cenario-item b{color:var(--text)}
  .doc-card{background:var(--bg-card-hover);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px}
  .doc-card h4{margin:0 0 6px;font-size:14px}
  .doc-card p{margin:4px 0;font-size:13px;color:var(--text-dim)}
  .doc-tema{color:var(--accent) !important}
  .doc-fonte{font-size:11px !important;opacity:.8;font-style:italic}
  .checklist-item{list-style:none;margin-left:-18px}
  .checklist-item label{display:flex;gap:8px;align-items:flex-start;cursor:pointer;font-size:14px}
  .checklist-item input{margin-top:3px}
  .cat-row{margin-bottom:14px}
  .cat-row-top{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px}
  .cat-motivo{font-size:12px;color:var(--text-dim);margin-top:4px}
  .sem-panel{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
  .sem-item{background:var(--bg-card-hover);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center}
  .sem-emoji{font-size:26px}
  .sem-label{font-weight:700;margin:4px 0}
  .sem-just{font-size:11px;color:var(--text-dim)}
  .dre-row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:14px}
  .dre-row:last-child{border-bottom:none}
  .dre-negativo span:last-child{color:var(--bad)}
  .dre-destaque{font-weight:800;font-size:16px;border-top:2px solid var(--border);margin-top:6px;padding-top:12px}
  .tl-item{display:flex;gap:12px;padding:10px 0}
  .tl-dot{width:12px;height:12px;border-radius:50%;margin-top:4px;flex-shrink:0}
  .tl-dot.ok{background:var(--ok)} .tl-dot.muted{background:var(--border)}
  .tl-info{font-size:12px;color:var(--text-dim)}
  .sim-grid{display:grid;grid-template-columns:340px 1fr;gap:20px}
  @media(max-width:900px){.sim-grid{grid-template-columns:1fr}}
  .sim-field{margin-bottom:14px}
  .sim-field label{display:flex;justify-content:space-between;font-size:13px;color:var(--text-dim);margin-bottom:4px}
  .sim-field input[type=range]{width:100%}
  .sim-field select{width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:8px}
  .sim-result-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
  .sim-result{background:var(--bg-card-hover);border:1px solid var(--border);border-radius:10px;padding:14px}
  .sim-result .stat-value{font-size:18px}
  .market-card{text-align:center;padding:40px 20px;color:var(--text-dim)}
  .market-card .lock{font-size:36px;margin-bottom:10px}
  .confianca-row{display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap}
  .validacao-card{border-color:var(--warn);background:var(--warn-bg);margin-bottom:16px}
  .validacao-card p{font-size:14px;margin:4px 0}.score-provisorio{color:var(--warn);font-size:14px;margin:0}
  footer{text-align:center;color:var(--text-dim);font-size:12px;padding:30px 0}
</style>
</head>
<body>

<header class="topbar">
  <h1><span class="brand">ROTA13</span> Bid Intelligence — Painel de Decisão</h1>
  <div style="font-size:13px;color:var(--text-dim)">__ORGAO__ · __NUMERO_PROCESSO__</div>
</header>

<nav class="tabs">
  <a href="#resumo">Resumo</a>
  <a href="#lotes">Lotes</a>
  <a href="#financeiro">Financeiro (DRE)</a>
  <a href="#juridico">Jurídico</a>
  <a href="#operacional">Operacional</a>
  <a href="#checklist">O que fazer</a>
  <a href="#timeline">Timeline</a>
  <a href="#simulacao">Simulação</a>
  <a href="#mercado">Mercado</a>
</nav>

<main>

<section id="resumo">
  <h2>📊 Resumo Executivo</h2>
  __VALIDACAO_HTML__
  <div class="card resumo-top">
    <div>__SCORE_GAUGE__</div>
    <div>
      <span class="go-badge __DECISAO_CLASSE__">__DECISAO__</span>
      <ul>__MOTIVOS_DECISAO__</ul>
      <div class="obj-box"><strong>Objeto:</strong> __OBJETO__</div>
      <div class="resumo-stats">
        <div class="stat"><span class="stat-label">Prazo contratual</span><span class="stat-value">__PRAZO__ meses</span></div>
        <div class="stat"><span class="stat-label">Valor estimado</span><span class="stat-value">__VALOR_ESTIMADO__</span></div>
        <div class="stat"><span class="stat-label">Lotes</span><span class="stat-value">__QTD_LOTES__</span></div>
        <div class="stat"><span class="stat-label">Itens (veículos)</span><span class="stat-value">__QTD_ITENS__</span></div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:16px">
    <h3 style="margin-top:0">Score por categoria</h3>
    __CATEGORIAS_SCORE__
  </div>

  <div class="card" style="margin-top:16px">
    <h3 style="margin-top:0">Semáforo</h3>
    <div class="sem-panel">__SEMAFORO_HTML__</div>
  </div>

  <div class="card" style="margin-top:16px">
    <h3 style="margin-top:0">Confiança da extração</h3>
    <div class="confianca-row">
      <span class="badge __CONFIANCA_CLASSE__">__CONFIANCA_PCT__%</span>
      <span style="font-size:12px;color:var(--text-dim)">Motor: __CONFIANCA_MOTOR__</span>
    </div>
    <div style="margin-top:10px"><strong style="font-size:12px">Encontrados:</strong><br>__CAMPOS_ENCONTRADOS__</div>
    <div style="margin-top:8px"><strong style="font-size:12px">Pendentes:</strong><br>__CAMPOS_PENDENTES__</div>
    <div style="margin-top:8px"><strong style="font-size:12px">Revisar manualmente:</strong><br>__CAMPOS_REVISADOS__</div>
  </div>

  <div class="grid grid-2" style="margin-top:16px">
    <div class="card"><h3 style="margin-top:0">✅ Pontos fortes</h3><ul>__PONTOS_FORTES__</ul></div>
    <div class="card"><h3 style="margin-top:0">⚠️ Pontos fracos</h3><ul>__PONTOS_FRACOS__</ul></div>
    <div class="card"><h3 style="margin-top:0">🚩 Riscos</h3><ul>__RISCOS__</ul></div>
    <div class="card"><h3 style="margin-top:0">💡 Oportunidades</h3><ul>__OPORTUNIDADES__</ul></div>
  </div>
  <div class="grid grid-2" style="margin-top:16px">
    <div class="card"><h3 style="margin-top:0">Decisões necessárias</h3><ul>__DECISOES_NECESSARIAS__</ul></div>
    <div class="card"><h3 style="margin-top:0">Ações recomendadas</h3><ul>__ACOES_RECOMENDADAS__</ul></div>
  </div>
</section>

<section id="lotes">
  <h2>📦 Análise por Lote</h2>
  <div class="grid grid-2">
    __LOTES_HTML__
  </div>
</section>

<section id="financeiro">
  <h2>💰 Financeiro — DRE Consolidada</h2>
  <div class="grid grid-2">
    <div class="card">
      <h3 style="margin-top:0">Demonstrativo de Resultado</h3>
      __DRE_CONSOLIDADO__
    </div>
    <div class="card">
      <h3 style="margin-top:0">Indicadores (sobre fluxo de caixa)</h3>
      <div class="stat-grid" style="grid-template-columns:repeat(2,1fr)">
        <div class="stat"><span class="stat-label">Capital investido</span><span class="stat-value">__CAPITAL_INVESTIDO__</span></div>
        <div class="stat"><span class="stat-label">Margem operacional</span><span class="stat-value small">__MARGEM_MEDIA__</span></div>
        <div class="stat"><span class="stat-label">ROI (período)</span><span class="stat-value small">__ROI_MEDIO__</span></div>
        <div class="stat"><span class="stat-label">Payback</span><span class="stat-value small">__PAYBACK_MEDIO__</span></div>
        <div class="stat"><span class="stat-label">TIR (a.a.)</span><span class="stat-value small">__TIR_MEDIA__</span></div>
        <div class="stat"><span class="stat-label">VPL</span><span class="stat-value small">__VPL_TOTAL__</span></div>
        <div class="stat"><span class="stat-label">Valor residual líquido (pós-financiamento)</span><span class="stat-value small">__VALOR_RESIDUAL__</span></div>
        <div class="stat"><span class="stat-label">Reserva técnica sugerida</span><span class="stat-value small">__RESERVA_TECNICA__</span></div>
      </div>
      <p style="font-size:11px;color:var(--text-dim);margin-top:14px">
        Margem usa o Lucro Operacional (contábil, inclui depreciação). ROI/Payback/TIR/VPL usam o
        fluxo de caixa (Lucro Operacional + Depreciação, que não é desembolso), com o capital investido
        no início e o valor residual no fim do contrato.
      </p>
    </div>
  </div>
</section>

<section id="juridico">
  <h2>⚖️ Jurídico</h2>
  <div class="card">
    <h3 style="margin-top:0">Análise de risco (com página/trecho do edital)</h3>
    __ACHADOS_JURIDICOS_HTML__
  </div>
  <div class="grid grid-2" style="margin-top:16px">
    <div class="card">
      <h3 style="margin-top:0">Leis aplicáveis</h3>
      __LEIS_HTML__
    </div>
    <div class="card">
      <h3 style="margin-top:0">Acórdãos relevantes (TCU)</h3>
      __ACORDAOS_HTML__
    </div>
    <div class="card">
      <h3 style="margin-top:0">Checklist Jurídico</h3>
      <ul>__CHECKLIST_JURIDICO__</ul>
    </div>
    <div class="card">
      <h3 style="margin-top:0">Itens para esclarecimento / possíveis impugnações</h3>
      <ul>__ESCLARECIMENTOS__</ul>
    </div>
  </div>
</section>

<section id="operacional">
  <h2>🔧 Operacional</h2>
  <div class="grid grid-2">
    <div class="card">
      <h3 style="margin-top:0">Veículos por lote</h3>
      __VEICULOS_OP_HTML__
    </div>
    <div class="card">
      <h3 style="margin-top:0">Prazos e manutenção</h3>
      <p><strong>Prazo de entrega:</strong> __PRAZO_ENTREGA__</p>
      <p><strong>Manutenção:</strong> __MANUTENCAO_TXT__</p>
      <p><strong>Seguro:</strong> __SEGURO_TXT__</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0">Documentação exigida</h3>
      <ul>__DOCUMENTACAO_HTML__</ul>
      <h3>Exigências</h3>
      <ul>__EXIGENCIAS_HTML__</ul>
    </div>
    <div class="card">
      <h3 style="margin-top:0">Checklist Operacional</h3>
      <ul>__CHECKLIST_OPERACIONAL__</ul>
    </div>
  </div>
</section>

<section id="checklist">
  <h2>✅ O que preciso fazer</h2>
  <div class="card">
    <ul>__CHECKLIST_PRATICO__</ul>
  </div>
</section>

<section id="timeline">
  <h2>🗓️ Timeline do processo</h2>
  <div class="card">
    __TIMELINE_HTML__
  </div>
</section>

<section id="simulacao">
  <h2>🧮 Simulações Financeiras</h2>
  <div class="card">
    <div class="sim-grid">
      <div>
        <div class="sim-field">
          <label>Lote simulado</label>
          <select id="sim-lote">__LOTE_OPTIONS__</select>
        </div>
        <div class="sim-field"><label>Receita mensal (% da FIPE cheia) <span id="v-receitapct"></span></label>
          <input type="range" id="p-receitapct" min="0.02" max="0.12" step="0.001"></div>
        <div class="sim-field"><label>Desconto da montadora <span id="v-desconto"></span></label>
          <input type="range" id="p-desconto" min="0" max="0.40" step="0.01"></div>
        <div class="sim-field"><label>Entrada <span id="v-entrada"></span></label>
          <input type="range" id="p-entrada" min="0" max="1" step="0.05"></div>
        <div class="sim-field"><label>Taxa de juros a.m. <span id="v-juros"></span></label>
          <input type="range" id="p-juros" min="0" max="0.05" step="0.001"></div>
        <div class="sim-field"><label>Prazo do financiamento (meses) <span id="v-prazofin"></span></label>
          <input type="range" id="p-prazofin" min="12" max="72" step="1"></div>
        <div class="sim-field"><label>Seguro a.m. (% do valor) <span id="v-seguro"></span></label>
          <input type="range" id="p-seguro" min="0" max="0.01" step="0.0005"></div>
        <div class="sim-field"><label>Manutenção mensal (R$) <span id="v-manutencao"></span></label>
          <input type="range" id="p-manutencao" min="100" max="2000" step="50"></div>
        <div class="sim-field"><label>Pneus mensal (R$) <span id="v-pneus"></span></label>
          <input type="range" id="p-pneus" min="20" max="400" step="10"></div>
        <div class="sim-field"><label>Tributos (% da receita) <span id="v-tributos"></span></label>
          <input type="range" id="p-tributos" min="0" max="0.20" step="0.005"></div>
        <div class="sim-field"><label>Administração (% da receita) <span id="v-administracao"></span></label>
          <input type="range" id="p-administracao" min="0" max="0.15" step="0.005"></div>
        <div class="sim-field"><label>Custos operacionais mensal (R$) <span id="v-custosop"></span></label>
          <input type="range" id="p-custosop" min="0" max="500" step="10"></div>
        <div class="sim-field"><label>Valor residual <span id="v-residual"></span></label>
          <input type="range" id="p-residual" min="0" max="0.99" step="0.01"></div>
      </div>
      <div>
        <div class="sim-result-grid">
          <div class="sim-result"><span class="stat-label">Capital necessário</span><span class="stat-value" id="r-capital">—</span></div>
          <div class="sim-result"><span class="stat-label">Receita bruta</span><span class="stat-value" id="r-receita">—</span></div>
          <div class="sim-result"><span class="stat-label">Lucro operacional</span><span class="stat-value" id="r-lucro">—</span></div>
          <div class="sim-result"><span class="stat-label">Margem</span><span class="stat-value" id="r-margem">—</span></div>
          <div class="sim-result"><span class="stat-label">ROI (período)</span><span class="stat-value" id="r-roi">—</span></div>
          <div class="sim-result"><span class="stat-label">Payback</span><span class="stat-value" id="r-payback">—</span></div>
          <div class="sim-result"><span class="stat-label">TIR (a.a.)</span><span class="stat-value" id="r-tir">—</span></div>
          <div class="sim-result"><span class="stat-label">VPL</span><span class="stat-value" id="r-vpl">—</span></div>
        </div>
        <p style="color:var(--text-dim);font-size:12px;margin-top:16px">
          Recalcula automaticamente, usando a mesma fórmula de DRE do motor em Python
          (scripts/financial.py). Valores iniciais = premissas padrão da análise.
        </p>
      </div>
    </div>
  </div>
</section>

<section id="mercado">
  <h2>🌐 Inteligência de Mercado</h2>
  <div class="card market-card">
    <div class="lock">🔒</div>
    <p style="font-size:16px;color:var(--text)">__MARKET_MSG__</p>
    <p>A estrutura de dados (market.db) já está pronta para receber o módulo de benchmark sem alterações no restante do sistema.</p>
  </div>
</section>

</main>

<footer>Rota13 Bid Intelligence — Gerado automaticamente a partir do edital em PDF</footer>

<script id="analise-data" type="application/json">__ANALISE_JSON__</script>
<script>
const ANALISE = JSON.parse(document.getElementById('analise-data').textContent);
const LOTES = ANALISE.lotes;

function brl(v){
  if(v===null||v===undefined||isNaN(v)) return '—';
  const neg = v<0; v = Math.abs(v);
  return (neg?'-':'') + 'R$ ' + v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
}
function pct(v){ return (v===null||v===undefined||isNaN(v)) ? 'Não calculado' : (v*100).toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1})+'%'; }
function meses(v){ return (v===null||v===undefined||isNaN(v)) ? 'Não calculado' : v.toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1})+' meses'; }

function pmt(taxa, nper, pv){
  if(nper<=0) return 0;
  if(taxa===0) return pv/nper;
  return pv*taxa/(1-Math.pow(1+taxa,-nper));
}
function amortizacaoPrice(taxa, nperFinanciamento, pv, mesesPeriodo){
  const parcela = pmt(taxa, nperFinanciamento, pv);
  let saldo = pv, jurosTotal = 0;
  const meses = Math.max(0, Math.min(mesesPeriodo, nperFinanciamento));
  for(let i=0;i<meses;i++){
    const jurosMes = saldo*taxa;
    const principalMes = parcela - jurosMes;
    saldo = Math.max(0, saldo - principalMes);
    jurosTotal += jurosMes;
  }
  return {parcela, jurosTotal, saldoFinal: saldo};
}
function npv(taxa, fluxos){
  let s=0;
  for(let t=0;t<fluxos.length;t++) s += fluxos[t]/Math.pow(1+taxa,t);
  return s;
}
function irr(fluxos){
  let baixo=-0.9, alto=3.0;
  if(npv(baixo,fluxos)*npv(alto,fluxos) > 0) return null;
  let meio=0;
  for(let i=0;i<200;i++){
    meio=(baixo+alto)/2;
    const v = npv(meio, fluxos);
    if(Math.abs(v) < 1e-6) return meio;
    if(npv(baixo,fluxos)*v < 0) alto = meio; else baixo = meio;
  }
  return meio;
}

function calcularLote(lote, params){
  const quantidade = Math.max(1, lote.quantidade);
  const fipe = (lote.veiculo_referencia && lote.veiculo_referencia.fipe) || 80000;
  const prazoMeses = ANALISE.simulacao_base.prazo_contratual_meses;

  const precoCompra = fipe * (1 - params.desconto);
  const entradaTotal = precoCompra * params.entrada * quantidade;

  const receitaMensalUnit = params.receitaPctFipe * fipe;  // sobre 100% da FIPE, sem desconto
  const receitaBrutaTotal = receitaMensalUnit * quantidade * prazoMeses;

  const tributosMensalUnit = receitaMensalUnit * params.tributos;
  const seguroMensalUnit = precoCompra * params.seguro;
  const administracaoMensalUnit = receitaMensalUnit * params.administracao;
  const valorFinanciado = precoCompra * (1 - params.entrada);
  const amort = amortizacaoPrice(params.juros, params.prazofin, valorFinanciado, prazoMeses);
  const parcelaMensalUnit = amort.parcela;       // desembolso de caixa cheio
  const jurosTotalUnit = amort.jurosTotal;       // só juros vira despesa de DRE
  const saldoDevedorFinalUnit = amort.saldoFinal;

  const valorResidualUnit = precoCompra * params.residual;
  const depreciacaoMensalUnit = prazoMeses>0 ? (precoCompra - valorResidualUnit) / prazoMeses : 0;

  const tributosTotal = tributosMensalUnit * quantidade * prazoMeses;
  const seguroTotal = seguroMensalUnit * quantidade * prazoMeses;
  const manutencaoTotal = params.manutencao * quantidade * prazoMeses;
  const pneusTotal = params.pneus * quantidade * prazoMeses;
  const administracaoTotal = administracaoMensalUnit * quantidade * prazoMeses;
  const financeiroTotal = jurosTotalUnit * quantidade;
  const depreciacaoTotal = depreciacaoMensalUnit * quantidade * prazoMeses;
  const custosOpTotal = params.custosop * quantidade * prazoMeses;

  const custoOperacionalMensalUnitSemFinanceiro = seguroMensalUnit + params.manutencao + params.pneus
    + administracaoMensalUnit + params.custosop;
  const capitalGiroSugerido = custoOperacionalMensalUnitSemFinanceiro * quantidade * params.mesesCapitalGiro;
  const capitalNecessario = entradaTotal + capitalGiroSugerido;

  const lucroOperacional = receitaBrutaTotal - tributosTotal - seguroTotal - manutencaoTotal
    - pneusTotal - administracaoTotal - financeiroTotal - depreciacaoTotal - custosOpTotal;
  const margem = receitaBrutaTotal>0 ? lucroOperacional/receitaBrutaTotal : null;

  const fluxoCaixaMensal = (receitaMensalUnit - tributosMensalUnit - seguroMensalUnit - params.manutencao
    - params.pneus - administracaoMensalUnit - parcelaMensalUnit - params.custosop) * quantidade;
  const valorResidualTotal = valorResidualUnit * quantidade;
  const saldoDevedorFinalTotal = saldoDevedorFinalUnit * quantidade;
  const valorResidualLiquidoTotal = valorResidualTotal - saldoDevedorFinalTotal;

  let payback = null;
  if(capitalNecessario>0 && fluxoCaixaMensal>0) payback = capitalNecessario/fluxoCaixaMensal;

  let roi = null;
  if(capitalNecessario>0) roi = (fluxoCaixaMensal*prazoMeses + valorResidualLiquidoTotal - capitalNecessario)/capitalNecessario;

  let tirAnual = null, vpl = null;
  if(capitalNecessario>0){
    const fluxos = [-capitalNecessario];
    for(let i=0;i<prazoMeses;i++) fluxos.push(fluxoCaixaMensal);
    fluxos[fluxos.length-1] += valorResidualLiquidoTotal;
    const tirMensal = irr(fluxos);
    tirAnual = tirMensal!==null ? Math.pow(1+tirMensal,12)-1 : null;
    vpl = npv(params.juros, fluxos);
  }

  return {capitalNecessario, receitaBrutaTotal, lucroOperacional, margem, roi, payback, tirAnual, vpl};
}

const els = {
  lote: document.getElementById('sim-lote'),
  receitapct: document.getElementById('p-receitapct'), vReceitapct: document.getElementById('v-receitapct'),
  desconto: document.getElementById('p-desconto'), vDesconto: document.getElementById('v-desconto'),
  entrada: document.getElementById('p-entrada'), vEntrada: document.getElementById('v-entrada'),
  juros: document.getElementById('p-juros'), vJuros: document.getElementById('v-juros'),
  prazofin: document.getElementById('p-prazofin'), vPrazofin: document.getElementById('v-prazofin'),
  seguro: document.getElementById('p-seguro'), vSeguro: document.getElementById('v-seguro'),
  manutencao: document.getElementById('p-manutencao'), vManutencao: document.getElementById('v-manutencao'),
  pneus: document.getElementById('p-pneus'), vPneus: document.getElementById('v-pneus'),
  tributos: document.getElementById('p-tributos'), vTributos: document.getElementById('v-tributos'),
  administracao: document.getElementById('p-administracao'), vAdministracao: document.getElementById('v-administracao'),
  custosop: document.getElementById('p-custosop'), vCustosop: document.getElementById('v-custosop'),
  residual: document.getElementById('p-residual'), vResidual: document.getElementById('v-residual'),
};

function paramsParaLote(lote){
  const p = ANALISE.simulacao_base.parametros_padrao;
  const premissas = lote.financeiro.premissas;
  const fipe = (lote.veiculo_referencia && lote.veiculo_referencia.fipe) || 80000;
  // Sempre editável: se o edital tinha valor explícito, a % inicial é a taxa
  // implícita nesse valor sobre 100% da FIPE; se não tinha, começa no cenário Moderado (6%).
  const receitaPctFipe = fipe>0 ? (lote.financeiro.receita_mensal_unitaria / fipe) : p.receita_pct_fipe_am;
  return {
    desconto: p.desconto_montadora, entrada: p.entrada_pct, juros: p.taxa_juros_am,
    prazofin: premissas.prazo_financiamento_meses, seguro: p.seguro_pct_am,
    manutencao: premissas.manutencao_mensal_aplicada, pneus: premissas.pneus_mensal_aplicado,
    tributos: p.tributos_pct, administracao: p.administracao_pct,
    custosop: p.custos_operacionais_mensal, residual: premissas.valor_residual_pct_aplicado,
    receitaPctFipe: receitaPctFipe, mesesCapitalGiro: p.meses_capital_giro
  };
}

function setSliders(p){
  els.receitapct.value=p.receitaPctFipe;
  els.desconto.value=p.desconto; els.entrada.value=p.entrada; els.juros.value=p.juros;
  els.prazofin.value=p.prazofin; els.seguro.value=p.seguro; els.manutencao.value=p.manutencao;
  els.pneus.value=p.pneus; els.tributos.value=p.tributos; els.administracao.value=p.administracao;
  els.custosop.value=p.custosop; els.residual.value=p.residual;
}

function lerParams(){
  return {
    receitaPctFipe: parseFloat(els.receitapct.value),
    desconto: parseFloat(els.desconto.value), entrada: parseFloat(els.entrada.value),
    juros: parseFloat(els.juros.value), prazofin: parseInt(els.prazofin.value),
    seguro: parseFloat(els.seguro.value), manutencao: parseFloat(els.manutencao.value),
    pneus: parseFloat(els.pneus.value), tributos: parseFloat(els.tributos.value),
    administracao: parseFloat(els.administracao.value), custosop: parseFloat(els.custosop.value),
    residual: parseFloat(els.residual.value), mesesCapitalGiro: ANALISE.simulacao_base.parametros_padrao.meses_capital_giro
  };
}

function atualizarLabels(p){
  els.vReceitapct.textContent=pct(p.receitaPctFipe);
  els.vDesconto.textContent=pct(p.desconto); els.vEntrada.textContent=pct(p.entrada);
  els.vJuros.textContent=pct(p.juros); els.vPrazofin.textContent=p.prazofin+' meses';
  els.vSeguro.textContent=pct(p.seguro); els.vManutencao.textContent=brl(p.manutencao);
  els.vPneus.textContent=brl(p.pneus); els.vTributos.textContent=pct(p.tributos);
  els.vAdministracao.textContent=pct(p.administracao); els.vCustosop.textContent=brl(p.custosop);
  els.vResidual.textContent=pct(p.residual);
}

function recalcular(){
  const numero = parseInt(els.lote.value);
  const lote = LOTES.find(l => l.numero === numero);
  const p = lerParams();
  atualizarLabels(p);
  const res = calcularLote(lote, p);
  document.getElementById('r-capital').textContent = brl(res.capitalNecessario);
  document.getElementById('r-receita').textContent = brl(res.receitaBrutaTotal);
  document.getElementById('r-lucro').textContent = brl(res.lucroOperacional);
  document.getElementById('r-margem').textContent = pct(res.margem);
  document.getElementById('r-roi').textContent = pct(res.roi);
  document.getElementById('r-payback').textContent = meses(res.payback);
  document.getElementById('r-tir').textContent = pct(res.tirAnual);
  document.getElementById('r-vpl').textContent = brl(res.vpl);
}

['receitapct','desconto','entrada','juros','prazofin','seguro','manutencao','pneus','tributos','administracao','custosop','residual'].forEach(k=>{
  els[k].addEventListener('input', recalcular);
});
els.lote.addEventListener('change', () => {
  const lote = LOTES.find(l => l.numero === parseInt(els.lote.value));
  setSliders(paramsParaLote(lote));
  recalcular();
});

setSliders(paramsParaLote(LOTES[0]));
recalcular();
</script>
</body>
</html>
"""
