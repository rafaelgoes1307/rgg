"""Base local de veículos: seed da tabela `veiculos` e consulta por categoria.

Carroceria (hatch/sedan/suv/pickup/van/onibus/caminhao/ambulancia) e
motorização (categoria: combustão comum, hibrido_phev, hibrido_hev,
eletrico) são dimensões INDEPENDENTES — um SUV PHEV não é a mesma coisa que
um Sedan PHEV, mesmo os dois sendo "categoria=hibrido_phev". Toda busca de
veículo aqui filtra pelas duas, nunca só pela categoria/motorização.
"""
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
               (marca, modelo, categoria, carroceria, ano, motor, combustivel, potencia, torque,
                consumo, tanque, porta_malas, capacidade, pneu, fipe, observacoes, garantia)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                v["marca"], v["modelo"], v["categoria"], v.get("carroceria", v["categoria"]), v["ano"],
                v["motor"], v["combustivel"], v["potencia"], v["torque"], v["consumo"],
                v["tanque"], v["porta_malas"], v["capacidade"], v["pneu"],
                v["fipe"], v["observacoes"], v.get("garantia", "Conforme fabricante"),
            ),
        )
    conn.commit()


def marcas_por_categoria(conn, categoria: str, carroceria: str = None, limite: int = 2) -> list:
    """Lista as marcas mais baratas (referência FIPE) disponíveis para a
    categoria/carroceria — usada para sugerir cotações concretas no checklist
    prático."""
    if carroceria:
        rows = conn.execute(
            "SELECT DISTINCT marca FROM veiculos WHERE categoria = ? AND carroceria = ? ORDER BY fipe ASC LIMIT ?",
            (categoria, carroceria, limite),
        ).fetchall()
        if rows:
            return [r["marca"] for r in rows]
    rows = conn.execute(
        "SELECT DISTINCT marca FROM veiculos WHERE categoria = ? ORDER BY fipe ASC LIMIT ?",
        (categoria, limite),
    ).fetchall()
    return [r["marca"] for r in rows]


def veiculo_referencia(conn, categoria: str, carroceria: str = None):
    """Retorna um veículo representativo da categoria+carroceria (usado como
    base de simulação). É sempre o mais barato dentro do que bate nos dois
    critérios — por isso o Dashboard também mostra alternativas (ver
    alternativas_veiculo) para o usuário poder corrigir manualmente quando a
    extração da carroceria não for confiável."""
    if carroceria:
        row = conn.execute(
            "SELECT * FROM veiculos WHERE categoria = ? AND carroceria = ? ORDER BY fipe ASC LIMIT 1",
            (categoria, carroceria),
        ).fetchone()
        if row:
            return dict(row)
    row = conn.execute(
        "SELECT * FROM veiculos WHERE categoria = ? ORDER BY fipe ASC LIMIT 1",
        (categoria,),
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM veiculos ORDER BY fipe ASC LIMIT 1").fetchone()
    return dict(row) if row else None


def alternativas_veiculo(conn, categoria: str, carroceria: str = None) -> list:
    """Lista TODOS os veículos cadastrados, com os que batem categoria+carroceria
    primeiro, depois só categoria, depois o resto — para o usuário escolher
    manualmente no Dashboard quando a extração automática não for confiável."""
    rows = conn.execute("SELECT * FROM veiculos ORDER BY fipe ASC").fetchall()
    veiculos = [dict(r) for r in rows]

    def chave(v):
        bate_os_dois = v["categoria"] == categoria and (carroceria is None or v["carroceria"] == carroceria)
        bate_categoria = v["categoria"] == categoria
        return (not bate_os_dois, not bate_categoria)

    veiculos.sort(key=chave)
    return veiculos
