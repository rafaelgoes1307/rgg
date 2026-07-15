"""Pipeline central de processamento de um edital (PDF -> Dashboard).

Usado tanto pelo modo batch (uploads/*.pdf via main.py) quanto pelo servidor
web interativo (scripts/webapp.py), para não duplicar a lógica.

Extração: tenta primeiro a IA local (Ollama); se indisponível ou falhar,
cai automaticamente para o extrator por regex (motor padrão, determinístico
e 100% rastreável). O cálculo financeiro é sempre feito em Python, nunca
pelo motor de extração.
"""
import json
import re
from datetime import date
from pathlib import Path

from . import ai_engine, analysis, dashboard, history
from .extractor import extract_all
from .pdf_reader import extract_pages

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"

RISCO_POR_FRACAO = [(0.7, "Baixo"), (0.4, "Médio")]


def _ano_do_processo(numero_processo: str) -> str:
    m = re.search(r"(20\d{2})", numero_processo)
    return m.group(1) if m else str(date.today().year)


def _nivel_risco_resumo(score_categorias: dict) -> str:
    c = score_categorias["riscos"]
    fracao = c["pontos"] / c["maximo"] if c["maximo"] else 0
    for limite, label in RISCO_POR_FRACAO:
        if fracao >= limite:
            return label
    return "Alto"


def _salvar_no_banco(conn, arquivo_pdf: str, analise: dict, pasta_historico: str, motor: str):
    r = analise["resumo_executivo"]
    nivel_risco = _nivel_risco_resumo(r["score_categorias"])
    cur = conn.execute(
        """INSERT INTO licitacoes
           (arquivo_pdf, orgao, numero_processo, modalidade, objeto, data_analise,
            prazo_contratual_meses, valor_estimado, qtd_lotes, qtd_itens,
            score_geral, go_no_go, nivel_risco, pasta_historico)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (arquivo_pdf, r["orgao"], r["numero_processo"], "Pregão Eletrônico", r["objeto"],
         date.today().isoformat(), r["prazo_contratual_meses"], r["valor_estimado"],
         r["qtd_lotes"], r["qtd_itens"], r["score_geral"], r["decisao"], nivel_risco,
         pasta_historico),
    )
    licitacao_id = cur.lastrowid

    for lote in analise["lotes"]:
        fin = lote["financeiro"]
        cur_lote = conn.execute(
            """INSERT INTO lotes
               (licitacao_id, numero, descricao, quantidade, categoria_veiculo,
                capital_necessario, receita_estimada, margem_estimada, roi, payback_meses, risco)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (licitacao_id, lote["numero"], lote["descricao"], lote["quantidade"],
             lote["categoria_veiculo"], fin["capital_necessario"], fin["receita_estimada"],
             fin["margem_estimada"], fin["roi"], fin["payback_meses"], fin["risco"]),
        )
        lote_id = cur_lote.lastrowid
        conn.execute(
            "INSERT INTO itens (lote_id, descricao, quantidade, unidade, valor_unitario_estimado) "
            "VALUES (?,?,?,?,?)",
            (lote_id, lote["descricao"], lote["quantidade"], "veículo", fin["receita_mensal_unitaria"]),
        )

    conn.execute(
        "INSERT INTO historico (licitacao_id, ano, pasta, data_registro) VALUES (?,?,?,?)",
        (licitacao_id, _ano_do_processo(r["numero_processo"]), pasta_historico, date.today().isoformat()),
    )
    conn.commit()


def processar_pdf(conn, pdf_path: Path, log=print) -> dict:
    """Roda o pipeline completo para um PDF e retorna um resumo do resultado."""
    log(f"📄 Processando: {pdf_path.name}")

    paginas = extract_pages(pdf_path)
    log(f"📖 PDF lido ({len(paginas)} página(s)).")
    if not "".join(paginas).strip():
        raise ValueError("Não foi possível extrair texto do PDF (arquivo digitalizado/imagem?).")

    log("🔎 Tentando extração via IA local (Ollama)...")
    dados = ai_engine.extract_with_ai(paginas)
    motor = "ia (Ollama local)"
    if dados is None:
        log("   ℹ️  IA local indisponível ou falhou — usando extrator por regex.")
        dados = extract_all(paginas)
        motor = "regex"
    else:
        log("   🤖 Extração feita pela IA local.")

    log(f"   Motor: {motor}")
    log(f"   Órgão: {dados['orgao']}")
    log(f"   Processo: {dados['numero_processo']}")
    log(f"   Lotes identificados: {dados['qtd_lotes']} | Itens: {dados['qtd_itens']}")

    log("🧮 Calculando DRE, score, jurídico e checklist de cada lote...")
    analise = analysis.build_analise(pdf_path.name, paginas, dados, conn)
    analise["meta"]["motor_extracao"] = motor

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_path = OUTPUT_DIR / "dashboard.html"
    analise_json_str = json.dumps(analise, ensure_ascii=False, indent=2)
    (OUTPUT_DIR / "analise.json").write_text(analise_json_str, encoding="utf-8")

    log("🎨 Gerando Dashboard HTML...")
    dashboard_html = dashboard.render(analise, dashboard_path)

    log("💾 Salvando no histórico e no banco...")
    ano = _ano_do_processo(analise["resumo_executivo"]["numero_processo"])
    pregao_nome = f"{analise['resumo_executivo']['numero_processo']}-{pdf_path.stem}"
    pasta = history.save_history(pdf_path, dashboard_html, analise_json_str, ano, pregao_nome)

    _salvar_no_banco(conn, pdf_path.name, analise, str(pasta), motor)

    r = analise["resumo_executivo"]
    log(f"   ✅ {r['decisao']} · Score {r['score_geral']}")
    log(f"   Dashboard: {dashboard_path}")
    log(f"   Histórico: {pasta}")

    return {
        "analise": analise,
        "dashboard_path": dashboard_path,
        "dashboard_html": dashboard_html,
        "pasta_historico": pasta,
        "motor": motor,
    }
