"""
bot/dongu.py
────────────
Analiz hattı ve zamanlayıcı.

Önceden main.py'de `kisa_vadeli_dongu` ve `uzun_vadeli_dongu` diye
%90'ı aynı iki fonksiyon vardı. İkisi tek `analiz_hatti()` fonksiyonunda
birleşti; aralarındaki fark bir `Katman` tanımına indi:

    KISA — 1 dakikalık veri, breakout şartı var, 10x kaldıraç
    UZUN — 15 dakikalık veri, breakout şartı yok, 3x kaldıraç

Yeni bir katman eklemek için tek yapılacak yeni bir Katman tanımlamak.
"""
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import config
from tipler import TeknikVeri
from agents import data_agent, news_agent, technical_agent, risk_agent, decision_agent, order_agent
from agents.telegram_agent import (bildir_sinyal, bildir_emir, bildir_hata,
                                   bildir_durum, bildir_ozet)
from agents.macro_agent import calistir as macro_calistir
from agents.calendar_agent import calistir as takvim_calistir
from bot.durum import BaglamDurumu, ZararTakibi
from bot.kayit import Kayitci


# ══════════════════════════════════════════════════════════════════════
# Katman tanımları
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Katman:
    """İki analiz katmanı arasındaki tüm farklar bu tanımda."""
    ad: str
    veri_fn: Callable[[], TeknikVeri]
    kaldirac: int
    strateji: str            # Telegram bildiriminde görünen etiket
    breakout_sart: bool      # True ise breakout yoksa Claude'a hiç gidilmez
    ayirac: str              # log ayraç karakteri
    baslik_eki: str = ""
    bitis_cizgisi: bool = False


RSS_PERIYOT_DK = 5   # RSS taraması kaç dakikada bir yapılsın


KISA = Katman(
    ad="KISA",
    veri_fn=data_agent.kisa_vadeli_veri,
    kaldirac=config.KALDIRAC_KISA,
    strateji="Breakout",
    breakout_sart=True,
    ayirac="─",
)

UZUN = Katman(
    ad="UZUN",
    veri_fn=data_agent.uzun_vadeli_veri,
    kaldirac=config.KALDIRAC_UZUN,
    strateji="RSI/MACD/BB",
    breakout_sart=False,
    ayirac="=",
    baslik_eki=" — 4 saatlik analiz",
    bitis_cizgisi=True,
)


# ══════════════════════════════════════════════════════════════════════
# Bağlam güncelleyicileri
# ══════════════════════════════════════════════════════════════════════
def haber_guncelle(durum: BaglamDurumu) -> None:
    print("\n  [HABER] İnternet taranıyor...")
    rapor = news_agent.calistir()
    durum.haber_yaz(rapor)
    print(f"  [HABER] Sentiment: {rapor.sentiment} | Skor: {rapor.haber_skoru:.1f}")


def makro_guncelle(durum: BaglamDurumu) -> None:
    print("\n  [MAKRO] DXY/VIX/TNX/SP500 güncelleniyor...")
    rapor = macro_calistir()
    if not rapor.basarili:
        print(f"  [MAKRO] Hata: {rapor.mesaj}")
        return

    onceki = durum.makro_yaz(rapor)
    print(f"  [MAKRO] Skor: {rapor.skor:+.1f} | {rapor.yorum} | "
          f"DXY:{rapor.dxy_degisim:+.2f}% VIX:{rapor.vix_degisim:+.2f}%")

    # Skor anlamlı ölçüde değiştiyse Telegram'a bildir
    if abs(rapor.skor - onceki.skor) >= 3:
        emoji = "📈" if rapor.skor > onceki.skor else "📉"
        bildir_durum(
            f"{emoji} <b>Makro Güncelleme</b>\n"
            f"Skor: {onceki.skor:+.1f} → {rapor.skor:+.1f} | {rapor.yorum}\n"
            f"DXY:{rapor.dxy_degisim:+.2f}%  VIX:{rapor.vix_degisim:+.2f}%  "
            f"TNX:{rapor.tnx_degisim:+.2f}%  SP500:{rapor.sp500_degisim:+.2f}%"
        )


def takvim_guncelle(durum: BaglamDurumu) -> None:
    print("\n  [TAKVİM] Ekonomik takvim kontrol ediliyor...")
    rapor  = takvim_calistir()
    onceki = durum.takvim_yaz(rapor)

    print(f"  [TAKVİM] Mod: {rapor.mod} | "
          f"Yaklaşan: {len(rapor.yaklasan_olaylar)} olay")

    # Mod kötüleştiyse Telegram uyarısı gönder
    sirali = ["NORMAL", "DIKKATLI", "YUKSEK_RISK"]
    if sirali.index(rapor.mod) > sirali.index(onceki.mod):
        olaylar = "".join(
            f"\n  • {o.isim} ({o.saat_sonra:.1f} saat sonra, etki:{o.etki})"
            for o in rapor.yaklasan_olaylar[:3]
        )
        bildir_durum(f"⚠️ <b>Takvim Uyarısı: {rapor.mod}</b>{olaylar}")


# ══════════════════════════════════════════════════════════════════════
# Analiz hattı — iki katman için ortak
# ══════════════════════════════════════════════════════════════════════
def analiz_hatti(katman: Katman, durum: BaglamDurumu,
                 zarar: ZararTakibi, kayitci: Kayitci) -> None:
    """
    Veri → teknik → risk → karar → emir.

    Her çıkış noktası kayitci'ye bir satır yazar; `asama` sütunu döngünün
    nereye kadar gittiğini söyler (bkz. bot/kayit.py).

    Erken çıkışlar (hiç Claude çağrısı yapılmaz):
      1. Günlük zarar limiti dolmuş
      2. Takvim YUKSEK_RISK
      3. Breakout şartı olan katmanda breakout yok
    """
    etiket = katman.ad
    zaman  = datetime.now().strftime("%H:%M:%S")
    print(f"\n{katman.ayirac * 50}")
    print(f"  [{etiket}] {zaman}{katman.baslik_eki}")

    def bitir():
        if katman.bitis_cizgisi:
            print(f"{katman.ayirac * 50}")

    # 1. Günlük zarar limiti
    if zarar.limitte_mi():
        print(f"  [{etiket}] ⛔ Günlük zarar limitine ulaşıldı — işlem yok.")
        kayitci.yaz(etiket, "zarar_limiti")
        bitir()
        return

    # 2. Takvim modu
    takvim_mod = durum.takvim_modu
    if takvim_mod == "YUKSEK_RISK":
        print(f"  [{etiket}] ⛔ Ekonomik veri bekleniyor — işlem yok.")
        kayitci.yaz(etiket, "takvim_bloke")
        bitir()
        return
    if takvim_mod == "DIKKATLI":
        print(f"  [{etiket}] ⚠️  Dikkatli mod aktif.")

    # 3. Veri
    teknik = katman.veri_fn()
    if not teknik.basarili:
        print(f"  [{etiket}] Veri hatası: {teknik.mesaj}")
        kayitci.yaz(etiket, "veri_hatasi", gerekce=teknik.mesaj)
        return

    if katman.breakout_sart:
        print(f"  [{etiket}] Fiyat: {teknik.fiyat} | Breakout: {teknik.breakout}")
        if teknik.breakout == "YOK":
            print(f"  [{etiket}] Breakout yok, bekleniyor.")
            kayitci.yaz(etiket, "breakout_yok", fiyat=teknik.fiyat)
            return
    else:
        print(f"  [{etiket}] Fiyat: {teknik.fiyat} | RSI: {teknik.rsi} | "
              f"Trend: {teknik.trend}")

    # 4. Teknik analiz
    teknik_analiz = technical_agent.calistir(teknik)
    print(f"  [{etiket}] Sinyal: {teknik_analiz.sinyal} | {teknik_analiz.yorum[:60]}")

    # 5. Bağlam
    haberler, makro, takvim = durum.oku()
    makro_satir = f"  [{etiket}] Makro: {makro.yorum} ({makro.skor:+.1f})"
    print(makro_satir if katman.breakout_sart
          else f"{makro_satir} | Takvim: {takvim_mod}")

    # 6. Risk
    risk = risk_agent.calistir(teknik, teknik_analiz, haberler)
    print(f"  [{etiket}] Risk: {risk.risk} | Onay: {risk.onay}")

    # 7. Karar
    karar = decision_agent.calistir(teknik, haberler, teknik_analiz, risk,
                                    makro=makro, takvim=takvim)
    print(f"  [{etiket}] Karar: {karar.eylem} | Güven: {karar.guven}/10")

    # 8. Emir
    emir_durum = ""
    sl = tp = 0.0
    if karar.islem_var and karar.guven >= config.MIN_GUVEN_SKORU:
        bildir_sinyal(karar.eylem, teknik.fiyat, katman.strateji, karar.guven)
        sonuc = order_agent.calistir(karar, teknik.fiyat, katman.kaldirac)
        emir_durum = sonuc.durum
        sl, tp = sonuc.stop_loss, sonuc.take_profit
        if sonuc.basarili:
            bildir_emir(karar.eylem, teknik.fiyat, config.QUANTITY,
                        sonuc.stop_loss, sonuc.take_profit)
            if zarar.ekle(karar.stop_loss_pct, teknik.fiyat):
                bildir_durum(
                    f"🛑 <b>Günlük Zarar Limitine Ulaşıldı</b>\n"
                    f"Bugünkü açık zarar: ${zarar.toplam:.2f}\n"
                    f"Limit: ${zarar.limit:.2f}\n"
                    f"Bugün için tüm işlemler durduruldu. Yarın sıfırlanacak."
                )

    kayitci.yaz(
        etiket, "emir" if emir_durum == "ok" else "karar",
        fiyat=teknik.fiyat, sinyal=teknik_analiz.sinyal,
        risk=risk.risk, onay=risk.onay,
        karar=karar.eylem, guven=karar.guven,
        emir_durum=emir_durum, sl=sl, tp=tp,
        kaldirac=katman.kaldirac if emir_durum == "ok" else 0,
        gerekce=karar.gerekce,
    )

    bitir()


# ══════════════════════════════════════════════════════════════════════
# Gün sonu özeti
# ══════════════════════════════════════════════════════════════════════
def gunluk_ozet_gonder(kayitci: Kayitci, gun, acik_zarar: float) -> None:
    """
    Gece 00:00 devrinde biten günün özetini Telegram'a gönderir.

    K/Z gerçek Binance bakiyesinden hesaplanır (bugünkü bakiye − dünkü).
    İlk gün önceki bakiye bilinmediği için K/Z 0 gösterilir.
    """
    istatistik = kayitci.gun_istatistigi(gun)
    bakiye     = order_agent.bakiye_getir()
    onceki     = kayitci.onceki_bakiye()

    kar_zarar = 0.0
    if bakiye >= 0:
        if onceki is not None:
            kar_zarar = bakiye - onceki
        kayitci.bakiye_kaydet(bakiye)

    print(f"\n  [ÖZET] {gun} — döngü:{istatistik['dongu']} "
          f"karar:{istatistik['karar_asamasi']} emir:{istatistik['emir']} "
          f"bakiye:${bakiye:.2f}")

    bildir_ozet(kar_zarar, istatistik["emir"], max(bakiye, 0.0))

    # bildir_ozet sabit üç alan gösteriyor; ayrıntı ayrı mesajda
    bildir_durum(
        f"📊 <b>{gun} detay</b>\n"
        f"Döngü: {istatistik['dongu']} "
        f"(breakout yok: {istatistik['breakout_yok']})\n"
        f"Karar aşamasına gelen: {istatistik['karar_asamasi']}\n"
        f"AL:{istatistik['al']}  SAT:{istatistik['sat']}  "
        f"BEKLE:{istatistik['bekle']}\n"
        f"Ortalama güven: {istatistik['ort_guven']:.1f}/10\n"
        f"Açılan risk (potansiyel SL): ${acik_zarar:.2f}"
    )


# ══════════════════════════════════════════════════════════════════════
# Zamanlayıcı
# ══════════════════════════════════════════════════════════════════════
def zamanlayici(durum: BaglamDurumu, zarar: ZararTakibi,
                kayitci: Kayitci) -> None:
    """
    Dakikalık ana döngü:
        her 15 dk  → makro
        her 60 dk  → takvim
        her 240 dk → uzun vadeli katman (+ haber)
        diğer dk   → RSS taraması + kısa vadeli katman
        gün devri  → günlük özet bildirimi
    """
    zarar.gun_kontrol()
    haber_guncelle(durum)
    makro_guncelle(durum)
    takvim_guncelle(durum)
    analiz_hatti(UZUN, durum, zarar, kayitci)

    dakika = 0
    while True:
        try:
            time.sleep(60)
            dakika += 1

            devir = zarar.gun_kontrol()
            if devir:
                biten_gun, acik_zarar = devir
                gunluk_ozet_gonder(kayitci, biten_gun, acik_zarar)

            if dakika % 15 == 0:
                makro_guncelle(durum)

            if dakika % 60 == 0:
                takvim_guncelle(durum)

            if dakika % 240 == 0:
                haber_guncelle(durum)
                analiz_hatti(UZUN, durum, zarar, kayitci)
            else:
                # RSS her 5 dakikada bir: 3 feed + FinBERT toplu çağrısı
                # 10-20 sn sürüyor, her dakika yapmak hem döngüyü
                # yavaşlatır hem feed sağlayıcılarını gereksiz yorar.
                # Haber akışı dakikalık çözünürlük gerektirmiyor.
                if dakika % RSS_PERIYOT_DK == 0:
                    yeni = news_agent.rss_kontrol()
                    if yeni:
                        print(f"  [RSS] {len(yeni)} yeni haber işlendi "
                              f"(son: {yeni[-1]['sentiment']})")
                analiz_hatti(KISA, durum, zarar, kayitci)

        except KeyboardInterrupt:
            bildir_durum("Bot durduruldu (Ctrl+C).")
            print("\n\nBot durduruldu. Güle güle!")
            raise

        except Exception as e:
            print(f"\nKritik hata: {e}")
            bildir_hata(f"Kritik hata — 30 saniye sonra devam:\n{e}")
            print("30 saniye sonra devam...")
            time.sleep(30)
