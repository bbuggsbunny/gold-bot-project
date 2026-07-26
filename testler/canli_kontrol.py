#!/usr/bin/env python3
"""
testler/canli_kontrol.py
────────────────────────
GERÇEK API'lerle uçtan uca ön kontrol — EMİR GÖNDERMEZ.

Duman testi her şeyi sahteliyor; bu betik tam tersini yapar: Binance,
Claude, yfinance, investing.com ve FinBERT'e gerçekten gider, ama
order_agent'a hiç dokunmaz (dokunulursa betik hata verip durur).

Amacı:
  • config.MODEL_ANALIZ gerçekten çalışıyor mu
  • Claude'un GERÇEK yanıtları alanlari_ayristir() ile doğru okunuyor mu
  • Dış servisler refactor sonrası ayakta mı

Maliyet: 3 Claude çağrısı (~$0.003). Emir: sıfır. Pozisyon: sıfır.

Çalıştırma:
    ~/gold-bot/bin/python3 testler/canli_kontrol.py
    ~/gold-bot/bin/python3 testler/canli_kontrol.py --habersiz   # RSS/FinBERT atla
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import traceback

import config
import claude_istemci

HABERSIZ = "--habersiz" in sys.argv

# ── Claude çağrılarının ham yanıtını kaydet ───────────────────────────
_cagrilar = []
_orijinal_sor = claude_istemci.sor


def _kayitli_sor(prompt, sistem, model=None, max_tokens=200, araclar=None):
    t0 = time.time()
    ham = _orijinal_sor(prompt, sistem, model, max_tokens, araclar)
    _cagrilar.append({
        "model": model or config.MODEL_ANALIZ,
        "sure": time.time() - t0,
        "ham": ham,
    })
    return ham


claude_istemci.sor = _kayitli_sor

# ── Emir gönderimini kesin olarak engelle ─────────────────────────────
from agents import order_agent


def _emir_yasak(*a, **kw):
    raise AssertionError(
        "canli_kontrol.py emir göndermemeli! order_agent.calistir çağrıldı."
    )


order_agent.calistir = _emir_yasak

from agents import (data_agent, technical_agent, risk_agent, decision_agent,
                    news_agent, macro_agent, calendar_agent)
from tipler import HaberRaporu

BASLIK = "═" * 66


def bolum(no: str, ad: str):
    print(f"\n{BASLIK}\n  [{no}] {ad}\n{BASLIK}")


def main():
    print(BASLIK)
    print("  CANLI ÖN KONTROL — gerçek API'ler, EMİR YOK")
    print(f"  Mod: {'TESTNET' if config.TESTNET else '*** GERÇEK PARA ***'}")
    print(f"  Analiz modeli: {config.MODEL_ANALIZ}")
    print(f"  Haber modeli : {config.MODEL_HABER}")
    print(BASLIK)

    hatalar = []

    # ── 0. Hesap ──────────────────────────────────────────────────
    bolum("0/6", "Binance hesabı — işlem yapabilir mi?")
    hesap = order_agent.hesap_kontrol()
    if hesap["durum"] != "ok":
        print(f"  ✗ Hesap sorgulanamadı: {hesap['mesaj']}")
        hatalar.append("hesap")
    elif not hesap["islem_yapabilir"]:
        print("  ✗ HESAP İŞLEM YAPAMAZ (canTrade=False)")
        print(f"    Bakiye: {hesap['bakiye']:.2f} USDT")
        print("    Binance Futures testnet hesapları periyodik sıfırlanır.")
        print("    → testnet.binancefuture.com adresinden yeni anahtar alıp")
        print("      .env dosyasını güncelle. Bot sinyal üretir ama her emir")
        print("      reddedilir.")
        hatalar.append("hesap: canTrade=False")
    elif hesap["bakiye"] <= 0:
        print(f"  ✗ Bakiye yok ({hesap['bakiye']:.2f} USDT) — emir açılamaz")
        hatalar.append("hesap: bakiye yok")
    else:
        print(f"  ✓ İşlem açık | Bakiye: {hesap['bakiye']:.2f} USDT")

    # ── 1. Makro ──────────────────────────────────────────────────
    bolum("1/6", "macro_agent — yfinance (DXY/VIX/TNX/SP500)")
    makro = macro_agent.calistir()
    if makro.basarili:
        print(f"  ✓ Skor {makro.skor:+.1f} → {makro.yorum}")
        print(f"    DXY:{makro.dxy_degisim:+.2f}%  VIX:{makro.vix_degisim:+.2f}%  "
              f"TNX:{makro.tnx_degisim:+.2f}%  SP500:{makro.sp500_degisim:+.2f}%")
    else:
        print(f"  ✗ HATA: {makro.mesaj}")
        hatalar.append("macro_agent")

    # ── 2. Takvim ─────────────────────────────────────────────────
    bolum("2/6", "calendar_agent — investing.com")
    takvim = calendar_agent.calistir()
    if takvim.basarili:
        print(f"  ✓ Mod: {takvim.mod} | Yaklaşan: {len(takvim.yaklasan_olaylar)} olay")
        for o in takvim.yaklasan_olaylar[:3]:
            print(f"    • {o.isim} — {o.saat_sonra:.1f} saat sonra (etki:{o.etki})")
    else:
        print(f"  ✗ HATA: {takvim.mesaj}")
        hatalar.append("calendar_agent")

    # ── 3. Haber ──────────────────────────────────────────────────
    bolum("3/6", "news_agent — RSS + FinBERT" + (" (ATLANDI)" if HABERSIZ else ""))
    if HABERSIZ:
        haber = HaberRaporu(sentiment="NOTR", ozet="(--habersiz ile atlandı)")
        print("  — atlandı")
    else:
        t0 = time.time()
        haber = news_agent.calistir()
        if haber.basarili:
            print(f"  ✓ Sentiment: {haber.sentiment} | Skor: {haber.haber_skoru:.1f} "
                  f"({time.time() - t0:.0f}s)")
            print(f"    Özet: {haber.ozet[:70]}")
            print(f"    Hafızadaki haber: {len(news_agent._haber_hafizasi)}")
        else:
            print(f"  ✗ HATA: {haber.mesaj}")
            hatalar.append("news_agent")

    # ── 4. Binance verisi ─────────────────────────────────────────
    bolum("4/6", "data_agent — Binance futures")
    kisa = data_agent.kisa_vadeli_veri()
    uzun = data_agent.uzun_vadeli_veri()

    if kisa.basarili:
        print(f"  ✓ Kısa (1dk): {kisa.fiyat} USD | Breakout: {kisa.breakout} | "
              f"ATR: {kisa.atr}")
        print(f"    Direnç {kisa.direnc} / Destek {kisa.destek} | "
              f"Hacim teyit: {kisa.hacim_teyit}")
    else:
        print(f"  ✗ Kısa veri HATA: {kisa.mesaj}")
        hatalar.append("data_agent.kisa")

    if uzun.basarili:
        print(f"  ✓ Uzun (15dk): {uzun.fiyat} USD | RSI: {uzun.rsi} ({uzun.rsi_yorum}) | "
              f"Trend: {uzun.trend}")
        print(f"    MACD {uzun.macd} / sinyal {uzun.macd_sinyal} | "
              f"BB {uzun.bb_alt}–{uzun.bb_ust}")
    else:
        print(f"  ✗ Uzun veri HATA: {uzun.mesaj}")
        hatalar.append("data_agent.uzun")

    if not uzun.basarili:
        print("\n  Binance verisi alınamadı — Claude zinciri atlanıyor.")
        return _ozet(hatalar)

    # ── 5. Claude zinciri (uzun katman üzerinden) ─────────────────
    bolum("5/6", f"Claude zinciri — {config.MODEL_ANALIZ}")

    analiz = technical_agent.calistir(uzun)
    if analiz.basarili:
        print(f"  ✓ technical_agent → sinyal={analiz.sinyal} sl={analiz.sl} tp={analiz.tp}")
        print(f"    yorum: {analiz.yorum[:70]}")
    else:
        print(f"  ✗ technical_agent HATA: {analiz.mesaj}")
        hatalar.append("technical_agent")

    risk = risk_agent.calistir(uzun, analiz, haber)
    if risk.basarili:
        print(f"  ✓ risk_agent → risk={risk.risk} onay={risk.onay} "
              f"max_poz={risk.max_pozisyon}")
        print(f"    uyarı: {risk.uyari[:70]}")
    else:
        print(f"  ✗ risk_agent HATA: {risk.mesaj}")
        hatalar.append("risk_agent")

    karar = decision_agent.calistir(uzun, haber, analiz, risk,
                                    makro=makro, takvim=takvim)
    if karar.basarili:
        print(f"  ✓ decision_agent → KARAR={karar.eylem} güven={karar.guven}/10")
        print(f"    SL %{karar.stop_loss_pct} / TP %{karar.take_profit_pct}")
        print(f"    gerekçe: {karar.gerekce[:70]}")
    else:
        print(f"  ✗ decision_agent HATA: {karar.mesaj}")
        hatalar.append("decision_agent")

    # ── 6. Ham yanıt incelemesi ───────────────────────────────────
    bolum("6/6", "Claude'un HAM yanıtları — ayrıştırma doğrulaması")
    for i, c in enumerate(_cagrilar, 1):
        print(f"\n  ── Çağrı {i} | {c['model']} | {c['sure']:.1f}s ──")
        for satir in c["ham"].split("\n"):
            print(f"     │ {satir}")

    # Emir gönderilir miydi?
    print(f"\n{BASLIK}")
    if karar.islem_var and karar.guven >= config.MIN_GUVEN_SKORU:
        print(f"  ►► Canlı bot olsaydı EMİR GÖNDERİRDİ: {karar.eylem} "
              f"@ {uzun.fiyat} ({config.KALDIRAC_UZUN}x)")
    else:
        print(f"  ►► Emir gönderilmezdi (karar={karar.eylem}, "
              f"güven={karar.guven}/{config.MIN_GUVEN_SKORU})")
    print("  ►► Bu betik hiçbir emir göndermedi.")

    return _ozet(hatalar)


def _ozet(hatalar):
    print(f"\n{BASLIK}")
    if hatalar:
        print(f"  SONUÇ: {len(hatalar)} bileşende hata → {', '.join(hatalar)}")
    else:
        print(f"  SONUÇ: tüm bileşenler çalışıyor  |  "
              f"{len(_cagrilar)} Claude çağrısı yapıldı")
    print(BASLIK)
    return 1 if hatalar else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\n\n!!! {e}")
        sys.exit(2)
    except Exception:
        traceback.print_exc()
        sys.exit(3)
