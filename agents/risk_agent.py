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
from tipler import TeknikVeri, TeknikAnaliz, RiskRaporu


def calistir(teknik: TeknikVeri, teknik_analiz: TeknikAnaliz,
             haberler: dict) -> RiskRaporu:
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        mod    = teknik.mod

        # Mod'a göre ek bilgi hazırla
        if mod == "kisa":
            ek_bilgi = f"""
- Breakout: {teknik.breakout}
- Direnç  : {teknik.direnc} USD
- Destek  : {teknik.destek} USD
- ATR     : {teknik.atr} USD
- Hacim teyit: {teknik.hacim_teyit}"""
            kaldirac = config.KALDIRAC_KISA
        else:
            ek_bilgi = f"""
- RSI     : {teknik.rsi} → {teknik.rsi_yorum}
- Trend   : {teknik.trend}
- BB Üst  : {teknik.bb_ust} USD
- BB Alt  : {teknik.bb_alt} USD"""
            kaldirac = config.KALDIRAC_UZUN

        prompt = f"""
Sen muhafazakar bir risk yöneticisisin. Şüphede HAYIR dersin.

MOD: {'Kısa vadeli (Breakout)' if mod == 'kisa' else 'Uzun vadeli (Swing)'}
FİYAT: {teknik.fiyat} USD
{ek_bilgi}

TEKNİK SİNYAL: {teknik_analiz.sinyal}
HABER SENTİMENT: {haberler['sentiment']}

KALDIRAÇ: {kaldirac}x
MAX STOP-LOSS: fiyatın %{config.MAX_STOP_LOSS_PCT}'i
MAX GÜNLÜK ZARAR: ${config.MAX_GUNLUK_ZARAR}

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

        return RiskRaporu(
            risk=risk,
            onay=onay,
            max_pozisyon=max_poz,
            uyari=uyari,
        )

    except Exception as e:
        print(f"  [RİSK] ⚠️  Risk ajanı hatası ({type(e).__name__}): {e} → ONAY:HAYIR")
        # Varsayılanlar zaten muhafazakâr: risk COK_YUKSEK, onay HAYIR
        return RiskRaporu(durum="hata", uyari="Risk ajani hatasi", mesaj=str(e))
