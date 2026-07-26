"""
agents/finbert_agent.py
───────────────────────
FinBERT ile finansal metin analizi.
Claude'a bağlanmaz — tamamen yerel çalışır.
Çıktı: BULLISH / BEARISH / NOTR + güven skoru

Kalibrasyon notu:
  FinBERT hisse senedi verisiyle eğitilmiştir. Altın piyasasında
  bazı kalıplar ters çalışır (örn. "gold surges" → BEARISH).
  _altin_yonu_duzelt() bu hataları anahtar ifade eşleşmesiyle düzeltir.
"""

import subprocess
import json
import sys
import os


# FinBERT sanal ortamındaki Python
FINBERT_PYTHON = os.path.expanduser("~/finbert-env/bin/python3.12")

# FinBERT etiket → sistemimizin dili
_ETIKET_MAP = {
    "positive": "BULLISH",
    "negative": "BEARISH",
    "neutral":  "NOTR",
}

# ── Altın piyasası kalibrasyon listeleri ──────────────────────────────────────
# Her eşleşen ifade 1 puan verir; net puan yönü belirler.

_ALTIN_BULLISH_IFADELER = [
    # Dolar zayıflığı → altın için olumlu
    "dollar falls", "dollar weakens", "dollar drops", "dollar declines",
    "dollar tumbles", "dollar retreats", "dollar slips", "dollar weakness",
    "dollar index falls", "dollar index drops", "dollar index declines",
    "dollar index weakens", "dollar index lower",
    "weak dollar", "dxy falls", "dxy drops", "dxy declines", "dxy lower",
    "dxy down", "dxy weakens", "greenback falls", "greenback weakens",
    # Altın fiyatı yükseliyor
    "gold surges", "gold rises", "gold jumps", "gold rallies", "gold gains",
    "gold soars", "gold climbs", "gold advances", "gold higher", "gold up",
    "gold record", "gold hits record", "gold at record",
    "xau surges", "xau rises", "xau jumps", "xau rallies", "xau gains",
    # Fed gevşemesi / faiz indirimi → altın için olumlu
    "rate cut", "rate cuts", "rate reduction", "rates fall", "rates drop",
    "dovish", "fed pivot", "fed pauses", "fed pause", "lower rates",
    "rate cut expectations", "cut rates",
    # Güvenli liman talebi → altın için olumlu
    "safe haven", "safe-haven", "flight to safety", "flight to gold",
    "geopolitical tension", "geopolitical risk", "geopolitical uncertainty",
    "war escalat", "nuclear threat", "military conflict",
    "banking crisis", "financial crisis", "debt crisis", "bank failure",
    "uncertainty rises", "uncertainty grows",
    # Enflasyon yükseliyor → altın için olumlu (enflasyon kalkanı)
    "inflation rises", "inflation hot", "inflation beats", "inflation surges",
    "inflation accelerates", "inflation above", "inflation elevated", "high inflation",
    "inflation jumps", "inflation climbs", "inflation higher",
    "cpi beats", "cpi hot", "cpi rises", "cpi surges", "cpi above",
    "cpi higher", "cpi elevated", "cpi jumps",
    "pce rises", "pce hot", "pce beats",
    # Tahvil faizleri düşüyor → altın için olumlu
    "yields fall", "yields decline", "yields drop", "yields lower",
    "bond yields fall", "treasury yields fall", "yields retreat",
]

_ALTIN_BEARISH_IFADELER = [
    # Dolar güçleniyor → altın için olumsuz
    "dollar rises", "dollar gains", "dollar surges", "dollar strengthens",
    "dollar strength", "dollar rallies", "strong dollar", "dollar higher",
    "dollar up", "dollar advances", "dollar climbs",
    "dxy rises", "dxy gains", "dxy surges", "dxy higher", "dxy up",
    "dxy strengthens", "greenback rises", "greenback gains",
    # Altın fiyatı düşüyor
    "gold falls", "gold drops", "gold slips", "gold tumbles", "gold declines",
    "gold retreats", "gold lower", "gold pressured", "gold weakens",
    "gold loses", "gold down", "gold slides",
    "xau falls", "xau drops", "xau declines", "xau lower", "xau slips",
    # Fed sıkılaştırması / faiz artışı → altın için olumsuz
    "rate hike", "rate hikes", "rate increase", "rates rise", "rates higher",
    "hawkish", "tightening", "higher for longer", "raise rates",
    "raises interest rate", "raises rates", "raised rates", "raising rates",
    "rate hike expectations", "hike rates",
    # Faiz indirimi beklentisi azalıyor → altın için olumsuz
    "rate cut hopes fade", "rate cut bets fade", "rate cut expectations fade",
    "rate cut hopes dim", "rate cut odds fall", "fewer rate cuts",
    "pushes back rate cut", "delays rate cut", "no rate cut",
    # Enflasyon düşüyor → altın için olumsuz (daha az korunma ihtiyacı)
    "inflation falls", "inflation drops", "inflation cools", "inflation eases",
    "inflation slows", "inflation below", "inflation declines", "inflation retreats",
    "inflation tame", "low inflation", "inflation subsides",
    "cpi falls", "cpi misses", "cpi cools", "cpi eases", "cpi below",
    "cpi lower", "cpi slows", "cpi declines",
    # Tahvil faizleri yükseliyor → altın için olumsuz
    "yields rise", "yields higher", "yields surge", "yields climb",
    "bond yields rise", "treasury yields rise", "yields jump",
    # Risk iştahı artıyor → güvenli limana ihtiyaç azalıyor
    "risk on", "risk-on", "risk appetite", "risk sentiment improves",
    "stocks rally", "equities rally", "stocks surge",
    "weighs on gold", "pressures gold", "drags gold lower",
    # İstihdam güçlü → Fed sıkılaştırması baskısı
    "beats expectations", "jobs beat", "payrolls beat", "nfp beats",
    "strong jobs", "strong employment", "economy beats",
]


def _altin_yonu_duzelt(metin: str, sentiment: str, guven: float) -> tuple[str, float, bool]:
    """
    FinBERT sonucunu altın piyasası dinamikleriyle kalibre eder.

    Altın fiyatıyla ilişkili kalıp ifadeler sayılır; net sayı yönü belirler.
    Kalıp bulunamazsa FinBERT sonucu değişmeden döner.

    Returns: (sentiment, güven, duzeltildi_mi)
    """
    kucuk = metin.lower()
    bullish_puan = sum(1 for ifade in _ALTIN_BULLISH_IFADELER if ifade in kucuk)
    bearish_puan = sum(1 for ifade in _ALTIN_BEARISH_IFADELER if ifade in kucuk)

    if bullish_puan == 0 and bearish_puan == 0:
        return sentiment, guven, False  # Bilinen kalıp yok → FinBERT'e güven

    if bullish_puan > bearish_puan:
        yeni_sentiment = "BULLISH"
    elif bearish_puan > bullish_puan:
        yeni_sentiment = "BEARISH"
    else:
        yeni_sentiment = "NOTR"  # Eşit güç → tarafsız

    duzeltildi = yeni_sentiment != sentiment
    if duzeltildi:
        # Düzeltme yapıldı; güveni kalibrasyon gücüyle ölçekle
        puan_farki = abs(bullish_puan - bearish_puan)
        yeni_guven = min(0.90, 0.60 + puan_farki * 0.10)
    else:
        # Zaten doğru yöndeydi; güveni biraz artır
        yeni_guven = min(1.0, guven + 0.05)

    return yeni_sentiment, round(yeni_guven, 4), duzeltildi


def _finbert_subprocess(metinler: list[str]) -> list[dict]:
    """
    FinBERT'i ayrı bir Python sürecinde çalıştırır.
    Ana bot gold-bot venv'inde, FinBERT finbert-env'de olduğu için
    subprocess ile köprü kuruyoruz.
    """
    kod = """
import sys, json
from transformers import pipeline
import warnings
warnings.filterwarnings("ignore")

metinler = json.loads(sys.argv[1])
classifier = pipeline(
    "text-classification",
    model="ProsusAI/finbert",
    truncation=True,
    max_length=512,
)
sonuclar = classifier(metinler)
print(json.dumps(sonuclar))
"""
    proc = subprocess.run(
        [FINBERT_PYTHON, "-c", kod, json.dumps(metinler)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"FinBERT subprocess hatası: {proc.stderr[-300:]}")

    # Son satır JSON çıktısı
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("["):
            return json.loads(line)

    raise ValueError(f"FinBERT çıktısı ayrıştırılamadı: {proc.stdout[-200:]}")


def analiz_et(metin: str) -> dict:
    """
    Tek metin analiz eder.

    Dönüş:
    {
        "durum":     "ok" | "hata",
        "sentiment": "BULLISH" | "BEARISH" | "NOTR",
        "guven":     0.0–1.0,
        "ham_etiket": "positive" | "negative" | "neutral",
        "mesaj":     str  (sadece hata durumunda)
    }
    """
    try:
        sonuclar = _finbert_subprocess([metin])
        s = sonuclar[0]
        etiket   = s["label"].lower()
        ham_sent = _ETIKET_MAP.get(etiket, "NOTR")
        ham_guven = round(float(s["score"]), 4)

        sentiment, guven, duzeltildi = _altin_yonu_duzelt(metin, ham_sent, ham_guven)
        return {
            "durum":       "ok",
            "sentiment":   sentiment,
            "guven":       guven,
            "ham_etiket":  etiket,
            "ham_sentiment": ham_sent,
            "duzeltildi":  duzeltildi,
        }
    except Exception as e:
        return {
            "durum":       "hata",
            "sentiment":   "NOTR",
            "guven":       0.0,
            "ham_etiket":  "neutral",
            "ham_sentiment": "NOTR",
            "duzeltildi":  False,
            "mesaj":       str(e),
        }


def toplu_analiz_et(metinler: list[str]) -> list[dict]:
    """
    Birden fazla metni tek subprocess çağrısıyla analiz eder.
    Her metin için analiz_et() ile aynı formatta dict döner.
    """
    if not metinler:
        return []
    try:
        sonuclar = _finbert_subprocess(metinler)
        cikti = []
        for metin, s in zip(metinler, sonuclar):
            etiket    = s["label"].lower()
            ham_sent  = _ETIKET_MAP.get(etiket, "NOTR")
            ham_guven = round(float(s["score"]), 4)
            sentiment, guven, duzeltildi = _altin_yonu_duzelt(metin, ham_sent, ham_guven)
            cikti.append({
                "durum":         "ok",
                "sentiment":     sentiment,
                "guven":         guven,
                "ham_etiket":    etiket,
                "ham_sentiment": ham_sent,
                "duzeltildi":    duzeltildi,
            })
        return cikti
    except Exception as e:
        return [
            {"durum": "hata", "sentiment": "NOTR", "guven": 0.0,
             "ham_etiket": "neutral", "ham_sentiment": "NOTR",
             "duzeltildi": False, "mesaj": str(e)}
            for _ in metinler
        ]


def ozet_sentiment(sonuclar: list[dict]) -> dict:
    """
    Birden fazla FinBERT sonucunu tek skora indirger.
    Güven ağırlıklı ortalama alır.

    Dönüş:
    {
        "sentiment":   "BULLISH" | "BEARISH" | "NOTR",
        "haber_skoru": -15.0 – +15.0,
        "guven_ort":   0.0–1.0,
        "bullish_adet": int,
        "bearish_adet": int,
        "notr_adet":    int,
    }
    """
    bullish = bearish = notr = 0
    agirlikli_skor = 0.0
    toplam_agirlik = 0.0

    for s in sonuclar:
        if s["durum"] != "ok":
            continue
        g = s["guven"]
        if s["sentiment"] == "BULLISH":
            bullish += 1
            agirlikli_skor  += g
            toplam_agirlik  += g
        elif s["sentiment"] == "BEARISH":
            bearish += 1
            agirlikli_skor  -= g
            toplam_agirlik  += g
        else:
            notr += 1
            toplam_agirlik  += g * 0.3   # nötr hafif ağırlık

    if toplam_agirlik == 0:
        return {
            "sentiment": "NOTR", "haber_skoru": 0.0, "guven_ort": 0.0,
            "bullish_adet": 0, "bearish_adet": 0, "notr_adet": 0,
        }

    net_skor  = agirlikli_skor / toplam_agirlik   # -1 … +1
    haber_skoru = round(net_skor * 15, 2)          # -15 … +15 aralığına ölçekle
    guven_ort   = round(toplam_agirlik / len(sonuclar), 4)

    if haber_skoru > 2:
        sentiment = "BULLISH"
    elif haber_skoru < -2:
        sentiment = "BEARISH"
    else:
        sentiment = "NOTR"

    return {
        "sentiment":    sentiment,
        "haber_skoru":  haber_skoru,
        "guven_ort":    guven_ort,
        "bullish_adet": bullish,
        "bearish_adet": bearish,
        "notr_adet":    notr,
    }


if __name__ == "__main__":
    # (metin, beklenen_gold_sentiment)
    TEST_SETI = [
        # BULLISH beklenen
        ("Gold surges as dollar weakens amid geopolitical tensions",    "BULLISH"),
        ("Safe haven demand boosts gold as geopolitical risks rise",    "BULLISH"),
        ("Federal Reserve signals rate cuts ahead, gold jumps",         "BULLISH"),
        ("CPI comes in hot, gold surges on inflation hedge demand",     "BULLISH"),
        ("Dollar index falls to multi-month low amid risk aversion",    "BULLISH"),
        ("Banking crisis fears push investors toward safe haven assets", "BULLISH"),
        ("Dovish Fed comments send gold higher",                        "BULLISH"),
        ("Inflation rises above 4%, gold rallies as hedge demand grows","BULLISH"),
        ("Treasury yields fall sharply, gold climbs to 3-month high",   "BULLISH"),
        ("War escalation drives safe haven demand for precious metals",  "BULLISH"),
        # BEARISH beklenen
        ("Federal Reserve raises interest rates to combat inflation",   "BEARISH"),
        ("Dollar strengthens as US economy beats expectations",         "BEARISH"),
        ("Gold falls as risk appetite improves on trade deal news",     "BEARISH"),
        ("Gold tumbles as Fed signals hawkish stance",                  "BEARISH"),
        ("Inflation cools to 2% target, rate cut hopes fade",          "BEARISH"),
        ("Risk-on sentiment weighs on safe haven gold",                 "BEARISH"),
        ("DXY surges to 6-month high, gold retreats sharply",          "BEARISH"),
        ("Rate hike expectations push gold lower",                      "BEARISH"),
        ("CPI misses estimates, gold falls on rate cut delay",          "BEARISH"),
        ("Treasury yields rise to 5%, dollar gains, gold drops",       "BEARISH"),
        # NOTR beklenen
        ("Gold traders await Fed decision next week",                   "NOTR"),
        ("Mixed signals in gold market as investors weigh risks",       "NOTR"),
    ]

    import json as _json

    print("=== FİNBERT ALTIN KALİBRASYON TESTİ ===\n")
    print(f"{'Metin':<62} {'Beklenen':<10} {'Sonuç':<10} {'Ham':<10} {'Düz?'}")
    print("-" * 110)

    sonuclar = toplu_analiz_et([m for m, _ in TEST_SETI])

    dogru = yanlis = 0
    duzeltme_sayisi = 0
    for (metin, beklenen), s in zip(TEST_SETI, sonuclar):
        isabet = "✓" if s["sentiment"] == beklenen else "✗"
        if s["sentiment"] == beklenen:
            dogru += 1
        else:
            yanlis += 1
        if s.get("duzeltildi"):
            duzeltme_sayisi += 1
        print(
            f"{isabet} {metin[:60]:<61} "
            f"{beklenen:<10} {s['sentiment']:<10} "
            f"{s.get('ham_sentiment','?'):<10} "
            f"{'DÜZELTILDI' if s.get('duzeltildi') else ''}"
        )

    print(f"\nDoğruluk: {dogru}/{dogru+yanlis}  ({dogru/(dogru+yanlis)*100:.0f}%)")
    print(f"Kalibrasyon düzeltmesi yapılan: {duzeltme_sayisi} cümle")

    print("\n--- Özet sentiment (tüm test seti) ---")
    print(_json.dumps(ozet_sentiment(sonuclar), indent=2, ensure_ascii=False))
