import pytest

from helper.language import detect


@pytest.mark.parametrize("text, language", [
    ("Who is top scorer in the Premier League?", "English"),
    ("Which Premier League matches are today?", "English"),
    ("When does Fenerbahçe play next?", "English"),   # a Turkish name in English
    ("How did Beşiktaş do?", "English"),
    ("Arsenal'in teknik direktörü kim?", "Turkish"),
    ("Türkiye'nin sıradaki maçı ne zaman?", "Turkish"),
    ("Premier Lig puan durumu nedir?", "Turkish"),
    ("Bugün hangi maçlar var?", "Turkish"),
    ("Arsenal", ""), ("", ""), ("¿Quién lidera?", ""),
])
def test_detect(text, language):
    assert detect(text) == language
