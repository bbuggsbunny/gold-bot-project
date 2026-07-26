# agents/technical_agent.py
# ─────────────────────────────────────────────
# Teknik Analist Ajanı:
# Kısa vadeli → Breakout analizi
# Uzun vadeli → RSI/MACD/BB analizi
# ─────────────────────────────────────────────

import config
import claude_istemci
from tipler import TeknikVeri, TeknikAnaliz


def calistir(teknik: TeknikVeri) -> TeknikAnaliz:
    try:
        mod = teknik.mod

        if mod == "kisa":
            prompt = f"""
Sen kısa vadeli bir teknik analistsin. Breakout stratejisi kullanıyorsun.

VERİLER:
- Fiyat    : {teknik.fiyat} USD
- Yüksek   : {teknik.yuksek} USD
- Düşük    : {teknik.dusuk} USD
- Direnç   : {teknik.direnc} USD (son 20 mumun en yükseği)
- Destek   : {teknik.destek} USD (son 20 mumun en düşüğü)
- ATR      : {teknik.atr} USD
- Hacim    : {teknik.hacim} (Ortalama: {teknik.hacim_ort})
- Hacim teyit: {teknik.hacim_teyit}
- Breakout : {teknik.breakout}

SADECE şu 4 satırı yaz:
SINYAL: GUCLU_AL veya ZAYIF_AL veya NOTR veya ZAYIF_SAT veya GUCLU_SAT
SL_FIYAT: sayı (ATR x 1.0 uzakta)
TP_FIYAT: sayı (ATR x 3.0 uzakta)
YORUM: tek cumle turkce
"""
        else:
            prompt = f"""
Sen uzun vadeli bir teknik analistsin. RSI/MACD/Bollinger kullanıyorsun.

VERİLER:
- Fiyat    : {teknik.fiyat} USD
- RSI      : {teknik.rsi} → {teknik.rsi_yorum}
- MACD     : {teknik.macd} / Sinyal: {teknik.macd_sinyal}
- BB Üst   : {teknik.bb_ust} / Alt: {teknik.bb_alt}
- MA20     : {teknik.ma20} / MA50: {teknik.ma50}
- Trend    : {teknik.trend}
- ATR      : {teknik.atr} USD

SADECE şu 4 satırı yaz:
SINYAL: GUCLU_AL veya ZAYIF_AL veya NOTR veya ZAYIF_SAT veya GUCLU_SAT
SL_FIYAT: sayı
TP_FIYAT: sayı
YORUM: tek cumle turkce
"""

        ham = claude_istemci.sor(
            prompt,
            sistem="Sen teknik analistsin. Sadece sayı ve sinyal üretirsin.",
            max_tokens=150,
        )
        alanlar = claude_istemci.alanlari_ayristir(ham, {
            "SINYAL":    str,
            "SL_FIYAT":  float,
            "TP_FIYAT":  float,
            "YORUM":     str,
        })

        return TeknikAnaliz(
            mod=mod,
            sinyal=alanlar.get("SINYAL", "NOTR"),
            sl=round(alanlar.get("SL_FIYAT", teknik.fiyat * 0.995), 2),
            tp=round(alanlar.get("TP_FIYAT", teknik.fiyat * 1.01), 2),
            yorum=alanlar.get("YORUM", ""),
        )

    except Exception as e:
        print(f"  [TEKNİK] ⚠️  Teknik ajan hatası ({type(e).__name__}): {e} → NOTR")
        return TeknikAnaliz(
            durum="hata",
            mod=getattr(teknik, "mod", "uzun"),
            yorum="Teknik analiz alinamadi",
            mesaj=str(e),
        )


if __name__ == "__main__":
    from agents.data_agent import kisa_vadeli_veri, uzun_vadeli_veri

    print("=== KISA VADELİ TEKNİK ANALİZ ===")
    kisa = kisa_vadeli_veri()
    sonuc = calistir(kisa)
    print(f"Sinyal : {sonuc.sinyal}")
    print(f"SL     : {sonuc.sl}")
    print(f"TP     : {sonuc.tp}")
    print(f"Yorum  : {sonuc.yorum}")

    print("\n=== UZUN VADELİ TEKNİK ANALİZ ===")
    uzun = uzun_vadeli_veri()
    sonuc = calistir(uzun)
    print(f"Sinyal : {sonuc.sinyal}")
    print(f"SL     : {sonuc.sl}")
    print(f"TP     : {sonuc.tp}")
    print(f"Yorum  : {sonuc.yorum}")
