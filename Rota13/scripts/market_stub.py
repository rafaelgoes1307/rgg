"""Estrutura da Inteligência de Mercado (implementação completa prevista para V2).

Cria apenas o esqueleto de market/market.db para que a V2 possa ligar o
módulo de benchmark (scraping do PNCP, comparação de preços entre órgãos)
sem precisar alterar o restante do sistema.
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MARKET_DB_PATH = BASE_DIR / "market" / "market.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS precos_mercado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria_veiculo TEXT,
    orgao TEXT,
    uf TEXT,
    valor_mensal REAL,
    data_referencia TEXT,
    fonte TEXT
);

CREATE TABLE IF NOT EXISTS editais_monitorados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_processo TEXT,
    orgao TEXT,
    status TEXT,
    data_coleta TEXT
);
"""


def init_market_db():
    """Cria o banco market.db vazio (estrutura pronta para V2)."""
    MARKET_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MARKET_DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
