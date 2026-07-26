#!/usr/bin/env python3
"""
testler/duman_testi.py
──────────────────────
Tüm canlı hattı ağ ve API çağrısı olmadan baştan sona koşturur.

Neden var:
    Bir ajanın DÖNDÜRDÜĞÜ anahtarlarla, onu tüketen ajanın BEKLEDİĞİ
    anahtarlar arasındaki uyumsuzluğu anında yakalamak için.

    2026-07-26'da bulunan hata tam olarak bu türdendi: decision_agent
    teknik_analiz['destek'] okuyordu, technical_agent bunu döndürmüyordu.
    Hata iki ay boyunca görünmedi çünkü ajanların kendi test blokları
    elle yazılmış, canlıda var olmayan anahtarlar içeren sözlükler
    kullanıyordu. Bu testte hiçbir sözlük elle yazılmaz — her ajan bir
    öncekinin GERÇEK çıktısıyla beslenir.

Çalıştırma:
    ~/gold-bot/bin/python3 testler/duman_testi.py

Ücretsiz ve çevrimdışıdır: Claude, Binance, Telegram, yfinance ve
investing.com sahte nesnelerle değiştirilir.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import math
import time


# ══════════════════════════════════════════════════════════════════════
# 1. SÖZLEŞMELER — her ajanın döndürmek zorunda olduğu anahtarlar
#    (tipler.py bu tablonun dataclass karşılığı — burada ikinci bir göz olarak kalıyor)
# ══════════════════════════════════════════════════════════════════════
SOZLESMELER = {
    "data_agent.kisa_vadeli_veri": {
        "durum", "mod", "fiyat", "degisim_pct", "yuksek", "dusuk",
        "direnc", "destek", "atr", "hacim", "hacim_ort", "hacim_teyit",
        "breakout", "son_5_kapanis",
    },
    "data_agent.uzun_vadeli_veri": {
        "durum", "mod", "fiyat", "degisim_pct", "rsi", "rsi_yorum",
        "macd", "macd_sinyal", "macd_hist", "ma20", "ma50",
        "bb_ust", "bb_alt", "atr", "trend", "son_5_kapanis",
    },
    "technical_agent.calistir": {"durum", "mod", "sinyal", "sl", "tp", "yorum"},
    "risk_agent.calistir": {"durum", "risk", "onay", "max_pozisyon", "uyari"},
    "decision_agent.calistir": {
        "durum", "eylem", "guven", "stop_loss_pct", "take_profit_pct", "gerekce",
    },
    "order_agent.calistir": {
        "durum", "islem", "fiyat", "stop_loss", "take_profit", "emir_id",
    },
    "macro_agent.calistir": {
        "durum", "skor", "yorum", "dxy_degisim", "vix_degisim",
        "tnx_degisim", "sp500_degisim", "detay",
    },
    "calendar_agent.calistir": {
        "durum", "mod", "yaklasan_olaylar", "aciklanan_olaylar",
    },
    "news_agent.calistir": {
        "durum", "sentiment", "haber_skoru", "etki", "kategori",
        "ozet", "son_haberler",
    },
}


# ══════════════════════════════════════════════════════════════════════
# 2. SAHTE NESNELER
# ══════════════════════════════════════════════════════════════════════
def sahte_mumlar(adet: int = 100, breakout: bool = False) -> list:
    """Binance futures_klines biçiminde deterministik OHLCV üretir."""
    satirlar = []
    t0 = int(time.time() * 1000) - adet * 60_000
    fiyat = 4500.0

    for i in range(adet):
        acilis  = fiyat
        kapanis = fiyat + math.sin(i / 7) * 3
        yuksek  = max(acilis, kapanis) + 1.5
        dusuk   = min(acilis, kapanis) - 1.5
        zaman   = t0 + i * 60_000
        satirlar.append([
            zaman, f"{acilis:.2f}", f"{yuksek:.2f}", f"{dusuk:.2f}",
            f"{kapanis:.2f}", "800.0", zaman + 59_999,
            "0", 0, "0", "0", "0",
        ])
        fiyat = kapanis

    if breakout:
        # Son mum: tüm direnci kırsın + hacim teyidi versin
        en_yuksek = max(float(s[2]) for s in satirlar[:-1])
        s = satirlar[-1]
        s[2] = f"{en_yuksek + 12:.2f}"          # yüksek
        s[4] = f"{en_yuksek + 10:.2f}"          # kapanış
        s[5] = "5000.0"                          # hacim (ort ~800 → teyit)

    return satirlar


class SahteBinance:
    """binance.client.Client yerine geçer."""
    son_emirler = []
    breakout_modu = False

    # data_agent bunlara Client.X olarak erişiyor
    KLINE_INTERVAL_1MINUTE  = "1m"
    KLINE_INTERVAL_5MINUTE  = "5m"
    KLINE_INTERVAL_15MINUTE = "15m"

    def __init__(self, *a, **kw):
        pass

    def get_server_time(self):
        return {"serverTime": int(time.time() * 1000)}

    def futures_klines(self, **kw):
        return sahte_mumlar(100, breakout=SahteBinance.breakout_modu)

    def futures_change_leverage(self, **kw):
        SahteBinance.son_emirler.append(("kaldirac", kw.get("leverage")))
        return {"leverage": kw.get("leverage")}

    def futures_create_order(self, **kw):
        SahteBinance.son_emirler.append((kw.get("type"), kw.get("side")))
        return {"orderId": 1000 + len(SahteBinance.son_emirler)}


class _Icerik:
    def __init__(self, text):
        self.text = text


class _Yanit:
    def __init__(self, text):
        self.content = [_Icerik(text)]


class _Messages:
    def create(self, **kw):
        sistem = kw.get("system", "")
        SahteClaude.cagri_sayisi += 1

        if "risk yöneticisi" in sistem:
            return _Yanit("RISK: ORTA\nONAY: EVET\nMAX_POZISYON: 0.01\n"
                          "UYARI: kaldirac dusuk tutulmali")
        if "teknik analist" in sistem:
            return _Yanit("SINYAL: GUCLU_AL\nSL_FIYAT: 4500.0\n"
                          "TP_FIYAT: 4560.0\nYORUM: breakout onaylandi")
        if "baş trader" in sistem:
            return _Yanit(json.dumps({
                "karar": "AL", "guven": 7,
                "stop_loss_pct": 0.8, "take_profit_pct": 1.5,
                "gerekce": "duman testi",
            }))
        return _Yanit("SENTIMENT: NOTR\nOZET: -\nETKENLER: -")


class SahteClaude:
    """anthropic.Anthropic yerine geçer."""
    cagri_sayisi = 0

    def __init__(self, *a, **kw):
        self.messages = _Messages()


def sahte_kurulum():
    """Tüm dış bağımlılıkları sahteleriyle değiştirir."""
    from agents import (data_agent, order_agent, technical_agent,
                        risk_agent, decision_agent, news_agent,
                        macro_agent, calendar_agent, telegram_agent)

    # Binance
    data_agent.Client = SahteBinance
    order_agent.Client = SahteBinance

    # Claude
    for modul in (technical_agent, risk_agent, decision_agent, news_agent):
        modul.anthropic = type("sahte_anthropic", (), {"Anthropic": SahteClaude})

    # Telegram — hiçbir mesaj gönderilmesin
    telegram_agent._gonder = lambda mesaj: True
    data_agent.bildir_hata = lambda m: True
    order_agent.bildir_hata = lambda m: True

    # yfinance (makro) — sabit fiyat çiftleri
    macro_agent._veri_cek = lambda sembol: {
        "DX-Y.NYB": (103.0, 103.5),   # dolar düşmüş → altına olumlu
        "^VIX":     (18.0, 17.0),
        "^TNX":     (4.2, 4.3),
        "^GSPC":    (5000.0, 5020.0),
    }[sembol]

    # investing.com (takvim) — olay yok → NORMAL mod
    calendar_agent._takvim_cek = lambda bas, bit: []

    # RSS + FinBERT — hafızaya tek haber koy, Claude'a düşmesin.
    # Hafıza içindeki haberler ham sözlük olarak kalır (son_haberler alanı),
    # HaberRaporu bunları olduğu gibi taşır.
    news_agent._haber_hafizasi = [{
        "baslik": "Gold rises as dollar weakens",
        "zaman": "2026-07-26T10:00:00+00:00",
        "sentiment": "BULLISH", "etki": 6, "agirlikli_etki": 6.0,
        "kategori": "MERKEZ_BANKASI", "ozet": "Dolar zayifladi",
        "aciklama": "-", "kaynak": "test", "finbert_guven": 0.9,
    }]
    news_agent.rss_kontrol = lambda: []


# ══════════════════════════════════════════════════════════════════════
# 3. TEST ÇATISI
# ══════════════════════════════════════════════════════════════════════
_sonuclar = []


def kontrol(ad: str, kosul: bool, detay: str = ""):
    _sonuclar.append((ad, kosul, detay))
    isaret = "✓" if kosul else "✗"
    print(f"  {isaret} {ad}" + (f"\n      → {detay}" if detay and not kosul else ""))


def _alanlar(sonuc) -> set:
    """Dataclass (tipler.py) ya da düz sözlük — ikisinden de alan adlarını çıkarır."""
    if hasattr(sonuc, "sozluk"):
        return set(sonuc.sozluk().keys())
    return set(sonuc.keys())


def sozlesme_kontrol(ad: str, sonuc):
    """Ajan çıktısının ilan ettiği alanları içerdiğini doğrular."""
    beklenen = SOZLESMELER[ad]
    eksik = beklenen - _alanlar(sonuc)
    kontrol(f"{ad} sözleşmesi",
            not eksik,
            f"eksik alan: {sorted(eksik)}")


# ══════════════════════════════════════════════════════════════════════
# 4. TESTLER
# ══════════════════════════════════════════════════════════════════════
def test_veri_ajani():
    from agents import data_agent
    print("\n[1] data_agent")

    SahteBinance.breakout_modu = True
    kisa = data_agent.kisa_vadeli_veri()
    sozlesme_kontrol("data_agent.kisa_vadeli_veri", kisa)
    kontrol("kısa veri durum=ok", kisa.basarili, kisa.mesaj)
    kontrol("breakout tespit edildi", kisa.breakout == "YUKARI",
            f"breakout={kisa.breakout}")

    uzun = data_agent.uzun_vadeli_veri()
    sozlesme_kontrol("data_agent.uzun_vadeli_veri", uzun)
    kontrol("uzun veri durum=ok", uzun.basarili, uzun.mesaj)
    return kisa, uzun


def test_baglam_ajanlari():
    from agents import macro_agent, calendar_agent, news_agent
    print("\n[2] bağlam ajanları (makro / takvim / haber)")

    makro = macro_agent.calistir()
    sozlesme_kontrol("macro_agent.calistir", makro)
    kontrol("makro durum=ok", makro.basarili, makro.mesaj)

    takvim = calendar_agent.calistir()
    sozlesme_kontrol("calendar_agent.calistir", takvim)
    kontrol("takvim modu geçerli",
            takvim.mod in ("NORMAL", "DIKKATLI", "YUKSEK_RISK"),
            f"mod={takvim.mod}")

    haber = news_agent.calistir()
    sozlesme_kontrol("news_agent.calistir", haber)
    kontrol("haber durum=ok", haber.basarili, haber.mesaj)
    return makro, takvim, haber


def test_hat(kisa, uzun, makro, takvim, haber):
    """
    ASIL TEST: her ajan bir öncekinin GERÇEK çıktısıyla beslenir.
    Elle yazılmış sözlük yok — 26 Temmuz hatası burada yakalanırdı.
    """
    from agents import technical_agent, risk_agent, decision_agent

    for etiket, teknik, kaldirac_adi in (("KISA", kisa, "KALDIRAC_KISA"),
                                          ("UZUN", uzun, "KALDIRAC_UZUN")):
        print(f"\n[3] tam hat — {etiket} katmanı")

        teknik_analiz = technical_agent.calistir(teknik)
        sozlesme_kontrol("technical_agent.calistir", teknik_analiz)
        kontrol(f"{etiket}: teknik ajan durum=ok",
                teknik_analiz.basarili, teknik_analiz.mesaj)

        risk = risk_agent.calistir(teknik, teknik_analiz, haber)
        sozlesme_kontrol("risk_agent.calistir", risk)
        kontrol(f"{etiket}: risk ajanı durum=ok", risk.basarili, risk.mesaj)

        karar = decision_agent.calistir(teknik, haber, teknik_analiz, risk,
                                        makro=makro, takvim=takvim)
        sozlesme_kontrol("decision_agent.calistir", karar)
        kontrol(f"{etiket}: karar ajanı durum=ok", karar.basarili, karar.mesaj)
        kontrol(f"{etiket}: Claude'a gerçekten ulaşıldı",
                SahteClaude.cagri_sayisi > 0,
                "hiç Claude çağrısı yapılmadı — hat karar ajanından önce kopuyor")
        kontrol(f"{etiket}: karar geçerli",
                karar.eylem in ("AL", "SAT", "BEKLE"),
                f"karar={karar.eylem}")

        yield etiket, teknik, karar


def test_emir(hat_sonuclari):
    from agents import order_agent
    import config
    print("\n[4] order_agent")

    for etiket, teknik, karar in hat_sonuclari:
        kaldirac = config.KALDIRAC_KISA if etiket == "KISA" else config.KALDIRAC_UZUN
        SahteBinance.son_emirler = []
        sonuc = order_agent.calistir(karar, teknik.fiyat, kaldirac)

        sozlesme_kontrol("order_agent.calistir", sonuc)
        kontrol(f"{etiket}: emir durum=ok", sonuc.basarili,
                f"durum={sonuc.durum} — {sonuc.mesaj}")
        gonderilen = [t for t, _ in SahteBinance.son_emirler]
        kontrol(f"{etiket}: market + SL + TP emirleri gitti",
                len([g for g in gonderilen if g != "kaldirac"]) == 3,
                f"gönderilen: {gonderilen}")
        kontrol(f"{etiket}: kaldıraç {kaldirac}x uygulandı",
                ("kaldirac", kaldirac) in SahteBinance.son_emirler,
                f"emirler: {SahteBinance.son_emirler}")

    from tipler import Karar

    # BEKLE kararında emir gitmemeli
    SahteBinance.son_emirler = []
    sonuc = order_agent.calistir(
        Karar(eylem="BEKLE", guven=9, gerekce="test"), 4500.0, 3)
    kontrol("BEKLE kararında emir gönderilmiyor",
            sonuc.durum == "bekle" and not SahteBinance.son_emirler)

    # Düşük güvende emir gitmemeli
    SahteBinance.son_emirler = []
    sonuc = order_agent.calistir(
        Karar(eylem="AL", guven=2, gerekce="test"), 4500.0, 3)
    kontrol("Düşük güvende emir gönderilmiyor",
            sonuc.durum == "dusuk_guven" and not SahteBinance.son_emirler)


def test_koruma_katmanlari():
    """Takvim ve risk ajanı engelleri Claude'a sormadan BEKLE üretmeli."""
    from agents import decision_agent
    from tipler import KisaVeri, TeknikAnaliz, RiskRaporu, HaberRaporu, TakvimRaporu
    print("\n[5] koruma katmanları")

    teknik = KisaVeri(fiyat=4500.0, destek=4480.0, direnc=4520.0)
    analiz = TeknikAnaliz(mod="kisa", sinyal="GUCLU_AL", sl=4480.0,
                          tp=4560.0, yorum="-")
    haber  = HaberRaporu(sentiment="BULLISH", ozet="-")
    risk_e = RiskRaporu(risk="ORTA", onay="EVET", max_pozisyon=0.01, uyari="-")
    risk_h = RiskRaporu(risk="YUKSEK", onay="HAYIR", uyari="volatilite yüksek")

    once = SahteClaude.cagri_sayisi
    k = decision_agent.calistir(teknik, haber, analiz, risk_e,
                                takvim=TakvimRaporu(mod="YUKSEK_RISK"))
    kontrol("YUKSEK_RISK takvimde BEKLE + Claude çağrısı yok",
            k.eylem == "BEKLE" and SahteClaude.cagri_sayisi == once,
            f"karar={k.eylem}, çağrı={SahteClaude.cagri_sayisi - once}")

    once = SahteClaude.cagri_sayisi
    k = decision_agent.calistir(teknik, haber, analiz, risk_h)
    kontrol("Risk ajanı HAYIR dediğinde BEKLE + Claude çağrısı yok",
            k.eylem == "BEKLE" and SahteClaude.cagri_sayisi == once,
            f"karar={k.eylem}, çağrı={SahteClaude.cagri_sayisi - once}")


# ══════════════════════════════════════════════════════════════════════
# 5. ÇALIŞTIRICI
# ══════════════════════════════════════════════════════════════════════
def main():
    print("=" * 62)
    print("  DUMAN TESTİ — canlı hat, ağ ve API çağrısı olmadan")
    print("=" * 62)

    sahte_kurulum()

    kisa, uzun = test_veri_ajani()
    makro, takvim, haber = test_baglam_ajanlari()
    hat = list(test_hat(kisa, uzun, makro, takvim, haber))
    test_emir(hat)
    test_koruma_katmanlari()

    gecen  = sum(1 for _, ok, _ in _sonuclar if ok)
    toplam = len(_sonuclar)
    kalan  = [ad for ad, ok, _ in _sonuclar if not ok]

    print("\n" + "=" * 62)
    print(f"  SONUÇ: {gecen}/{toplam} kontrol geçti"
          f"  |  Claude çağrısı: {SahteClaude.cagri_sayisi} (hepsi sahte)")
    if kalan:
        print("\n  BAŞARISIZ:")
        for ad in kalan:
            print(f"    ✗ {ad}")
    print("=" * 62)

    return 0 if not kalan else 1


if __name__ == "__main__":
    sys.exit(main())
