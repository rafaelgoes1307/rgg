"""Rota13 Bid Intelligence — MVP V1

Executar com: python main.py

Sobe um servidor web local (upload de edital pelo navegador) e também
processa automaticamente qualquer PDF já presente em uploads/. Toda análise
é salva no histórico (historical/Ano/Pregao/) e no banco (database/rota13.db).
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from scripts import db, fipe_stub, knowledge, market_stub, vehicles
from scripts.pipeline import processar_pdf
from scripts.webapp import run_server

UPLOADS_DIR = BASE_DIR / "uploads"


def _bootstrap():
    """Inicializa banco, seeds e estruturas auxiliares (idempotente)."""
    conn = db.init_db()
    vehicles.seed_vehicles(conn)
    knowledge.seed_knowledge(conn)
    market_stub.init_market_db()
    fipe_stub.init_fipe_structure()
    return conn


def _processar_uploads_existentes(conn):
    pdfs = sorted(UPLOADS_DIR.glob("*.pdf"))
    for pdf_path in pdfs:
        try:
            processar_pdf(conn, pdf_path)
        except Exception as e:
            print(f"   ❌ Erro ao processar {pdf_path.name}: {e}")


def main():
    print("=" * 60)
    print(" ROTA13 BID INTELLIGENCE — MVP V1")
    print("=" * 60)

    conn = _bootstrap()

    print(f"\nVerificando editais já presentes em {UPLOADS_DIR}/ ...")
    _processar_uploads_existentes(conn)
    conn.close()

    run_server()


if __name__ == "__main__":
    main()
