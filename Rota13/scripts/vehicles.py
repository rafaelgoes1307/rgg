"""Base local de veículos: seed da tabela `veiculos` e consulta por categoria."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VEICULOS_JSON = BASE_DIR / "datasets" / "vehicles" / "veiculos.json"


def seed_vehicles(conn):
    """Popula a tabela veiculos a partir do JSON local, apenas se estiver vazia."""
    cur = conn.execute("SELECT COUNT(*) FROM veiculos")
    if cur.fetchone()[0] > 0:
        return
    with open(VEICULOS_JSON, encoding="utf-8") as f:
        veiculos = json.load(f)
    for v in veiculos:
        conn.execute(
            """INSERT INTO veiculos
               (marca, modelo, categoria, ano, motor, combustivel, potencia, torque,
                consumo, tanque, porta_malas, capacidade, pneu, fipe, observacoes, garantia)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                v["marca"], v["modelo"], v["categoria"], v["ano"], v["motor"],
                v["combustivel"], v["potencia"], v["torque"], v["consumo"],
                v["tanque"], v["porta_malas"], v["capacidade"], v["pneu"],
                v["fipe"], v["observacoes"], v.get("garantia", "Conforme fabricante"),
            ),
        )
    conn.commit()


def marcas_por_categoria(conn, categoria: str, limite: int = 2) -> list:
    """Lista as marcas mais baratas (referência FIPE) disponíveis para a categoria —
    usada para sugerir cotações concretas no checklist prático."""
    rows = conn.execute(
        "SELECT DISTINCT marca FROM veiculos WHERE categoria = ? ORDER BY fipe ASC LIMIT ?",
        (categoria, limite),
    ).fetchall()
    return [r["marca"] for r in rows]


def veiculo_referencia(conn, categoria: str):
    """Retorna um veículo representativo da categoria (usado como base de simulação).
    É sempre o mais barato — por isso o Dashboard mostra alternativas
    (ver alternativas_veiculo) para o usuário poder corrigir manualmente
    quando o mais barato não bate com a especificação técnica real do lote."""
    row = conn.execute(
        "SELECT * FROM veiculos WHERE categoria = ? ORDER BY fipe ASC LIMIT 1",
        (categoria,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM veiculos ORDER BY fipe ASC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def alternativas_veiculo(conn, categoria: str) -> list:
    """Lista TODOS os veículos cadastrados, com os da mesma categoria de
    motorização primeiro — para o usuário escolher manualmente no Dashboard
    quando o "mais barato da categoria" não bate com a especificação real
    (ex.: categoria certa mas carroceria errada, sedan vs SUV). Mostrar todos
    (não só a mesma categoria) é proposital: a categoria automática pode
    estar errada, e é exatamente esse caso que o seletor precisa cobrir."""
    rows = conn.execute("SELECT * FROM veiculos ORDER BY fipe ASC").fetchall()
    veiculos = [dict(r) for r in rows]
    veiculos.sort(key=lambda v: v["categoria"] != categoria)
    return veiculos
