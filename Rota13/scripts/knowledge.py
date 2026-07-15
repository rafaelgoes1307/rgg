"""Base de conhecimento: parse dos arquivos markdown em knowledge/ e casamento
por palavra-chave com o conteúdo do edital, para montar a seção Jurídico do
Dashboard (leis aplicáveis, acórdãos relevantes, checklists)."""
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _parse_frontmatter(raw: str) -> dict:
    campos = {}
    for linha in raw.splitlines():
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        campos[chave.strip()] = valor.strip()
    return campos


def _parse_sections(corpo: str) -> dict:
    partes = SECTION_RE.split(corpo)
    # partes = [texto_antes, titulo1, corpo1, titulo2, corpo2, ...]
    secoes = {}
    for i in range(1, len(partes), 2):
        titulo = partes[i].strip().lower()
        conteudo = partes[i + 1].strip() if i + 1 < len(partes) else ""
        secoes[titulo] = conteudo
    return secoes


def _parse_doc(path: Path) -> dict:
    texto = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(texto)
    if not m:
        return None
    meta = _parse_frontmatter(m.group(1))
    secoes = _parse_sections(m.group(2))
    return {
        "titulo": meta.get("titulo", path.stem),
        "categoria": meta.get("categoria", "manual"),
        "numero": meta.get("numero", ""),
        "tema": meta.get("tema", ""),
        "palavras_chave": meta.get("palavras_chave", ""),
        "fonte": meta.get("fonte", ""),
        "resumo": secoes.get("resumo", ""),
        "aplicacao_pratica": secoes.get("aplicação prática", secoes.get("aplicacao pratica", "")),
        "pontos_importantes": secoes.get("pontos importantes", ""),
    }


def load_all_docs() -> list:
    docs = []
    for path in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        doc = _parse_doc(path)
        if doc:
            docs.append(doc)
    return docs


def seed_knowledge(conn):
    """Popula leis / acordaos / manuais a partir dos arquivos markdown, se vazias."""
    total = conn.execute(
        "SELECT (SELECT COUNT(*) FROM leis) + (SELECT COUNT(*) FROM acordaos) + (SELECT COUNT(*) FROM manuais)"
    ).fetchone()[0]
    if total > 0:
        return
    for doc in load_all_docs():
        if doc["categoria"] == "legislacao":
            conn.execute(
                "INSERT INTO leis (nome, resumo, aplicacao_pratica, pontos_importantes, fonte, palavras_chave) "
                "VALUES (?,?,?,?,?,?)",
                (doc["titulo"], doc["resumo"], doc["aplicacao_pratica"], doc["pontos_importantes"],
                 doc["fonte"], doc["palavras_chave"]),
            )
        elif doc["categoria"] == "acordao":
            conn.execute(
                "INSERT INTO acordaos (numero, tribunal, tema, resumo, aplicacao_pratica, pontos_importantes, "
                "fonte, palavras_chave) VALUES (?,?,?,?,?,?,?,?)",
                (doc["numero"], "TCU", doc["tema"], doc["resumo"], doc["aplicacao_pratica"],
                 doc["pontos_importantes"], doc["fonte"], doc["palavras_chave"]),
            )
        else:
            conn.execute(
                "INSERT INTO manuais (titulo, categoria, resumo, aplicacao_pratica, pontos_importantes, fonte, "
                "palavras_chave) VALUES (?,?,?,?,?,?,?)",
                (doc["titulo"], doc["categoria"], doc["resumo"], doc["aplicacao_pratica"],
                 doc["pontos_importantes"], doc["fonte"], doc["palavras_chave"]),
            )
    conn.commit()


def _bate_palavra_chave(palavras_chave: str, texto_lower: str) -> bool:
    termos = [t.strip().lower() for t in palavras_chave.split(",") if t.strip()]
    return any(t in texto_lower for t in termos)


def match_juridico(conn, texto_edital: str) -> dict:
    """Seleciona leis/acórdãos/manuais relevantes com base no texto do edital."""
    texto_lower = texto_edital.lower()

    leis = [dict(r) for r in conn.execute("SELECT * FROM leis").fetchall()]
    acordaos = [dict(r) for r in conn.execute("SELECT * FROM acordaos").fetchall()]
    manuais = [dict(r) for r in conn.execute("SELECT * FROM manuais").fetchall()]

    # Lei 14.133 é sempre aplicável (base geral de licitações)
    leis_aplicaveis = [l for l in leis if "14.133" in l["nome"] or _bate_palavra_chave(l["palavras_chave"], texto_lower)]
    acordaos_relevantes = [a for a in acordaos if _bate_palavra_chave(a["palavras_chave"], texto_lower)] or acordaos
    manuais_relevantes = [m for m in manuais if _bate_palavra_chave(m["palavras_chave"], texto_lower)] or manuais

    checklist = [
        "Conferir se há franquia de KM definida e valor do KM excedente",
        "Conferir índice de reajuste anual e cláusula de reequilíbrio (art. 124-125, Lei 14.133)",
        "Conferir matriz de riscos e responsabilidade por sinistros",
        "Conferir exigência de veículo reserva/substituto e prazo de substituição",
        "Conferir percentual de multa e hipóteses de rescisão unilateral",
        "Conferir garantia contratual exigida (art. 96-98, Lei 14.133)",
        "Conferir benefícios de ME/EPP aplicáveis (LC 123/2006), se houver",
    ]

    itens_esclarecimento = [
        "Solicitar esclarecimento sobre metodologia da pesquisa de preços, se não estiver explícita",
        "Solicitar esclarecimento sobre franquia de KM, se omissa no edital",
        "Solicitar esclarecimento sobre índice de reajuste, se não previsto",
    ]

    return {
        "leis_aplicaveis": leis_aplicaveis,
        "acordaos_relevantes": acordaos_relevantes[:4],
        "manuais_relevantes": manuais_relevantes[:4],
        "checklist_juridico": checklist,
        "itens_esclarecimento": itens_esclarecimento,
    }
