"""Estrutura de snapshots da tabela FIPE.

Nesta versão apenas a estrutura é criada (datasets/fipe/AAAA-MM.sqlite +
current.sqlite). A atualização automática (scraping/API da FIPE) fica para
uma versão futura — ver knowledge/ e o módulo market/ para o mesmo padrão.
Mantém apenas os 3 snapshots mais recentes.
"""
import sqlite3
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FIPE_DIR = BASE_DIR / "datasets" / "fipe"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fipe (
    codigo_fipe TEXT,
    marca TEXT,
    modelo TEXT,
    ano_modelo INTEGER,
    combustivel TEXT,
    valor REAL,
    mes_referencia TEXT
);
"""


def _snapshot_atual_nome() -> str:
    hoje = date.today()
    return f"{hoje.year:04d}-{hoje.month:02d}.sqlite"


def init_fipe_structure():
    FIPE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = FIPE_DIR / _snapshot_atual_nome()
    current_path = FIPE_DIR / "current.sqlite"

    for path in (snapshot_path, current_path):
        if not path.exists():
            conn = sqlite3.connect(path)
            conn.executescript(SCHEMA)
            conn.commit()
            conn.close()

    _manter_ultimos_3_snapshots()


def _manter_ultimos_3_snapshots():
    snapshots = sorted(
        [p for p in FIPE_DIR.glob("*.sqlite") if p.name != "current.sqlite"]
    )
    excedentes = snapshots[:-3]
    for p in excedentes:
        p.unlink()
