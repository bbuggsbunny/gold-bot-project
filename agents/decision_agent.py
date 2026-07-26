import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import json
import config


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
    teknik: dict,
    haberler: dict,
    teknik_analiz: dict,
    risk: dict,
    makro: dict | None = None,
    takvim: dict | None = None,
) -> dict:
    try:
        # ── 1. Takvim koruması (Claude'a sormadan) ──────────────────
        takvim_mod = takvim.get("mod", "NORMAL") if takvim else "NORMAL"

        if takvim_mod == "YUKSEK_RISK":
            return {
                "durum":           "ok",
                "karar":           "BEKLE",
                "guven":           0,
                "stop_loss_pct":   config.MAX_STOP_LOSS_PCT,
                "take_profit_pct": config.MAX_TAKE_PROFIT_PCT,
                "gerekce":         "Yüksek etkili ekonomik veri bekleniyor",
            }

        # Dikkatli mod → min güven eşiği yükselir
        min_guven = 8 if takvim_mod == "DIKKATLI" else config.MIN_GUVEN_SKORU

        # ── 2. Risk ajanı HAYIR → Claude'a sorma ────────────────────
        if risk["onay"] == "HAYIR":
            return {
                "durum":           "ok",
                "karar":           "BEKLE",
                "guven":           0,
                "stop_loss_pct":   config.MAX_STOP_LOSS_PCT,
                "take_profit_pct": config.MAX_TAKE_PROFIT_PCT,
                "gerekce":         f"Risk ajani engelledi: {risk['uyari']}",
            }

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

        # Destek/direnç veri ajanından gelir (teknik_analiz'de yok):
        # kısa modda breakout seviyeleri, uzun modda Bollinger bantları.
        if "destek" in teknik and "direnc" in teknik:
            seviyeler = (f"\n- Destek: {teknik['destek']} USD"
                         f"\n- Direnç: {teknik['direnc']} USD")
        elif "bb_alt" in teknik and "bb_ust" in teknik:
            seviyeler = (f"\n- BB Alt: {teknik['bb_alt']} USD"
                         f"\n- BB Üst: {teknik['bb_ust']} USD")
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

FİYAT: {teknik['fiyat']} USD

MAKRO DURUM: {makro_mesaj}{takvim_ozet}

HABER ANALİSTİ RAPORU:
- Sentiment: {haberler['sentiment']}
- Özet: {haberler['ozet']}

TEKNİK ANALİST RAPORU:
- Sinyal: {teknik_analiz['sinyal']}{seviyeler}
- Yorum: {teknik_analiz['yorum']}

RİSK YÖNETİCİSİ RAPORU:
- Risk seviyesi: {risk['risk']}
- Onay: {risk['onay']}
- Max pozisyon: {risk['max_pozisyon']} oz
- Uyarı: {risk['uyari']}

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
        karar = json.loads(ham)
        claude_karari = (karar["karar"], karar["guven"])

        # ── 5. Ağırlıklı karar sistemi ───────────────────────────────
        makro_yon  = _yon(makro_skor, "makro")
        haber_yon  = _yon(haberler.get("sentiment", "NOTR"), "sentiment")
        teknik_yon = _yon(teknik_analiz.get("sinyal", ""), "teknik")

        makro_haber_ayni = (makro_yon == haber_yon and makro_yon != "NOTR")

        if makro_haber_ayni:
            if teknik_yon == makro_yon:
                # Üç sinyal aynı yön → güven +2
                karar["guven"] = min(10, karar["guven"] + 2)
                karar["gerekce"] += " [Makro+haber+teknik hizalı, güven artırıldı]"
            elif teknik_yon != "NOTR":
                # Makro+haber aynı yön ama teknik zıt → çelişki şiddetine göre karar
                if abs(makro_skor) > 6:
                    # Güçlü çelişki (skor >±6): teknik sinyali geçersiz say
                    karar["karar"]  = "BEKLE"
                    karar["guven"]  = 0
                    karar["gerekce"] = (
                        f"Güçlü makro ({makro_skor:+.1f}) ve {makro_yon} haber "
                        "teknik sinyalle çelişiyor, bekle"
                    )
                else:
                    # Zayıf/orta çelişki: Claude prompt'ta zaten gördü, kararını koru
                    karar["gerekce"] += (
                        f" [Makro/haber hafif ters ({makro_skor:+.1f}), teknik baskın]"
                    )
        # Ağırlıklandırma Claude'un kararını değiştirdiyse görünür olsun
        if (karar["karar"], karar["guven"]) != claude_karari:
            print(f"  [KARAR] Claude: {claude_karari[0]}/{claude_karari[1]} → "
                  f"ağırlıklı: {karar['karar']}/{karar['guven']} "
                  f"(makro:{makro_yon} haber:{haber_yon} teknik:{teknik_yon})")

        # ── 6. Minimum güven kontrolü ────────────────────────────────
        if karar["guven"] < min_guven:
            karar["karar"] = "BEKLE"

        karar["stop_loss_pct"]   = min(karar["stop_loss_pct"],   config.MAX_STOP_LOSS_PCT)
        karar["take_profit_pct"] = min(karar["take_profit_pct"], config.MAX_TAKE_PROFIT_PCT)

        return {"durum": "ok", **karar}

    except Exception as e:
        # Hatayı sessizce BEKLE'ye çevirmek canlı akışı iki ay boyunca
        # görünmez şekilde bloke etti — artık her zaman log'a düşer.
        print(f"  [KARAR] ⚠️  Karar ajanı hatası ({type(e).__name__}): {e} → BEKLE")
        return {
            "durum":           "hata",
            "karar":           "BEKLE",
            "guven":           0,
            "stop_loss_pct":   0.5,
            "take_profit_pct": 1.0,
            "gerekce":         "Karar ajani hatasi",
            "mesaj":           str(e),
        }


if __name__ == "__main__":
    import json as _json

    # ── Ortak test verileri ──────────────────────────────────────────
    # DİKKAT: Aşağıdaki sözlükler ilgili ajanın DÖNDÜRDÜĞÜ anahtarlarla
    # birebir aynı olmalı. Buraya canlıda olmayan bir anahtar eklenirse
    # test geçer ama canlı akış KeyError ile çöker (2026-07-26'da olan buydu).
    test_teknik_breakout = {   # data_agent.kisa_vadeli_veri() çıktısı
        "durum": "ok", "mod": "kisa", "fiyat": 3350.00, "degisim_pct": 0.42,
        "yuksek": 3352.0, "dusuk": 3344.0,
        "direnc": 3348.0, "destek": 3320.0, "atr": 6.5,
        "hacim": 1200.0, "hacim_ort": 900.0, "hacim_teyit": True,
        "breakout": "YUKARI",
        "son_5_kapanis": [3330.0, 3335.0, 3341.0, 3346.0, 3350.0],
    }
    test_teknik_sat = {        # data_agent.uzun_vadeli_veri() çıktısı
        "durum": "ok", "mod": "uzun", "fiyat": 4536.26, "degisim_pct": -0.038,
        "rsi": 40.71, "rsi_yorum": "NOTR",
        "macd": -0.2354, "macd_sinyal": 0.3983, "macd_hist": -0.6337,
        "ma20": 4539.76, "ma50": 4537.70,
        "bb_ust": 4545.0, "bb_alt": 4528.0, "atr": 4.2, "trend": "YUKARI",
        "son_5_kapanis": [4536.36, 4537.01, 4537.97, 4538.0, 4536.26],
    }
    test_haberler_bearish = {
        "sentiment": "BEARISH",
        "ozet": "Fed faiz artırımı beklentisi altını baskılıyor.",
        "etkenler": ["Fed faiz artışı", "güçlü dolar"],
    }
    test_analiz_guclu_al = {   # technical_agent.calistir() çıktısı
        "durum": "ok", "mod": "kisa", "sinyal": "GUCLU_AL",
        "sl": 3343.5, "tp": 3369.5,
        "yorum": "Güçlü momentum, direnci kırdı, breakout onaylandı.",
    }
    test_analiz_zayif_sat = {  # technical_agent.calistir() çıktısı
        "durum": "ok", "mod": "uzun", "sinyal": "ZAYIF_SAT",
        "sl": 4540.0, "tp": 4515.0,
        "yorum": "MACD negatif, kısa vadeli baskı var.",
    }
    test_risk_evet = {
        "risk": "ORTA", "onay": "EVET",
        "max_pozisyon": 0.01, "uyari": "Kaldıraç düşük tutulmalı.",
    }
    makro_zayif_bearish = {"skor": -4.5, "yorum": "Hafif bearish"}   # Eski kodda "nötr" görünür
    makro_guclu_bearish = {"skor": -10.5, "yorum": "Güçlü bearish"}
    test_takvim_dikkatli = {"mod": "DIKKATLI", "yaklasan_olaylar": [
        {"isim": "CPI Release", "etki": 9, "saat_sonra": 2.5}
    ]}

    # ── TEST 1: Daha önce hatalı çalışan senaryo ─────────────────────
    # Breakout GUCLU_AL + Risk EVET + Makro -4.5 (hafif bearish) + Haber BEARISH
    # Beklenti: güven >= 6 (en az min_guven), AL kararı çıkmalı
    print("=" * 60)
    print("TEST 1: Breakout AL + Makro hafif bearish + Haber BEARISH")
    print("  Beklenti: güven >= 6, karar AL")
    print("=" * 60)
    s = calistir(test_teknik_breakout, test_haberler_bearish,
                 test_analiz_guclu_al, test_risk_evet,
                 makro=makro_zayif_bearish)
    print(_json.dumps(s, indent=2, ensure_ascii=False))
    guvn = s.get("guven", 0)
    karar_s = s.get("karar", "?")
    print(f"  → SONUÇ: karar={karar_s}, güven={guvn}  "
          f"{'✓ BAŞARILI' if guvn >= 6 else '✗ HATA: güven çok düşük'}")

    # ── TEST 2: Güçlü makro çelişki → hala BEKLE bekliyoruz ─────────
    print("\n" + "=" * 60)
    print("TEST 2: Breakout AL + Makro GÜÇLÜ bearish (-10.5) + Haber BEARISH")
    print("  Beklenti: BEKLE (güçlü çelişki koruması aktif)")
    print("=" * 60)
    s = calistir(test_teknik_breakout, test_haberler_bearish,
                 test_analiz_guclu_al, test_risk_evet,
                 makro=makro_guclu_bearish)
    print(_json.dumps(s, indent=2, ensure_ascii=False))
    print(f"  → SONUÇ: karar={s.get('karar')}  "
          f"{'✓ BAŞARILI' if s.get('karar') == 'BEKLE' else '✗ HATA: bekle bekleniyordu'}")

    # ── TEST 3: Normal mod (makro yok) ───────────────────────────────
    print("\n" + "=" * 60)
    print("TEST 3: Normal mod (makro parametresi yok)")
    print("=" * 60)
    s = calistir(test_teknik_sat, test_haberler_bearish, test_analiz_zayif_sat, test_risk_evet)
    print(_json.dumps(s, indent=2, ensure_ascii=False))

    # ── TEST 4: DIKKATLI takvim + güçlü bearish makro ────────────────
    print("\n" + "=" * 60)
    print("TEST 4: MAKRO güçlü + TAKVİM dikkatli")
    print("=" * 60)
    s = calistir(test_teknik_sat, test_haberler_bearish, test_analiz_zayif_sat, test_risk_evet,
                 makro=makro_guclu_bearish, takvim=test_takvim_dikkatli)
    print(_json.dumps(s, indent=2, ensure_ascii=False))

    # ── TEST 5: YUKSEK_RISK takvim ───────────────────────────────────
    print("\n" + "=" * 60)
    print("TEST 5: YUKSEK_RISK takvim → direkt BEKLE")
    print("=" * 60)
    s = calistir(test_teknik_sat, test_haberler_bearish, test_analiz_zayif_sat, test_risk_evet,
                 takvim={"mod": "YUKSEK_RISK", "yaklasan_olaylar": []})
    print(_json.dumps(s, indent=2, ensure_ascii=False))
