"""
claude_istemci.py
─────────────────
Tek Claude istemcisi + ortak yanıt ayrıştırma.

Önceden 6 ayrı yerde `anthropic.Anthropic()` kuruluyordu ve her ajan
"ANAHTAR: değer" satırlarını kendi kopyaladığı döngüyle ayrıştırıyordu.
Model kimlikleri de dört dosyaya dağılmıştı.

Burada tek yerde toplanır:
  istemci()            — süreç başına tek istemci
  sor()                — çağrı yapar, ham metni döndürür
  alanlari_ayristir()  — "SINYAL: GUCLU_AL" tarzı satırları şemaya göre okur
  json_ayristir()      — ```json çitlerini temizleyip JSON'a çevirir
"""
import json

import anthropic

import config

_istemci: anthropic.Anthropic | None = None


def istemci() -> anthropic.Anthropic:
    """Süreç başına tek istemci — ilk çağrıda kurulur."""
    global _istemci
    if _istemci is None:
        _istemci = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _istemci


def sor(prompt: str, sistem: str, model: str | None = None,
        max_tokens: int = 1000, araclar: list | None = None) -> str:
    """
    Claude'a tek mesajlık soru sorar ve yanıtın düz metnini döndürür.

    Yanıttaki tüm metin blokları birleştirilir; yanıt birden fazla bloktan
    gelebiliyor (thinking + text, web arama sonuçları vb.).

    MAX_TOKENS UYARISI (2026-07-26'da öğrenildi)
        claude-sonnet-5 varsayılan olarak bir `thinking` bloğu üretir ve bu
        token'lar max_tokens bütçesinden düşer. Bütçe darsa metin bloğu
        kesilir veya hiç üretilmez — `sor()` boş string döner, ajan da
        sessizce varsayılanına düşer.

        Canlı ön kontrolde tam olarak bu yaşandı: max_tokens=150 ile
        technical_agent boş yanıt aldı, risk_agent'ın yanıtı ortadan
        kesildi. Bütçeyi düşünme payını da kapsayacak kadar geniş tut.
    """
    parametreler = {
        "model": model or config.MODEL_ANALIZ,
        "max_tokens": max_tokens,
        "system": sistem,
        "messages": [{"role": "user", "content": prompt}],
    }
    if araclar:
        parametreler["tools"] = araclar

    yanit = istemci().messages.create(**parametreler)
    return "".join(
        blok.text for blok in yanit.content
        if getattr(blok, "text", None)
    ).strip()


def alanlari_ayristir(ham: str, sema: dict[str, type]) -> dict:
    """
    "ANAHTAR: değer" satırlarını şemaya göre ayrıştırır.

    sema örneği: {"SINYAL": str, "SL_FIYAT": float}

    Dönüştürülemeyen değer sonuca hiç konmaz — böylece çağıran
    `.get(anahtar, varsayilan)` ile kendi varsayılanını koruyabilir.
    """
    sonuc: dict = {}
    for satir in ham.split("\n"):
        satir = satir.strip()
        for anahtar, tip in sema.items():
            on_ek = f"{anahtar}:"
            if satir.startswith(on_ek):
                deger = satir[len(on_ek):].strip()
                try:
                    sonuc[anahtar] = tip(deger)
                except (ValueError, TypeError):
                    pass   # bozuk değer → varsayılan korunur
                break
    return sonuc


def json_ayristir(ham: str) -> dict:
    """Markdown kod çitlerini temizleyip JSON'a çevirir."""
    temiz = ham.replace("```json", "").replace("```", "").strip()
    return json.loads(temiz)
