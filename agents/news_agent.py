import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedparser
import anthropic
from datetime import datetime, timezone
import config
from agents import finbert_agent

# ──────────────────────────────────────────
# Modül seviyesi hafıza
# ──────────────────────────────────────────
RSS_FEEDLER = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.kitco.com/rss/",
    "https://www.gold.org/goldhub/rss",
]

ALTIN_KELIMELER = [
    "gold", "xau", "fed", "federal reserve",
    "interest rate", "inflation", "cpi", "dollar",
    "altın", "faiz",
]

_son_kontrol: dict[str, datetime] = {}   # feed_url → son kontrol zamanı
_gorulmus_basliklar: set = set()          # daha önce işlenen başlıklar
_haber_hafizasi: list = []               # son 10 işlenmiş haber


# ──────────────────────────────────────────
# Yardımcı fonksiyonlar
# ──────────────────────────────────────────
def _zaman_carpani(haber_zamani: datetime) -> float:
    simdi = datetime.now(timezone.utc)
    if haber_zamani.tzinfo is None:
        haber_zamani = haber_zamani.replace(tzinfo=timezone.utc)
    fark_saat = (simdi - haber_zamani).total_seconds() / 3600

    if fark_saat <= 1:
        return 1.0
    elif fark_saat <= 4:
        return 0.7
    elif fark_saat <= 24:
        return 0.4
    else:
        return 0.1


def _altin_haberi_mi(baslik: str) -> bool:
    kucuk = baslik.lower()
    return any(k in kucuk for k in ALTIN_KELIMELER)


def _parse_entry_time(entry) -> datetime:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            import time as _time
            return datetime.fromtimestamp(_time.mktime(t), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _etki_tahmini(baslik: str, ozet: str = "") -> int:
    """
    Anahtar kelime eşleşmesiyle haberin altın üzerindeki etki skorunu tahmin eder.
    Dönüş: 1–10 (9-10 → Claude çağrısı tetiklenir)
    """
    metin = (baslik + " " + ozet).lower()

    kritik = [
        "fomc", "federal reserve decision", "fed rate", "interest rate decision",
        "cpi", "inflation report", "nfp", "non-farm payroll", "jobs report",
        "nuclear", "war declaration", "central bank", "default", "crisis",
    ]
    yuksek = [
        "fed", "rate hike", "rate cut", "inflation", "payroll", "gdp",
        "recession", "bank", "treasury", "yields", "dollar index", "dxy",
    ]
    orta = [
        "gold", "xau", "commodity", "precious metal", "silver",
        "geopolit", "sanction", "tariff", "trade",
    ]

    for k in kritik:
        if k in metin:
            return 9

    puan = sum(1 for k in yuksek if k in metin)
    if puan >= 2:
        return 7
    if puan == 1:
        return 5

    if any(k in metin for k in orta):
        return 4

    return 3


def _claude_analiz(baslik: str, ozet_metin: str) -> dict:
    """Tek bir haberi Claude ile analiz et, yapılandırılmış dict döndür."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    sistem = (
        "Sen bir emtia piyasası analistisin. Altın fiyatına etkisini analiz et. "
        "SADECE şu 5 satırı yaz, başka hiçbir şey yazma:\n"
        "SENTIMENT: BULLISH / BEARISH / NOTR\n"
        "ETKI: 1-10\n"
        "KATEGORI: MERKEZ_BANKASI / JEOPOLITIK / ENFLASYON / ISTIHDAM / "
        "FIZIKSEL_TALEP / RISK_ISTAHI / TEKNIK / DIGER\n"
        "OZET: tek cümle türkçe\n"
        "ACIKLAMA: neden bu etki skoru?"
    )

    mesaj = f"Haber başlığı: {baslik}\nÖzet: {ozet_metin}"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system=sistem,
        messages=[{"role": "user", "content": mesaj}]
    )

    yanit = response.content[0].text.strip()
    sonuc = {
        "sentiment": "NOTR",
        "etki": 5,
        "kategori": "DIGER",
        "ozet": "",
        "aciklama": "",
    }

    for satir in yanit.split("\n"):
        satir = satir.strip()
        if satir.startswith("SENTIMENT:"):
            v = satir.split(":", 1)[1].strip().upper()
            if v in ("BULLISH", "BEARISH", "NOTR"):
                sonuc["sentiment"] = v
        elif satir.startswith("ETKI:"):
            try:
                sonuc["etki"] = max(1, min(10, int(satir.split(":", 1)[1].strip())))
            except ValueError:
                pass
        elif satir.startswith("KATEGORI:"):
            sonuc["kategori"] = satir.split(":", 1)[1].strip()
        elif satir.startswith("OZET:"):
            sonuc["ozet"] = satir.split(":", 1)[1].strip()
        elif satir.startswith("ACIKLAMA:"):
            sonuc["aciklama"] = satir.split(":", 1)[1].strip()

    return sonuc


# ──────────────────────────────────────────
# RSS takip sistemi
# ──────────────────────────────────────────
def rss_kontrol() -> list:
    """
    Tüm RSS feedlerini tarar, yeni altın haberleri Claude'a analiz ettirir.
    Yeni işlenen haberlerin listesini döndürür.
    """
    global _haber_hafizasi
    yeni_haberler = []

    for feed_url in RSS_FEEDLER:
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue

        for entry in feed.entries:
            baslik = getattr(entry, "title", "").strip()
            if not baslik or baslik in _gorulmus_basliklar:
                continue

            if not _altin_haberi_mi(baslik):
                _gorulmus_basliklar.add(baslik)
                continue

            _gorulmus_basliklar.add(baslik)
            haber_zamani = _parse_entry_time(entry)
            ozet_metin = getattr(entry, "summary", "")[:300]

            # 1. Etki tahmini (anahtar kelime, ücretsiz)
            etki = _etki_tahmini(baslik, ozet_metin)

            # 2. Sentiment: FinBERT (yerel, ücretsiz)
            finbert_sonuc = finbert_agent.analiz_et(baslik + " " + ozet_metin[:200])
            sentiment  = finbert_sonuc["sentiment"]
            fb_guven   = finbert_sonuc["guven"]
            kategori   = "DIGER"
            ozet_kisa  = baslik[:80]
            aciklama   = f"FinBERT güven: {fb_guven:.2%}"

            # 3. Sadece etki 9-10 → Claude ile derinleştir
            if etki >= 9:
                try:
                    claude_sonuc = _claude_analiz(baslik, ozet_metin)
                    sentiment  = claude_sonuc["sentiment"]
                    etki       = claude_sonuc["etki"]
                    kategori   = claude_sonuc["kategori"]
                    ozet_kisa  = claude_sonuc["ozet"]
                    aciklama   = claude_sonuc["aciklama"]
                except Exception as e:
                    aciklama += f" | Claude hatası: {e}"

            carpan = _zaman_carpani(haber_zamani)
            haber = {
                "baslik":         baslik,
                "zaman":          haber_zamani.isoformat(),
                "sentiment":      sentiment,
                "etki":           etki,
                "agirlikli_etki": round(etki * carpan, 2),
                "kategori":       kategori,
                "ozet":           ozet_kisa,
                "aciklama":       aciklama,
                "kaynak":         feed_url,
                "finbert_guven":  fb_guven,
            }
            yeni_haberler.append(haber)

        _son_kontrol[feed_url] = datetime.now(timezone.utc)

    # Hafızayı güncelle (son 10 haber)
    _haber_hafizasi = (_haber_hafizasi + yeni_haberler)[-10:]
    return yeni_haberler


def _agirlikli_skor() -> float:
    """Hafızadaki son 10 haberin ağırlıklı toplam etkisini döndürür."""
    if not _haber_hafizasi:
        return 0.0
    return round(sum(h["agirlikli_etki"] for h in _haber_hafizasi), 2)


def _ozet_sentiment() -> str:
    """Hafızadaki haberlere göre genel sentiment."""
    if not _haber_hafizasi:
        return "NOTR"
    sayac = {"BULLISH": 0, "BEARISH": 0, "NOTR": 0}
    for h in _haber_hafizasi:
        sayac[h.get("sentiment", "NOTR")] += h.get("agirlikli_etki", 0)
    return max(sayac, key=sayac.get)


# ──────────────────────────────────────────
# Ana fonksiyon (mevcut arayüz korundu)
# ──────────────────────────────────────────
def calistir() -> dict:
    try:
        # RSS'ten yeni haberleri çek
        rss_kontrol()

        # RSS sonuçlarına göre veri varsa onları kullan
        if _haber_hafizasi:
            son_haber = _haber_hafizasi[-1]
            return {
                "durum":        "ok",
                "sentiment":    _ozet_sentiment(),
                "haber_skoru":  _agirlikli_skor(),
                "etki":         son_haber["etki"],
                "kategori":     son_haber["kategori"],
                "ozet":         son_haber["ozet"],
                "son_haberler": _haber_hafizasi[-3:],
            }

        # RSS'te yeni haber yoksa genel web araması yap (orijinal davranış)
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        bugun  = datetime.now().strftime("%d %B %Y")

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            system=(
                "Sen bir emtia piyasası analistisin. Altın fiyatını etkileyen haberleri analiz et. "
                "SADECE ve SADECE aşağıdaki 3 satırı yaz, başka hiçbir şey yazma, markdown kullanma:\n"
                "SENTIMENT: BULLISH\n"
                "OZET: buraya 2 cumle turkce ozet\n"
                "ETKENLER: etken1, etken2, etken3"
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Bugün {bugun} itibarıyla altın fiyatını etkileyen en önemli gelişmeleri analiz et. "
                    "Fed politikası, dolar endeksi, jeopolitik riskler ve fiziksel talep verilerini göz önünde bulundur."
                )
            }]
        )

        tam_yanit = "".join(
            b.text for b in response.content
            if hasattr(b, "text") and b.text
        ).strip()

        sentiment = "NOTR"
        ozet      = ""
        etkenler  = []

        for satir in tam_yanit.split("\n"):
            satir = satir.strip()
            if satir.startswith("SENTIMENT:"):
                deger = satir.replace("SENTIMENT:", "").strip().upper()
                if deger in ["BULLISH", "BEARISH", "NOTR"]:
                    sentiment = deger
            elif satir.startswith("OZET:"):
                ozet = satir.replace("OZET:", "").strip()
            elif satir.startswith("ETKENLER:"):
                etkenler = [e.strip() for e in satir.replace("ETKENLER:", "").strip().split(",")]

        return {
            "durum":        "ok",
            "sentiment":    sentiment,
            "haber_skoru":  0.0,
            "etki":         5,
            "kategori":     "DIGER",
            "ozet":         ozet,
            "son_haberler": [],
            # geriye uyumluluk
            "etkenler":     etkenler,
            "ham_yanit":    tam_yanit,
        }

    except Exception as e:
        return {
            "durum":        "hata",
            "sentiment":    "NOTR",
            "haber_skoru":  0.0,
            "etki":         0,
            "kategori":     "DIGER",
            "ozet":         "Haber verisi alinamadi.",
            "son_haberler": [],
            "mesaj":        str(e),
        }


if __name__ == "__main__":
    import json

    print("=== RSS KONTROL ===")
    yeni = rss_kontrol()
    print(f"Yeni altın haberi: {len(yeni)}")
    for h in yeni:
        print(f"  [{h['sentiment']} | etki:{h['etki']} | ağırlıklı:{h['agirlikli_etki']}] {h['baslik'][:70]}")

    print("\n=== HABER AJANI calistir() ===")
    sonuc = calistir()
    print(json.dumps(sonuc, indent=2, ensure_ascii=False, default=str))
