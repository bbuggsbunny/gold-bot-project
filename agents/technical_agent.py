# agents/technical_agent.py
# ─────────────────────────────────────────────
# Teknik Analist Ajanı:
# Kısa vadeli → Breakout analizi
# Uzun vadeli → RSI/MACD/BB analizi
# ─────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import config


def calistir(teknik: dict) -> dict:
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        mod    = teknik.get("mod", "uzun")

        if mod == "kisa":
            prompt = f"""
Sen kısa vadeli bir teknik analistsin. Breakout stratejisi kullanıyorsun.

VERİLER:
- Fiyat    : {teknik['fiyat']} USD
- Yüksek   : {teknik['yuksek']} USD
- Düşük    : {teknik['dusuk']} USD
- Direnç   : {teknik['direnc']} USD (son 20 mumun en yükseği)
- Destek   : {teknik['destek']} USD (son 20 mumun en düşüğü)
- ATR      : {teknik['atr']} USD
- Hacim    : {teknik['hacim']} (Ortalama: {teknik['hacim_ort']})
- Hacim teyit: {teknik['hacim_teyit']}
- Breakout : {teknik['breakout']}

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
- Fiyat    : {teknik['fiyat']} USD
- RSI      : {teknik['rsi']} → {teknik['rsi_yorum']}
- MACD     : {teknik['macd']} / Sinyal: {teknik['macd_sinyal']}
- BB Üst   : {teknik['bb_ust']} / Alt: {teknik['bb_alt']}
- MA20     : {teknik['ma20']} / MA50: {teknik['ma50']}
- Trend    : {teknik['trend']}
- ATR      : {teknik['atr']} USD

SADECE şu 4 satırı yaz:
SINYAL: GUCLU_AL veya ZAYIF_AL veya NOTR veya ZAYIF_SAT veya GUCLU_SAT
SL_FIYAT: sayı
TP_FIYAT: sayı
YORUM: tek cumle turkce
"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system="Sen teknik analistsin. Sadece sayı ve sinyal üretirsin.",
            messages=[{"role": "user", "content": prompt}]
        )

        ham    = response.content[0].text.strip()
        sinyal = "NOTR"
        sl     = teknik['fiyat'] * 0.995
        tp     = teknik['fiyat'] * 1.01
        yorum  = ""

        for satir in ham.split("\n"):
            satir = satir.strip()
            if satir.startswith("SINYAL:"):
                sinyal = satir.replace("SINYAL:", "").strip()
            elif satir.startswith("SL_FIYAT:"):
                try:
                    sl = float(satir.replace("SL_FIYAT:", "").strip())
                except:
                    pass
            elif satir.startswith("TP_FIYAT:"):
                try:
                    tp = float(satir.replace("TP_FIYAT:", "").strip())
                except:
                    pass
            elif satir.startswith("YORUM:"):
                yorum = satir.replace("YORUM:", "").strip()

        return {
            "durum":  "ok",
            "mod":    mod,
            "sinyal": sinyal,
            "sl":     round(sl, 2),
            "tp":     round(tp, 2),
            "yorum":  yorum
        }

    except Exception as e:
        return {
            "durum":  "hata",
            "mod":    teknik.get("mod", "uzun"),
            "sinyal": "NOTR",
            "sl":     0,
            "tp":     0,
            "yorum":  "Teknik analiz alinamadi",
            "mesaj":  str(e)
        }


if __name__ == "__main__":
    from agents.data_agent import kisa_vadeli_veri, uzun_vadeli_veri

    print("=== KISA VADELİ TEKNİK ANALİZ ===")
    kisa = kisa_vadeli_veri()
    sonuc = calistir(kisa)
    print(f"Sinyal : {sonuc['sinyal']}")
    print(f"SL     : {sonuc['sl']}")
    print(f"TP     : {sonuc['tp']}")
    print(f"Yorum  : {sonuc['yorum']}")

    print("\n=== UZUN VADELİ TEKNİK ANALİZ ===")
    uzun = uzun_vadeli_veri()
    sonuc = calistir(uzun)
    print(f"Sinyal : {sonuc['sinyal']}")
    print(f"SL     : {sonuc['sl']}")
    print(f"TP     : {sonuc['tp']}")
    print(f"Yorum  : {sonuc['yorum']}")
