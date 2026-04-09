from main import _extract_receipt_fields


def test_extract_iban():
    text = """
    Tutar: 3.450,25 TL
    Tarih: 09.04.2026
    IBAN: TR12 3456 7890 1234 5678 9012 34
    """
    result = _extract_receipt_fields(text)
    assert result["iban"] == "TR123456789012345678901234"


def test_extract_receiver_name():
    text = """
    Alici: Ayse Demir
    Tutar: 120,00 TL
    """
    result = _extract_receipt_fields(text)
    assert result["receiver_name"] == "Ayse Demir"


def test_empty_text_returns_none_fields():
    result = _extract_receipt_fields("")
    assert result["sender_name"] is None
    assert result["receiver_name"] is None
    assert result["iban"] is None
