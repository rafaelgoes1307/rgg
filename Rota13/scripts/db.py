"""Camada de banco de dados: cria e conecta ao rota13.db (SQLite)."""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "rota13.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS licitacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_pdf TEXT,
    orgao TEXT,
    numero_processo TEXT,
    modalidade TEXT,
    objeto TEXT,
    data_analise TEXT,
    prazo_contratual_meses INTEGER,
    valor_estimado REAL,
    qtd_lotes INTEGER,
    qtd_itens INTEGER,
    score_geral REAL,
    go_no_go TEXT,
    nivel_risco TEXT,
    pasta_historico TEXT
);

CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    licitacao_id INTEGER REFERENCES licitacoes(id),
    numero INTEGER,
    descricao TEXT,
    quantidade INTEGER,
    categoria_veiculo TEXT,
    capital_necessario REAL,
    receita_estimada REAL,
    margem_estimada REAL,
    roi REAL,
    payback_meses REAL,
    risco TEXT
);

CREATE TABLE IF NOT EXISTS itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id INTEGER REFERENCES lotes(id),
    descricao TEXT,
    quantidade INTEGER,
    unidade TEXT,
    valor_unitario_estimado REAL
);

CREATE TABLE IF NOT EXISTS veiculos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marca TEXT,
    modelo TEXT,
    categoria TEXT,
    carroceria TEXT,
    ano INTEGER,
    motor TEXT,
    combustivel TEXT,
    potencia TEXT,
    torque TEXT,
    consumo TEXT,
    tanque TEXT,
    porta_malas TEXT,
    capacidade TEXT,
    pneu TEXT,
    fipe REAL,
    observacoes TEXT,
    garantia TEXT
);

CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj TEXT,
    razao_social TEXT,
    observacoes TEXT
);

CREATE TABLE IF NOT EXISTS historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    licitacao_id INTEGER REFERENCES licitacoes(id),
    ano TEXT,
    pasta TEXT,
    data_registro TEXT
);

CREATE TABLE IF NOT EXISTS fipe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_fipe TEXT,
    marca TEXT,
    modelo TEXT,
    ano_modelo INTEGER,
    valor REAL,
    mes_referencia TEXT,
    combustivel TEXT
);

CREATE TABLE IF NOT EXISTS leis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT,
    resumo TEXT,
    aplicacao_pratica TEXT,
    pontos_importantes TEXT,
    fonte TEXT,
    palavras_chave TEXT
);

CREATE TABLE IF NOT EXISTS acordaos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT,
    tribunal TEXT,
    tema TEXT,
    resumo TEXT,
    aplicacao_pratica TEXT,
    pontos_importantes TEXT,
    fonte TEXT,
    palavras_chave TEXT
);

CREATE TABLE IF NOT EXISTS manuais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT,
    categoria TEXT,
    resumo TEXT,
    aplicacao_pratica TEXT,
    pontos_importantes TEXT,
    fonte TEXT,
    palavras_chave TEXT
);

CREATE TABLE IF NOT EXISTS benchmark (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria_veiculo TEXT,
    orgao TEXT,
    valor_medio_mensal REAL,
    data_referencia TEXT,
    fonte TEXT
);
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
