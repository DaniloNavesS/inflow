from jobs.attendance import DSF_SAMPLES, parse_attendance_pages, resolve_senator
from bronze.raw import canonical_json_bytes
from domain import supplier_identity


def test_supplier_without_document_does_not_collapse_distinct_expenses():
    first = supplier_identity(None, "Fornecedor sem documento", 10)
    second = supplier_identity(None, "Fornecedor sem documento", 11)
    assert first["key"] != second["key"]
    assert first["kind"] == second["kind"] == "AUSENTE"


def test_supplier_uses_complete_cnpj_as_identity():
    first = supplier_identity("12.345.678/0001-90", "Nome A", 10)
    second = supplier_identity("12345678000190", "Nome B", 11)
    assert first["key"] == second["key"] == "CNPJ:12345678000190"


def test_masked_cpf_includes_name_in_weak_identity():
    first = supplier_identity("***.123.456-**", "Pessoa A", 10)
    second = supplier_identity("***.123.456-**", "Pessoa B", 11)
    assert first["key"] != second["key"]
    assert first["kind"] == "CPF_MASCARADO"


def test_attendance_parser_keeps_presence_separate_from_vote():
    page = """
      REGISTRO   DE COMPARECIMENTO E VOTO
      UNIÃO            AC Alan Rick                        X    X
      PSB              MA Ana Paula Lobato                 X
    """
    rows = parse_attendance_pages([page], 76)
    assert [(row.name, row.vote_recorded) for row in rows] == [
        ("Alan Rick", True),
        ("Ana Paula Lobato", False),
    ]


def test_unresolved_name_is_not_attributed_to_a_senator():
    assert resolve_senator("Nome incerto", {}) == (None, "NAO_RESOLVIDA")


def test_document_abbreviations_resolve_without_fuzzy_matching():
    mapping = {"ASTRONAUTA MARCOS PONTES": {6009}, "PROFESSORA DORINHA SEABRA": {5386}}
    assert resolve_senator("Astr. Marcos Pontes", mapping) == (6009, "EXATA")
    assert resolve_senator("Prof. Dorinha Seabra", mapping) == (5386, "EXATA")


def test_viability_sample_has_three_distinct_deliberative_dates():
    assert len(DSF_SAMPLES) == 3
    assert len({sample["session_date"] for sample in DSF_SAMPLES}) == 3
    assert all("Deliberativa" in sample["session_type"] for sample in DSF_SAMPLES)


def test_bronze_json_is_canonical_for_stable_hashing():
    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes({"a": 1, "b": 2})
