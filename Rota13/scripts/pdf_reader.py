"""Leitura de texto de editais em PDF."""
from pypdf import PdfReader


def extract_pages(pdf_path) -> list:
    """Extrai o texto do PDF preservando a divisão por página (lista, índice 0
    = página 1). Necessário para rastreabilidade (citar página/trecho de cada
    informação extraída)."""
    reader = PdfReader(str(pdf_path))
    paginas = []
    for page in reader.pages:
        try:
            paginas.append(page.extract_text() or "")
        except Exception:
            paginas.append("")
    return paginas


def extract_text(pdf_path) -> str:
    """Extrai todo o texto do PDF como uma única string (sem divisão por página)."""
    return "\n".join(extract_pages(pdf_path))


def count_pages(pdf_path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)
