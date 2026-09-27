import re
import unicodedata


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"\s+", " ", value).strip().upper()
    value = re.sub(r"^ASTR\.\s+", "ASTRONAUTA ", value)
    value = re.sub(r"^PROF\.\s+", "PROFESSORA ", value)
    value = re.sub(r"\bJR\.?$", "JUNIOR", value)
    return value


def supplier_identity(document: str | None, name: str | None, expense_id: int) -> dict:
    raw_document = (document or "").strip()
    normalized_name = normalize_name(name or "NÃO INFORMADO")
    digits = re.sub(r"\D", "", raw_document)

    if len(digits) == 14 and "*" not in raw_document:
        kind, normalized, key = "CNPJ", digits, f"CNPJ:{digits}"
    elif len(digits) == 11 and "*" not in raw_document:
        kind, normalized, key = "CPF", digits, f"CPF:{digits}"
    elif "*" in raw_document and digits:
        kind = "CPF_MASCARADO"
        normalized = raw_document
        key = f"CPF_MASCARADO:{raw_document}:{normalized_name}"
    elif raw_document:
        kind, normalized = "OUTRO", raw_document
        key = f"OUTRO:{raw_document}:{normalized_name}"
    else:
        kind, normalized = "AUSENTE", None
        key = f"AUSENTE:{normalized_name}:DESPESA:{expense_id}"

    return {
        "kind": kind,
        "normalized_document": normalized,
        "normalized_name": normalized_name,
        "key": key,
    }
