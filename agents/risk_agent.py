# agents/risk_agent.py
# ─────────────────────────────────────────────
# Risk Yöneticisi Ajanı
# Hem kısa hem uzun vadeli veriyle çalışır
# ─────────────────────────────────────────────

import config
import claude_istemci
from tipler import TeknikVeri, TeknikAnaliz, RiskRaporu, HaberRaporu


def calistir(teknik: TeknikVeri, teknik_analiz: TeknikAnaliz,
             haberler: HaberRaporu) -> RiskRaporu:
    try:
        mod = teknik.mod

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
HABER SENTİMENT: {haberler.sentiment}

KALDIRAÇ: {kaldirac}x
MAX STOP-LOSS: fiyatın %{config.MAX_STOP_LOSS_PCT}'i
MAX GÜNLÜK ZARAR: ${config.MAX_GUNLUK_ZARAR}

SADECE şu 4 satırı yaz:
RISK: DUSUK veya ORTA veya YUKSEK veya COK_YUKSEK
ONAY: EVET veya HAYIR
MAX_POZISYON: sayı
UYARI: tek cumle turkce
"""

        ham = claude_istemci.sor(
            prompt,
            sistem="Sen muhafazakar risk yöneticisisin. Sermayeyi korumak önce gelir.",
            max_tokens=1000,
        )
        alanlar = claude_istemci.alanlari_ayristir(ham, {
            "RISK":         str,
            "ONAY":         str,
            "MAX_POZISYON": float,
            "UYARI":        str,
        })

        return RiskRaporu(
            risk=alanlar.get("RISK", "YUKSEK"),
            onay=alanlar.get("ONAY", "HAYIR"),
            max_pozisyon=alanlar.get("MAX_POZISYON", config.QUANTITY),
            uyari=alanlar.get("UYARI", ""),
        )

    except Exception as e:
        print(f"  [RİSK] ⚠️  Risk ajanı hatası ({type(e).__name__}): {e} → ONAY:HAYIR")
        # Varsayılanlar zaten muhafazakâr: risk COK_YUKSEK, onay HAYIR
        return RiskRaporu(durum="hata", uyari="Risk ajani hatasi", mesaj=str(e))
