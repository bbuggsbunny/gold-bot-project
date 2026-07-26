import feedparser
from datetime import datetime, timezone
import config
import claude_istemci
from tipler import HaberRaporu
from agents import finbert_agent

# ──────────────────────────────────────────
# Modül seviyesi hafıza
# ──────────────────────────────────────────
# ──────────────────────────────────────────
# RSS kaynakları
#
# 2026-07-26: önceki üç kaynağın ÜÇÜ DE ölüydü — Reuters feed'i DNS'te
# yok (servis kapatılmış), kitco.com/rss ve gold.org/goldhub/rss 404.
# Yani haber katmanı aylardır hiçbir şey üretmiyordu ve FinBERT hiç
# çalışmıyordu. Aşağıdakiler ölçülerek seçildi.
# ──────────────────────────────────────────
RSS_FEEDLER = [
    # Google News — altın fiyatını süren makro haberler.
    # Dışlamalar: -stock -shares -mining madencilik hissesi gürültüsünü,
    # -karat -tola yerel kuyumcu fiyat listelerini eler.
    "https://news.google.com/rss/search?"
    "q=gold+(fed+OR+inflation+OR+dollar+OR+%22interest+rate%22)"
    "+-stock+-shares+-mining+-karat+-tola+when:1d"
    "&hl=en-US&gl=US&ceid=US:en",

    # Investing.com emtia — az sayıda ama derlenmiş, konuya yakın
    "https://www.investing.com/rss/commodities.rss",

    # FXStreet — döviz/emtia profesyonel akışı
    "https://www.fxstreet.com/rss/news",
]

ALTIN_KELIMELER = [
    "gold", "xau", "fed", "federal reserve",
    "interest rate", "inflation", "cpi", "dollar",
    "altın", "faiz",
]

# Anahtar kelimeyi içerse de altın FİYATIYLA ilgisi olmayan başlıklar:
# perakende kuyumcu fiyat listeleri, madencilik şirketi haberleri, hisse kotasyonları
GURULTU_KELIMELER = [
    "22k", "24k", "18k", "karat", "carat", "tola", "sovereign rate",
    "stock price", "share price", "shares of", "(nyse", "(nasdaq",
    "music video", "horoscope",
]

# Tek döngüde işlenecek en fazla yeni haber. FinBERT toplu çağrısı
# birkaç saniye sürüyor; ilk çalıştırmada yüzlerce başlık gelebildiği
# için sınır koyuluyor — kalanlar sonraki döngülerde işlenir.
MAX_YENI_HABER = 15

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
    """Altın fiyatıyla ilgili mi? Anahtar kelime var ama gürültü yoksa evet."""
    kucuk = baslik.lower()
    if any(g in kucuk for g in GURULTU_KELIMELER):
        return False
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

    ham = claude_istemci.sor(
        f"Haber başlığı: {baslik}\nÖzet: {ozet_metin}",
        sistem=sistem,
        model=config.MODEL_HABER,
        max_tokens=1000,
    )
    alanlar = claude_istemci.alanlari_ayristir(ham, {
        "SENTIMENT": str,
        "ETKI":      int,
        "KATEGORI":  str,
        "OZET":      str,
        "ACIKLAMA":  str,
    })

    # Geçerlilik: sentiment bilinen üç değerden biri, etki 1-10 aralığında
    sentiment = alanlar.get("SENTIMENT", "NOTR").upper()
    if sentiment not in ("BULLISH", "BEARISH", "NOTR"):
        sentiment = "NOTR"

    return {
        "sentiment": sentiment,
        "etki":      max(1, min(10, alanlar.get("ETKI", 5))),
        "kategori":  alanlar.get("KATEGORI", "DIGER"),
        "ozet":      alanlar.get("OZET", ""),
        "aciklama":  alanlar.get("ACIKLAMA", ""),
    }


# ──────────────────────────────────────────
# RSS takip sistemi
# ──────────────────────────────────────────
def rss_kontrol() -> list:
    """
    Tüm RSS feed'lerini tarar, yeni altın haberlerini analiz eder.

    TOPLU FinBERT (2026-07-26)
        Önceden her başlık için ayrı `analiz_et()` çağrılıyordu; her çağrı
        yeni bir subprocess açıp modeli sıfırdan yüklüyordu — başlık başına
        ~8 saniye. Feed'ler ölü olduğu için bu hiç fark edilmemişti, ama
        90 başlıkla dönen bir feed 1 dakikalık döngüyü 12 dakika kilitlerdi.

        Artık aday başlıklar önce toplanıyor, sonra TEK `toplu_analiz_et()`
        çağrısı yapılıyor: model bir kez yükleniyor, 90 başlık ~4 saniye.

    Dönüş: bu turda işlenen yeni haberlerin listesi.
    """
    global _haber_hafizasi

    # ── 1. Adayları topla (henüz FinBERT çağrılmıyor) ────────────────
    adaylar = []   # (baslik, ozet_metin, haber_zamani, feed_url)
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
                # Konu dışı — bir daha bakmamak için işaretle
                _gorulmus_basliklar.add(baslik)
                continue

            adaylar.append((
                baslik,
                getattr(entry, "summary", "")[:300],
                _parse_entry_time(entry),
                feed_url,
            ))

        _son_kontrol[feed_url] = datetime.now(timezone.utc)

    if not adaylar:
        return []

    # En yeni haber önce; sınırı aşanlar sonraki döngülerde işlenir
    # (işaretlenmedikleri için aday olarak kalıyorlar)
    adaylar.sort(key=lambda a: a[2], reverse=True)
    adaylar = adaylar[:MAX_YENI_HABER]

    # ── 2. TEK FinBERT çağrısı ───────────────────────────────────────
    fb_sonuclari = finbert_agent.toplu_analiz_et(
        [f"{baslik} {ozet[:200]}" for baslik, ozet, _, _ in adaylar]
    )

    # ── 3. Etki skoru + gerekirse Claude ─────────────────────────────
    yeni_haberler = []
    for (baslik, ozet_metin, haber_zamani, feed_url), fb in zip(adaylar, fb_sonuclari):
        _gorulmus_basliklar.add(baslik)

        etki       = _etki_tahmini(baslik, ozet_metin)
        sentiment  = fb["sentiment"]
        fb_guven   = fb["guven"]
        kategori   = "DIGER"
        ozet_kisa  = baslik[:80]
        aciklama   = f"FinBERT güven: {fb_guven:.2%}"

        # Sadece etki 9-10 → Claude ile derinleştir (nadir, ücretli)
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
        yeni_haberler.append({
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
        })

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
def calistir() -> HaberRaporu:
    try:
        # RSS'ten yeni haberleri çek
        rss_kontrol()

        # RSS sonuçlarına göre veri varsa onları kullan
        if _haber_hafizasi:
            son_haber = _haber_hafizasi[-1]
            return HaberRaporu(
                sentiment=_ozet_sentiment(),
                haber_skoru=_agirlikli_skor(),
                etki=son_haber["etki"],
                kategori=son_haber["kategori"],
                ozet=son_haber["ozet"],
                son_haberler=_haber_hafizasi[-3:],
            )

        # RSS'te yeni haber yoksa genel web araması yap (orijinal davranış)
        bugun = datetime.now().strftime("%d %B %Y")

        ham = claude_istemci.sor(
            f"Bugün {bugun} itibarıyla altın fiyatını etkileyen en önemli "
            "gelişmeleri analiz et. Fed politikası, dolar endeksi, jeopolitik "
            "riskler ve fiziksel talep verilerini göz önünde bulundur.",
            sistem=(
                "Sen bir emtia piyasası analistisin. Altın fiyatını etkileyen haberleri analiz et. "
                "SADECE ve SADECE aşağıdaki 2 satırı yaz, başka hiçbir şey yazma, markdown kullanma:\n"
                "SENTIMENT: BULLISH\n"
                "OZET: buraya 2 cumle turkce ozet"
            ),
            max_tokens=2000,
            araclar=[{"type": "web_search_20250305", "name": "web_search"}],
        )
        alanlar = claude_istemci.alanlari_ayristir(ham, {
            "SENTIMENT": str,
            "OZET":      str,
        })

        sentiment = alanlar.get("SENTIMENT", "NOTR").upper()
        if sentiment not in ("BULLISH", "BEARISH", "NOTR"):
            sentiment = "NOTR"

        return HaberRaporu(
            sentiment=sentiment,
            etki=5,
            ozet=alanlar.get("OZET", ""),
        )

    except Exception as e:
        print(f"  [HABER] ⚠️  Haber ajanı hatası ({type(e).__name__}): {e} → NOTR")
        return HaberRaporu.hata(e)


if __name__ == "__main__":
    import json

    print("=== RSS KONTROL ===")
    yeni = rss_kontrol()
    print(f"Yeni altın haberi: {len(yeni)}")
    for h in yeni:
        print(f"  [{h['sentiment']} | etki:{h['etki']} | ağırlıklı:{h['agirlikli_etki']}] {h['baslik'][:70]}")

    print("\n=== HABER AJANI calistir() ===")
    print(json.dumps(calistir().sozluk(), indent=2, ensure_ascii=False, default=str))
