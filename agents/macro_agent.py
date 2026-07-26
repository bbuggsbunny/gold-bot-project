import math

import yfinance as yf
from tipler import MakroRaporu


SEMBOLLER = {
    "dxy":   "DX-Y.NYB",
    "vix":   "^VIX",
    "tnx":   "^TNX",
    "sp500": "^GSPC",
}


def _veri_cek(sembol: str) -> tuple:
    """
    Son iki kapanış fiyatını döndürür: (guncel, onceki)

    NaN kontrolü kritik: yfinance zaman zaman NaN kapanış döndürüyor.
    NaN sessizce skora karışırsa toplam skor da NaN olur ve _yorumla()
    tüm karşılaştırmalardan düşüp "GUCLU_BEARISH" verir — yani veri
    eksikliği güçlü satış sinyaline dönüşür. (2026-07-26'da canlı
    kontrolde ^GSPC ile yaşandı.)
    """
    df = yf.Ticker(sembol).history(period="5d")
    if len(df) < 2:
        raise ValueError(f"{sembol} için yeterli veri yok")

    guncel  = float(df["Close"].iloc[-1])
    onceki  = float(df["Close"].iloc[-2])
    if math.isnan(guncel) or math.isnan(onceki) or onceki == 0:
        raise ValueError(f"{sembol} için geçersiz kapanış (NaN veya sıfır)")
    return guncel, onceki


def _degisim(guncel: float, onceki: float) -> float:
    return round((guncel - onceki) / onceki * 100, 4)


def _dxy_skoru(degisim: float) -> float:
    # +0.5% → -9 | -0.5% → +9 | orantılı
    ham = -(degisim / 0.5) * 9
    return round(max(-9.0, min(9.0, ham)), 2)


def _vix_skoru(degisim: float) -> float:
    # +10% → +6 | -10% → -3 | orantılı (asimetrik)
    if degisim >= 0:
        return round(min((degisim / 10) * 6, 6.0), 2)
    else:
        return round(max((degisim / 10) * 3, -3.0), 2)


def _tnx_skoru(degisim: float) -> float:
    # +2% → -5 | -2% → +5 | orantılı
    ham = -(degisim / 2) * 5
    return round(max(-5.0, min(5.0, ham)), 2)


def _sp500_skoru(degisim: float) -> float:
    # +1% → -3 | -1% → +4 | orantılı (asimetrik)
    if degisim >= 0:
        return round(max(-(degisim / 1) * 3, -3.0), 2)
    else:
        return round(min(-(degisim / 1) * 4, 4.0), 2)


def _yorumla(skor: float) -> str:
    # NaN her karşılaştırmadan False döner ve son else'e düşerdi →
    # veri eksikliği "GUCLU_BEARISH" olurdu. Açıkça yakala.
    if math.isnan(skor):
        return "NOTR"
    if skor >= 15:
        return "GUCLU_BULLISH"
    elif skor >= 8:
        return "BULLISH"
    elif skor >= 3:
        return "ZAYIF_BULLISH"
    elif skor > -3:
        return "NOTR"
    elif skor > -8:
        return "ZAYIF_BEARISH"
    elif skor > -15:
        return "BEARISH"
    else:
        return "GUCLU_BEARISH"


def calistir() -> MakroRaporu:
    SKORLAYICILAR = {
        "dxy":   _dxy_skoru,
        "vix":   _vix_skoru,
        "tnx":   _tnx_skoru,
        "sp500": _sp500_skoru,
    }

    try:
        degisimler = {}
        puanlar    = {}
        eksik      = []

        # Bir sembol alınamazsa o bileşen 0 puan katkı verir ve raporlanır;
        # diğer üçünün sinyali korunur. Sessizce NaN yayılmaz.
        for ad, sembol in SEMBOLLER.items():
            try:
                guncel, onceki = _veri_cek(sembol)
                d = _degisim(guncel, onceki)
                # İkinci savunma hattı: NaN _veri_cek'ten sızmış olabilir
                # (ör. test sahtesi ya da ileride değişen bir veri kaynağı).
                if math.isnan(d):
                    raise ValueError("değişim NaN")
                puan = SKORLAYICILAR[ad](d)
                if math.isnan(puan):
                    raise ValueError("puan NaN")
                degisimler[ad] = d
                puanlar[ad]    = puan
            except Exception as e:
                print(f"  [MAKRO] ⚠️  {ad} ({sembol}) alınamadı: {e} → 0 puan")
                degisimler[ad] = 0.0
                puanlar[ad]    = 0.0
                eksik.append(ad)

        if len(eksik) == len(SEMBOLLER):
            return MakroRaporu.hata("Hiçbir makro sembolü alınamadı")

        dxy_d, vix_d, tnx_d, sp500_d = (degisimler["dxy"], degisimler["vix"],
                                        degisimler["tnx"], degisimler["sp500"])
        dxy_p, vix_p, tnx_p, sp500_p = (puanlar["dxy"], puanlar["vix"],
                                        puanlar["tnx"], puanlar["sp500"])

        skor = round(dxy_p + vix_p + tnx_p + sp500_p, 2)

        return MakroRaporu(
            skor=skor,
            yorum=_yorumla(skor),
            dxy_degisim=dxy_d,
            vix_degisim=vix_d,
            tnx_degisim=tnx_d,
            sp500_degisim=sp500_d,
            detay={
                "dxy_puan":   dxy_p,
                "vix_puan":   vix_p,
                "tnx_puan":   tnx_p,
                "sp500_puan": sp500_p,
                "eksik":      eksik,
            },
        )

    except Exception as e:
        print(f"  [MAKRO] ⚠️  Makro ajanı hatası ({type(e).__name__}): {e} → skor 0")
        return MakroRaporu.hata(e)


if __name__ == "__main__":
    import json
    print("=== MAKRO AJAN ===")
    print(json.dumps(calistir().sozluk(), indent=2, ensure_ascii=False))
