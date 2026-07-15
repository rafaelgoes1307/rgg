"""Persistência do histórico de análises em historical/Ano/Pregao/."""
import re
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORICAL_DIR = BASE_DIR / "historical"


def _slug(texto: str) -> str:
    texto = re.sub(r"[^\w\s-]", "", texto, flags=re.UNICODE).strip().lower()
    texto = re.sub(r"[\s_]+", "-", texto)
    return texto[:80] or "edital"


def save_history(pdf_path: Path, dashboard_html: str, analise_json_str: str, ano: str, pregao_nome: str) -> Path:
    """Salva edital.pdf, dashboard.html e analise.json em historical/Ano/Pregao/."""
    pasta = HISTORICAL_DIR / ano / _slug(pregao_nome)
    pasta.mkdir(parents=True, exist_ok=True)

    shutil.copy2(pdf_path, pasta / "edital.pdf")
    (pasta / "dashboard.html").write_text(dashboard_html, encoding="utf-8")
    (pasta / "analise.json").write_text(analise_json_str, encoding="utf-8")

    return pasta
