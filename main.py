# main.py
# ─────────────────────────────────────────────
# İki ayrı bot döngüsü:
# KISA VADELİ → her 1 dakikada bir (breakout)
# UZUN VADELİ → her 4 saatte bir (RSI/MACD/BB)
# Makro       → her 15 dakikada bir (DXY/VIX/TNX/SP500)
# Takvim      → her 1 saatte bir (ekonomik takvim)
# 4. saatte tüm döngüler senkronize çalışır
# ─────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import threading
from datetime import datetime
from agents import data_agent, news_agent, technical_agent, risk_agent, decision_agent, order_agent
from agents.telegram_agent import bildir_sinyal, bildir_emir, bildir_hata, bildir_durum
from agents.macro_agent import calistir as macro_calistir
from agents.calendar_agent import calistir as takvim_calistir
import config

# ──────────────────────────────────────────────────────────
# Günlük zarar takibi
# ──────────────────────────────────────────────────────────
_gunluk_zarar       = 0.0
_gunluk_zarar_durdu = False
_son_gun            = None   # datetime.date
_zarar_kilidi       = threading.Lock()


def _gun_kontrol():
    """Gece 00:00 geçişini tespit edip günlük sayacı sıfırlar."""
    global _gunluk_zarar, _gunluk_zarar_durdu, _son_gun
    bugun = datetime.now().date()
    with _zarar_kilidi:
        if _son_gun is None or bugun != _son_gun:
            if _son_gun is not None:
                print(
                    f"\n  [ZARAR] Yeni gün — sayaç sıfırlandı "
                    f"(önceki gün toplam: ${_gunluk_zarar:.2f})"
                )
            _gunluk_zarar       = 0.0
            _gunluk_zarar_durdu = False
            _son_gun            = bugun


def _zarar_limitinde_mi() -> bool:
    """True dönerse bugün için işlem yasak."""
    with _zarar_kilidi:
        return _gunluk_zarar_durdu


def _zarar_ekle(stop_loss_pct: float, fiyat: float):
    """
    Açılan pozisyonun potansiyel SL zararını günlük sayaca ekler.
    Limit aşılınca botu durdurur ve Telegram'a bildirir.
    """
    global _gunluk_zarar, _gunluk_zarar_durdu
    kayip = config.QUANTITY * fiyat * (stop_loss_pct / 100)

    with _zarar_kilidi:
        _gunluk_zarar += kayip
        print(
            f"  [ZARAR] Günlük açık zarar: ${_gunluk_zarar:.2f} "
            f"/ ${config.MAX_GUNLUK_ZARAR:.2f}"
        )
        if not _gunluk_zarar_durdu and _gunluk_zarar >= config.MAX_GUNLUK_ZARAR:
            _gunluk_zarar_durdu = True
            bildir_durum(
                f"🛑 <b>Günlük Zarar Limitine Ulaşıldı</b>\n"
                f"Bugünkü açık zarar: ${_gunluk_zarar:.2f}\n"
                f"Limit: ${config.MAX_GUNLUK_ZARAR:.2f}\n"
                f"Bugün için tüm işlemler durduruldu. Yarın sıfırlanacak."
            )
            print(
                f"  [ZARAR] ⛔ ${config.MAX_GUNLUK_ZARAR:.2f} limiti aşıldı — "
                f"bugün işlem yok."
            )


# ──────────────────────────────────────────────────────────
# Paylaşılan durum değişkenleri
# ──────────────────────────────────────────────────────────
son_haber_raporu = {
    "sentiment": "NOTR",
    "haber_skoru": 0.0,
    "ozet": "Henüz haber analizi yapılmadı.",
    "etkenler": [],
    "son_haberler": [],
}
haber_kilidi = threading.Lock()

son_makro_raporu = {
    "durum": "ok",
    "skor": 0,
    "yorum": "NOTR",
    "dxy_degisim": 0.0,
    "vix_degisim": 0.0,
    "tnx_degisim": 0.0,
    "sp500_degisim": 0.0,
    "detay": {},
}
makro_kilidi = threading.Lock()

son_takvim_raporu = {
    "durum": "ok",
    "mod": "NORMAL",
    "yaklasan_olaylar": [],
    "aciklanan_olaylar": [],
}
takvim_kilidi = threading.Lock()


# ──────────────────────────────────────────────────────────
# Güncelleme fonksiyonları
# ──────────────────────────────────────────────────────────
def haber_guncelle():
    global son_haber_raporu
    print("\n  [HABER] İnternet taranıyor...")
    rapor = news_agent.calistir()
    with haber_kilidi:
        son_haber_raporu = rapor
    print(f"  [HABER] Sentiment: {rapor['sentiment']} | Skor: {rapor.get('haber_skoru', 0):.1f}")


def makro_guncelle():
    global son_makro_raporu
    print("\n  [MAKRO] DXY/VIX/TNX/SP500 güncelleniyor...")
    rapor = macro_calistir()
    if rapor["durum"] != "ok":
        print(f"  [MAKRO] Hata: {rapor.get('mesaj', '?')}")
        return

    onceki_skor = son_makro_raporu["skor"]
    with makro_kilidi:
        son_makro_raporu = rapor

    skor  = rapor["skor"]
    yorum = rapor["yorum"]
    print(f"  [MAKRO] Skor: {skor:+.1f} | {yorum} | DXY:{rapor['dxy_degisim']:+.2f}% VIX:{rapor['vix_degisim']:+.2f}%")

    # Skor anlamlı ölçüde değiştiyse Telegram'a bildir
    if abs(skor - onceki_skor) >= 3:
        emoji = "📈" if skor > onceki_skor else "📉"
        bildir_durum(
            f"{emoji} <b>Makro Güncelleme</b>\n"
            f"Skor: {onceki_skor:+.1f} → {skor:+.1f} | {yorum}\n"
            f"DXY:{rapor['dxy_degisim']:+.2f}%  VIX:{rapor['vix_degisim']:+.2f}%  "
            f"TNX:{rapor['tnx_degisim']:+.2f}%  SP500:{rapor['sp500_degisim']:+.2f}%"
        )


def takvim_guncelle():
    global son_takvim_raporu
    print("\n  [TAKVİM] Ekonomik takvim kontrol ediliyor...")
    rapor = takvim_calistir()

    onceki_mod = son_takvim_raporu["mod"]
    with takvim_kilidi:
        son_takvim_raporu = rapor

    mod = rapor["mod"]
    print(f"  [TAKVİM] Mod: {mod} | Yaklaşan: {len(rapor['yaklasan_olaylar'])} olay")

    # Mod kötüleştiyse Telegram uyarısı gönder
    sirali = ["NORMAL", "DIKKATLI", "YUKSEK_RISK"]
    if sirali.index(mod) > sirali.index(onceki_mod):
        yaklashan_str = ""
        for o in rapor["yaklasan_olaylar"][:3]:
            yaklashan_str += f"\n  • {o['isim']} ({o['saat_sonra']:.1f} saat sonra, etki:{o['etki']})"
        bildir_durum(
            f"⚠️ <b>Takvim Uyarısı: {mod}</b>{yaklashan_str}"
        )


# ──────────────────────────────────────────────────────────
# Ortak bağlam oluşturucu
# ──────────────────────────────────────────────────────────
def _baglam_olustur() -> tuple:
    """Haberler, makro ve takvim verilerini okur.
    Dönüş: (haberler, makro, takvim) — üçü ayrı ayrı decision_agent'a iletilir."""
    with haber_kilidi:
        haberler = son_haber_raporu.copy()
    with makro_kilidi:
        makro = son_makro_raporu.copy()
    with takvim_kilidi:
        takvim = son_takvim_raporu.copy()

    # Loglama kolaylığı için haberler'e özet bilgi göm
    haberler["makro_skor"]       = makro["skor"]
    haberler["makro_yorum"]      = makro["yorum"]
    haberler["takvim_mod"]       = takvim["mod"]
    haberler["yaklasan_olaylar"] = takvim.get("yaklasan_olaylar", [])
    return haberler, makro, takvim


# ──────────────────────────────────────────────────────────
# Bot döngüleri
# ──────────────────────────────────────────────────────────
def kisa_vadeli_dongu():
    zaman = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'─'*50}")
    print(f"  [KISA] {zaman}")

    # Günlük zarar limiti kontrolü
    if _zarar_limitinde_mi():
        print(f"  [KISA] ⛔ Günlük zarar limitine ulaşıldı — işlem yok.")
        return

    # Takvim modu kontrolü
    with takvim_kilidi:
        takvim_mod = son_takvim_raporu["mod"]

    if takvim_mod == "YUKSEK_RISK":
        print(f"  [KISA] ⛔ Ekonomik veri bekleniyor — işlem yok.")
        return
    elif takvim_mod == "DIKKATLI":
        print(f"  [KISA] ⚠️  Dikkatli mod aktif.")

    # Veri
    teknik = data_agent.kisa_vadeli_veri()
    if teknik["durum"] == "hata":
        print(f"  [KISA] Veri hatası: {teknik['mesaj']}")
        return
    print(f"  [KISA] Fiyat: {teknik['fiyat']} | Breakout: {teknik['breakout']}")

    # Breakout yoksa çık
    if teknik["breakout"] == "YOK":
        print(f"  [KISA] Breakout yok, bekleniyor.")
        return

    # Teknik analiz
    teknik_analiz = technical_agent.calistir(teknik)
    print(f"  [KISA] Sinyal: {teknik_analiz['sinyal']} | {teknik_analiz['yorum'][:60]}")

    # Makro + haber + takvim bağlamını oku
    baglam, makro, takvim = _baglam_olustur()
    print(f"  [KISA] Makro: {baglam['makro_yorum']} ({baglam['makro_skor']:+.1f})")

    # Risk değerlendirmesi
    risk = risk_agent.calistir(teknik, teknik_analiz, baglam)
    print(f"  [KISA] Risk: {risk['risk']} | Onay: {risk['onay']}")

    # Karar
    karar = decision_agent.calistir(teknik, baglam, teknik_analiz, risk, makro=makro, takvim=takvim)
    print(f"  [KISA] Karar: {karar['karar']} | Güven: {karar['guven']}/10")

    # Emir
    if karar["karar"] != "BEKLE" and karar["guven"] >= config.MIN_GUVEN_SKORU:
        bildir_sinyal(karar["karar"], teknik["fiyat"], "Breakout", karar["guven"])
        sonuc = order_agent.calistir(karar, teknik["fiyat"])
        if sonuc["durum"] == "ok":
            bildir_emir(
                karar["karar"], teknik["fiyat"],
                config.QUANTITY, sonuc["stop_loss"], sonuc["take_profit"]
            )
            _zarar_ekle(karar.get("stop_loss_pct", config.MAX_STOP_LOSS_PCT), teknik["fiyat"])


def uzun_vadeli_dongu(haber_guncelle_de=False):
    zaman = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'='*50}")
    print(f"  [UZUN] {zaman} — 4 saatlik analiz")

    # Günlük zarar limiti kontrolü
    if _zarar_limitinde_mi():
        print(f"  [UZUN] ⛔ Günlük zarar limitine ulaşıldı — işlem yok.")
        print(f"{'='*50}")
        return

    if haber_guncelle_de:
        haber_guncelle()

    # Takvim modu kontrolü
    with takvim_kilidi:
        takvim_mod = son_takvim_raporu["mod"]

    if takvim_mod == "YUKSEK_RISK":
        print(f"  [UZUN] ⛔ Ekonomik veri bekleniyor — işlem yok.")
        print(f"{'='*50}")
        return
    elif takvim_mod == "DIKKATLI":
        print(f"  [UZUN] ⚠️  Dikkatli mod aktif.")

    # Veri
    teknik = data_agent.uzun_vadeli_veri()
    if teknik["durum"] == "hata":
        print(f"  [UZUN] Veri hatası: {teknik['mesaj']}")
        return
    print(f"  [UZUN] Fiyat: {teknik['fiyat']} | RSI: {teknik['rsi']} | Trend: {teknik['trend']}")

    # Teknik analiz
    teknik_analiz = technical_agent.calistir(teknik)
    print(f"  [UZUN] Sinyal: {teknik_analiz['sinyal']} | {teknik_analiz['yorum'][:60]}")

    # Makro + haber + takvim bağlamını oku
    baglam, makro, takvim = _baglam_olustur()
    print(f"  [UZUN] Makro: {baglam['makro_yorum']} ({baglam['makro_skor']:+.1f}) | Takvim: {takvim_mod}")

    # Risk
    risk = risk_agent.calistir(teknik, teknik_analiz, baglam)
    print(f"  [UZUN] Risk: {risk['risk']} | Onay: {risk['onay']}")

    # Karar
    karar = decision_agent.calistir(teknik, baglam, teknik_analiz, risk, makro=makro, takvim=takvim)
    print(f"  [UZUN] Karar: {karar['karar']} | Güven: {karar['guven']}/10")

    # Emir
    if karar["karar"] != "BEKLE" and karar["guven"] >= config.MIN_GUVEN_SKORU:
        bildir_sinyal(karar["karar"], teknik["fiyat"], "RSI/MACD/BB", karar["guven"])
        sonuc = order_agent.calistir(karar, teknik["fiyat"])
        if sonuc["durum"] == "ok":
            bildir_emir(
                karar["karar"], teknik["fiyat"],
                config.QUANTITY, sonuc["stop_loss"], sonuc["take_profit"]
            )
            _zarar_ekle(karar.get("stop_loss_pct", config.MAX_STOP_LOSS_PCT), teknik["fiyat"])
    print(f"{'='*50}")


# ──────────────────────────────────────────────────────────
# Ana giriş
# ──────────────────────────────────────────────────────────
def main():
    print("\n" + "★"*52)
    print("  ALTIN TRADİNG BOTU — 2 KATMANLI SİSTEM")
    print(f"  Kısa vadeli : 1 dk   | Breakout      | 10x")
    print(f"  Makro       : 15 dk  | DXY/VIX/TNX   |")
    print(f"  Takvim      : 1 saat | Ekonomik veri |")
    print(f"  Uzun vadeli : 4 saat | RSI/MACD/BB   | 3x")
    print(f"  Mod         : {'TESTNET' if config.TESTNET else '*** GERÇEK PARA ***'}")
    print("  Durdurmak için: Ctrl+C")
    print("★"*52)

    mod = "TESTNET" if config.TESTNET else "GERÇEK PARA"
    bildir_durum(f"Altın Trading Botu başlatıldı.\nMod: {mod} | Sembol: {config.SYMBOL}")

    # Başlangıç verileri
    _gun_kontrol()
    haber_guncelle()
    makro_guncelle()
    takvim_guncelle()
    uzun_vadeli_dongu(haber_guncelle_de=False)

    dongu_sayaci = 0  # kaç dakika geçti

    while True:
        try:
            time.sleep(60)
            dongu_sayaci += 1
            _gun_kontrol()   # Gece 00:00 geçişi → sıfırla

            # Her 15 dakikada makro güncelle
            if dongu_sayaci % 15 == 0:
                makro_guncelle()

            # Her 1 saatte takvim güncelle
            if dongu_sayaci % 60 == 0:
                takvim_guncelle()

            # Her 4 saatte uzun vadeli
            if dongu_sayaci % 240 == 0:
                uzun_vadeli_dongu(haber_guncelle_de=True)
            else:
                # Her dakika: RSS + kısa vadeli
                news_agent.rss_kontrol()
                kisa_vadeli_dongu()

        except KeyboardInterrupt:
            bildir_durum("Bot durduruldu (Ctrl+C).")
            print("\n\nBot durduruldu. Güle güle!")
            sys.exit(0)

        except Exception as e:
            print(f"\nKritik hata: {e}")
            bildir_hata(f"Kritik hata — 30 saniye sonra devam:\n{e}")
            print("30 saniye sonra devam...")
            time.sleep(30)


if __name__ == "__main__":
    main()
