import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import json
import config
from tipler import TeknikVeri, KisaVeri, UzunVeri, TeknikAnaliz, RiskRaporu, Karar


def _yon(deger: str | float, tip: str) -> str:
    """Farklı kaynaklardan yön bilgisi çıkarır: BULLISH / BEARISH / NOTR"""
    if tip == "sentiment":
        return str(deger).upper() if str(deger).upper() in ("BULLISH", "BEARISH") else "NOTR"
    if tip == "makro":
        skor = float(deger)
        if skor > 3:
            return "BULLISH"
        if skor < -3:
            return "BEARISH"
        return "NOTR"
    if tip == "teknik":
        s = str(deger).upper()
        if "AL" in s:
            return "BULLISH"
        if "SAT" in s:
            return "BEARISH"
        return "NOTR"
    return "NOTR"


def calistir(
    teknik: TeknikVeri,
    haberler: dict,
    teknik_analiz: TeknikAnaliz,
    risk: RiskRaporu,
    makro: dict | None = None,
    takvim: dict | None = None,
) -> Karar:
    try:
        # ── 1. Takvim koruması (Claude'a sormadan) ──────────────────
        takvim_mod = takvim.get("mod", "NORMAL") if takvim else "NORMAL"

        if takvim_mod == "YUKSEK_RISK":
            return Karar(
                stop_loss_pct=config.MAX_STOP_LOSS_PCT,
                take_profit_pct=config.MAX_TAKE_PROFIT_PCT,
                gerekce="Yüksek etkili ekonomik veri bekleniyor",
            )

        # Dikkatli mod → min güven eşiği yükselir
        min_guven = 8 if takvim_mod == "DIKKATLI" else config.MIN_GUVEN_SKORU

        # ── 2. Risk ajanı HAYIR → Claude'a sorma ────────────────────
        if not risk.onayli:
            return Karar(
                stop_loss_pct=config.MAX_STOP_LOSS_PCT,
                take_profit_pct=config.MAX_TAKE_PROFIT_PCT,
                gerekce=f"Risk ajani engelledi: {risk.uyari}",
            )

        # ── 3. Makro özeti ───────────────────────────────────────────
        makro_skor = makro["skor"] if makro else 0
        if makro_skor > 8:
            makro_mesaj = "Makro güçlü BULLISH (DXY zayıf, VIX yüksek, SP500 düşük)"
        elif makro_skor > 3:
            makro_mesaj = f"Makro hafif BULLISH (skor: {makro_skor:+.1f})"
        elif makro_skor >= -3:
            makro_mesaj = f"Makro nötr (skor: {makro_skor:+.1f})"
        elif makro_skor >= -8:
            makro_mesaj = f"Makro hafif BEARISH (skor: {makro_skor:+.1f})"
        else:
            makro_mesaj = "Makro güçlü BEARISH (DXY güçlü, risk iştahı yüksek)"

        # Destek/direnç veri ajanından gelir, teknik analizden değil:
        # kısa katmanda breakout seviyeleri, uzun katmanda Bollinger bantları.
        if isinstance(teknik, KisaVeri):
            seviyeler = (f"\n- Destek: {teknik.destek} USD"
                         f"\n- Direnç: {teknik.direnc} USD")
        elif isinstance(teknik, UzunVeri):
            seviyeler = (f"\n- BB Alt: {teknik.bb_alt} USD"
                         f"\n- BB Üst: {teknik.bb_ust} USD")
        else:
            seviyeler = ""

        takvim_ozet = ""
        if takvim_mod == "DIKKATLI":
            yaklasan = takvim.get("yaklasan_olaylar", []) if takvim else []
            if yaklasan:
                en_yakin = yaklasan[0]
                takvim_ozet = (
                    f"\nDİKKAT: {en_yakin['isim']} — "
                    f"{en_yakin['saat_sonra']:.1f} saat sonra (etki:{en_yakin['etki']})"
                )

        # ── 4. Claude prompt ─────────────────────────────────────────
        prompt = f"""Sen deneyimli bir baş tradersin. 3 uzmanının raporunu okudun.
Şimdi nihai al/sat/bekle kararını vereceksin.

FİYAT: {teknik.fiyat} USD

MAKRO DURUM: {makro_mesaj}{takvim_ozet}

HABER ANALİSTİ RAPORU:
- Sentiment: {haberler['sentiment']}
- Özet: {haberler['ozet']}

TEKNİK ANALİST RAPORU:
- Sinyal: {teknik_analiz.sinyal}{seviyeler}
- Yorum: {teknik_analiz.yorum}

RİSK YÖNETİCİSİ RAPORU:
- Risk seviyesi: {risk.risk}
- Onay: {risk.onay}
- Max pozisyon: {risk.max_pozisyon} oz
- Uyarı: {risk.uyari}

SADECE JSON yaz, başka hiçbir şey yazma:
{{"karar": "AL", "guven": 7, "stop_loss_pct": 0.5, "take_profit_pct": 1.0, "gerekce": "kisa turkce aciklama"}}

karar: AL veya SAT veya BEKLE
guven: 1-10 (min geçerli güven: {min_guven})
stop_loss_pct: max {config.MAX_STOP_LOSS_PCT}
take_profit_pct: max {config.MAX_TAKE_PROFIT_PCT}"""

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system="Sen tüm uzmanları dinleyen baş tradersin. Uzlaşı ararsın. Risk yöneticisine saygı duyarsın.",
            messages=[{"role": "user", "content": prompt}],
        )

        ham = response.content[0].text.strip()
        ham = ham.replace("```json", "").replace("```", "").strip()
        ham_karar = json.loads(ham)

        # Claude'un JSON anahtarı "karar"; kod içindeki alan adı "eylem"
        karar = Karar(
            eylem=ham_karar["karar"],
            guven=ham_karar["guven"],
            stop_loss_pct=ham_karar["stop_loss_pct"],
            take_profit_pct=ham_karar["take_profit_pct"],
            gerekce=ham_karar.get("gerekce", ""),
        )
        claude_karari = (karar.eylem, karar.guven)

        # ── 5. Ağırlıklı karar sistemi ───────────────────────────────
        makro_yon  = _yon(makro_skor, "makro")
        haber_yon  = _yon(haberler.get("sentiment", "NOTR"), "sentiment")
        teknik_yon = _yon(teknik_analiz.sinyal, "teknik")

        makro_haber_ayni = (makro_yon == haber_yon and makro_yon != "NOTR")

        if makro_haber_ayni:
            if teknik_yon == makro_yon:
                # Üç sinyal aynı yön → güven +2
                karar.guven = min(10, karar.guven + 2)
                karar.gerekce += " [Makro+haber+teknik hizalı, güven artırıldı]"
            elif teknik_yon != "NOTR":
                # Makro+haber aynı yön ama teknik zıt → çelişki şiddetine göre karar
                if abs(makro_skor) > 6:
                    # Güçlü çelişki (skor >±6): teknik sinyali geçersiz say
                    karar.eylem = "BEKLE"
                    karar.guven = 0
                    karar.gerekce = (
                        f"Güçlü makro ({makro_skor:+.1f}) ve {makro_yon} haber "
                        "teknik sinyalle çelişiyor, bekle"
                    )
                else:
                    # Zayıf/orta çelişki: Claude prompt'ta zaten gördü, kararını koru
                    karar.gerekce += (
                        f" [Makro/haber hafif ters ({makro_skor:+.1f}), teknik baskın]"
                    )
        # Ağırlıklandırma Claude'un kararını değiştirdiyse görünür olsun
        if (karar.eylem, karar.guven) != claude_karari:
            print(f"  [KARAR] Claude: {claude_karari[0]}/{claude_karari[1]} → "
                  f"ağırlıklı: {karar.eylem}/{karar.guven} "
                  f"(makro:{makro_yon} haber:{haber_yon} teknik:{teknik_yon})")

        # ── 6. Minimum güven kontrolü ────────────────────────────────
        if karar.guven < min_guven:
            karar.eylem = "BEKLE"

        karar.stop_loss_pct   = min(karar.stop_loss_pct,   config.MAX_STOP_LOSS_PCT)
        karar.take_profit_pct = min(karar.take_profit_pct, config.MAX_TAKE_PROFIT_PCT)

        return karar

    except Exception as e:
        # Hatayı sessizce BEKLE'ye çevirmek canlı akışı iki ay boyunca
        # görünmez şekilde bloke etti — artık her zaman log'a düşer.
        print(f"  [KARAR] ⚠️  Karar ajanı hatası ({type(e).__name__}): {e} → BEKLE")
        # Varsayılan zaten BEKLE / güven 0
        return Karar(durum="hata", gerekce="Karar ajani hatasi", mesaj=str(e))


if __name__ == "__main__":
    """
    Karar mantığının senaryo testleri.

    Sözlük yerine dataclass kullanılıyor: alan adı yanlış yazılırsa
    kod burada TypeError verir, sessizce geçip canlıda patlamaz.
    Hattın tamamı için: python3 testler/duman_testi.py
    """
    from tipler import KisaVeri, UzunVeri, TeknikAnaliz, RiskRaporu

    teknik_breakout = KisaVeri(
        fiyat=3350.00, degisim_pct=0.42, yuksek=3352.0, dusuk=3344.0,
        direnc=3348.0, destek=3320.0, atr=6.5,
        hacim=1200.0, hacim_ort=900.0, hacim_teyit=True, breakout="YUKARI",
        son_5_kapanis=[3330.0, 3335.0, 3341.0, 3346.0, 3350.0],
    )
    teknik_uzun = UzunVeri(
        fiyat=4536.26, degisim_pct=-0.038, rsi=40.71, rsi_yorum="NOTR",
        macd=-0.2354, macd_sinyal=0.3983, macd_hist=-0.6337,
        ma20=4539.76, ma50=4537.70, bb_ust=4545.0, bb_alt=4528.0,
        atr=4.2, trend="YUKARI",
        son_5_kapanis=[4536.36, 4537.01, 4537.97, 4538.0, 4536.26],
    )
    analiz_guclu_al = TeknikAnaliz(
        mod="kisa", sinyal="GUCLU_AL", sl=3343.5, tp=3369.5,
        yorum="Güçlü momentum, direnci kırdı, breakout onaylandı.",
    )
    analiz_zayif_sat = TeknikAnaliz(
        mod="uzun", sinyal="ZAYIF_SAT", sl=4540.0, tp=4515.0,
        yorum="MACD negatif, kısa vadeli baskı var.",
    )
    risk_evet = RiskRaporu(risk="ORTA", onay="EVET", max_pozisyon=0.01,
                           uyari="Kaldıraç düşük tutulmalı.")

    haber_bearish       = {"sentiment": "BEARISH",
                           "ozet": "Fed faiz artırımı beklentisi altını baskılıyor."}
    makro_zayif_bearish = {"skor": -4.5,  "yorum": "Hafif bearish"}
    makro_guclu_bearish = {"skor": -10.5, "yorum": "Güçlü bearish"}
    takvim_dikkatli     = {"mod": "DIKKATLI", "yaklasan_olaylar": [
        {"isim": "CPI Release", "etki": 9, "saat_sonra": 2.5}]}

    def _yaz(baslik: str, beklenti: str, sonuc: Karar):
        print("\n" + "=" * 62)
        print(f"{baslik}\n  Beklenti: {beklenti}")
        print("=" * 62)
        print(f"  → karar={sonuc.eylem}  güven={sonuc.guven}  durum={sonuc.durum}")
        print(f"    gerekçe: {sonuc.gerekce}")

    _yaz("TEST 1: Breakout AL + makro hafif bearish + haber BEARISH",
         "güven >= 6, karar AL (zayıf çelişki kararı bozmamalı)",
         calistir(teknik_breakout, haber_bearish, analiz_guclu_al, risk_evet,
                  makro=makro_zayif_bearish))

    _yaz("TEST 2: Breakout AL + makro GÜÇLÜ bearish (-10.5) + haber BEARISH",
         "BEKLE (güçlü çelişki koruması)",
         calistir(teknik_breakout, haber_bearish, analiz_guclu_al, risk_evet,
                  makro=makro_guclu_bearish))

    _yaz("TEST 3: Makro parametresi yok",
         "Claude kararı aynen geçer",
         calistir(teknik_uzun, haber_bearish, analiz_zayif_sat, risk_evet))

    _yaz("TEST 4: Makro güçlü bearish + takvim DIKKATLI",
         "min güven 8'e yükselir",
         calistir(teknik_uzun, haber_bearish, analiz_zayif_sat, risk_evet,
                  makro=makro_guclu_bearish, takvim=takvim_dikkatli))

    _yaz("TEST 5: Takvim YUKSEK_RISK",
         "Claude'a sorulmadan BEKLE",
         calistir(teknik_uzun, haber_bearish, analiz_zayif_sat, risk_evet,
                  takvim={"mod": "YUKSEK_RISK", "yaklasan_olaylar": []}))
