# agents/risk_agent.py
# ─────────────────────────────────────────────
# Risk Yöneticisi Ajanı
# Hem kısa hem uzun vadeli veriyle çalışır
# ─────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import config


def calistir(teknik: dict, teknik_analiz: dict, haberler: dict) -> dict:
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        mod    = teknik.get("mod", "uzun")

        # Mod'a göre ek bilgi hazırla
        if mod == "kisa":
            ek_bilgi = f"""
- Breakout: {teknik.get('breakout', 'YOK')}
- Direnç  : {teknik.get('direnc', '-')} USD
- Destek  : {teknik.get('destek', '-')} USD
- ATR     : {teknik.get('atr', '-')} USD
- Hacim teyit: {teknik.get('hacim_teyit', False)}"""
            kaldirac = config.KALDIRAC_KISA
        else:
            ek_bilgi = f"""
- RSI     : {teknik.get('rsi', '-')} → {teknik.get('rsi_yorum', '-')}
- Trend   : {teknik.get('trend', '-')}
- BB Üst  : {teknik.get('bb_ust', '-')} USD
- BB Alt  : {teknik.get('bb_alt', '-')} USD"""
            kaldirac = config.KALDIRAC_UZUN

        prompt = f"""
Sen muhafazakar bir risk yöneticisisin. Şüphede HAYIR dersin.

MOD: {'Kısa vadeli (Breakout)' if mod == 'kisa' else 'Uzun vadeli (Swing)'}
FİYAT: {teknik['fiyat']} USD
{ek_bilgi}

TEKNİK SİNYAL: {teknik_analiz['sinyal']}
HABER SENTİMENT: {haberler['sentiment']}

KALDIRAÇ: {kaldirac}x
MAX GÜNLÜK ZARAR: ${config.MAX_STOP_LOSS_PCT}

SADECE şu 4 satırı yaz:
RISK: DUSUK veya ORTA veya YUKSEK veya COK_YUKSEK
ONAY: EVET veya HAYIR
MAX_POZISYON: sayı
UYARI: tek cumle turkce
"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system="Sen muhafazakar risk yöneticisisin. Sermayeyi korumak önce gelir.",
            messages=[{"role": "user", "content": prompt}]
        )

        ham      = response.content[0].text.strip()
        risk     = "YUKSEK"
        onay     = "HAYIR"
        max_poz  = config.QUANTITY
        uyari    = ""

        for satir in ham.split("\n"):
            satir = satir.strip()
            if satir.startswith("RISK:"):
                risk = satir.replace("RISK:", "").strip()
            elif satir.startswith("ONAY:"):
                onay = satir.replace("ONAY:", "").strip()
            elif satir.startswith("MAX_POZISYON:"):
                try:
                    max_poz = float(satir.replace("MAX_POZISYON:", "").strip())
                except:
                    pass
            elif satir.startswith("UYARI:"):
                uyari = satir.replace("UYARI:", "").strip()

        return {
            "durum":        "ok",
            "risk":         risk,
            "onay":         onay,
            "max_pozisyon": max_poz,
            "uyari":        uyari
        }

    except Exception as e:
        return {
            "durum":        "hata",
            "risk":         "COK_YUKSEK",
            "onay":         "HAYIR",
            "max_pozisyon": 0,
            "uyari":        "Risk ajani hatasi",
            "mesaj":        str(e)
        }
