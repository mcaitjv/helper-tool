"""Tell Turkish from English. Only these two; anything else returns ""."""
import re

TURKISH_LETTERS = set("ğışöüçİĞŞÖÜÇ")
TURKISH = set("ve bir mi mı mu mü ne kim kaç hangi nerede nasıl zaman bu şu için ile var yok maç maçı "
              "lider lig puan son bugün yarın dün selam merhaba evet".split())
ENGLISH = set("the is are was were who what when where which how did does do of in on at for and "
              "to a an my me show next last top today yesterday tomorrow hello thanks any".split())


def detect(text: str) -> str:
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text)
    lower = [w.lower() for w in words]
    turkish = sum(w in TURKISH for w in lower) + sum(
        bool(TURKISH_LETTERS & set(w)) for w in words if w.islower())
    english = sum(w in ENGLISH for w in lower)
    if turkish == english:
        return ""
    return "Turkish" if turkish > english else "English"
