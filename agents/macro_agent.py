import yfinance as yf
from tipler import MakroRaporu


SEMBOLLER = {
    "dxy":   "DX-Y.NYB",
    "vix":   "^VIX",
    "tnx":   "^TNX",
    "sp500": "^GSPC",
}


def _veri_cek(sembol: str) -> tuple:
    """Son iki kapanış fiyatını döndürür: (guncel, onceki)"""
    df = yf.Ticker(sembol).history(period="5d")
    if len(df) < 2:
        raise ValueError(f"{sembol} için yeterli veri yok")
    return float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])


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
    try:
        dxy_gun,   dxy_onc   = _veri_cek(SEMBOLLER["dxy"])
        vix_gun,   vix_onc   = _veri_cek(SEMBOLLER["vix"])
        tnx_gun,   tnx_onc   = _veri_cek(SEMBOLLER["tnx"])
        sp500_gun, sp500_onc = _veri_cek(SEMBOLLER["sp500"])

        dxy_d   = _degisim(dxy_gun,   dxy_onc)
        vix_d   = _degisim(vix_gun,   vix_onc)
        tnx_d   = _degisim(tnx_gun,   tnx_onc)
        sp500_d = _degisim(sp500_gun, sp500_onc)

        dxy_p   = _dxy_skoru(dxy_d)
        vix_p   = _vix_skoru(vix_d)
        tnx_p   = _tnx_skoru(tnx_d)
        sp500_p = _sp500_skoru(sp500_d)

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
            },
        )

    except Exception as e:
        print(f"  [MAKRO] ⚠️  Makro ajanı hatası ({type(e).__name__}): {e} → skor 0")
        return MakroRaporu.hata(e)


if __name__ == "__main__":
    import json
    print("=== MAKRO AJAN ===")
    print(json.dumps(calistir().sozluk(), indent=2, ensure_ascii=False))
