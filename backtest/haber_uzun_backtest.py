"""
backtest/haber_uzun_backtest.py
───────────────────────────────
Son 30 günlük 15dk veriyle uzun vadeli backtest.
Her gün için 1 Claude çağrısı (haberler), yfinance ile makro.
3x kaldıraç, %1 SL, %2 TP, max 1 açık pozisyon.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from datetime import datetime, timedelta

import pandas as pd
import anthropic
import yfinance as yf
from binance.client import Client
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import config

# ── Dosya yolları ──────────────────────────────────────────────────────
GECMIS_DOSYA = os.path.join(os.path.dirname(__file__), "haber_gecmis.json")
GRAFIK_DOSYA = os.path.join(os.path.dirname(__file__), "haber_uzun_backtest.png")

# ── Sabitler ───────────────────────────────────────────────────────────
BASLANGIC_KAP = 1000.0
LEVERAGE      = 3
SL_PCT        = 0.01      # fiyatın %1'i → kaldıraçlı %3
TP_PCT        = 0.02      # fiyatın %2'i → kaldıraçlı %6
MIN_GUVEN     = 6
WARMUP        = 60        # indikatör ısınma mumu sayısı

# ── Takvim (Nisan–Mayıs 2026 gerçek tarihleri) ────────────────────────
YUKSEK_RISK = {
    "2026-04-03": "NFP",
    "2026-04-10": "CPI",
    "2026-05-01": "NFP",
    "2026-05-06": "FOMC_BASLANGIC",
    "2026-05-07": "FOMC_KARAR",
    "2026-05-13": "CPI",
}

DIKKATLI = {
    "2026-04-01": "ISM_IMALAT",
    "2026-04-08": "FOMC_TUTANAK",
    "2026-04-11": "PPI",
    "2026-04-15": "PERAKENDE_SATIS",
    "2026-04-22": "PMI_FLASH",
    "2026-04-29": "TUKETICI_GUVEN",
    "2026-04-30": "PCE",
    "2026-05-08": "PPI",
    "2026-05-14": "PERAKENDE_SATIS",
    "2026-05-15": "TUKETICI_DUYGU",
    "2026-05-22": "FOMC_TUTANAK",
}


# ══════════════════════════════════════════════════════════════════════
# 1. VERİ ÇEKME — Binance (2 sayfalı istek, ~30 gün)
# ══════════════════════════════════════════════════════════════════════
def veri_cek() -> pd.DataFrame:
    """Binance'den ~30 günlük 15dk veri çeker (2 × 1500 mum = 3000 mum)."""
    client = Client(
        config.BINANCE_API_KEY,
        config.BINANCE_SECRET_KEY,
        testnet=config.TESTNET,
    )

    # 1. sayfa: en son 1500 mum
    sayfa1 = client.futures_klines(
        symbol=config.SYMBOL,
        interval=Client.KLINE_INTERVAL_15MINUTE,
        limit=1500,
    )

    # 2. sayfa: sayfa1'in başından geriye 1500 mum
    en_eski_zaman = int(sayfa1[0][0])
    sayfa2 = client.futures_klines(
        symbol=config.SYMBOL,
        interval=Client.KLINE_INTERVAL_15MINUTE,
        limit=1500,
        endTime=en_eski_zaman - 1,
    )

    tum_mumlar = sayfa2 + sayfa1

    df = pd.DataFrame(tum_mumlar, columns=[
        "zaman", "acilis", "yuksek", "dusuk", "kapanis",
        "hacim", "kapanis_zamani", "quote_hacim", "islem_sayisi",
        "taker_al", "taker_sat", "ignore",
    ])
    for s in ["acilis", "yuksek", "dusuk", "kapanis", "hacim"]:
        df[s] = df[s].astype(float)
    df["zaman"] = pd.to_datetime(df["zaman"], unit="ms")
    df = df.drop_duplicates("zaman").sort_values("zaman").reset_index(drop=True)
    return df


# ══════════════════════════════════════════════════════════════════════
# 2. HABER GEÇMİŞİ — önbellekli Claude çağrısı
# ══════════════════════════════════════════════════════════════════════
def _haber_gecmisi_yukle() -> dict:
    if os.path.exists(GECMIS_DOSYA):
        with open(GECMIS_DOSYA, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _haber_gecmisi_kaydet(gecmis: dict):
    os.makedirs(os.path.dirname(GECMIS_DOSYA), exist_ok=True)
    with open(GECMIS_DOSYA, "w", encoding="utf-8") as f:
        json.dump(gecmis, f, ensure_ascii=False, indent=2)


def _gun_haberi_cek(tarih_str: str, client: anthropic.Anthropic) -> dict:
    """Claude Haiku ile o günün altın haber analizini döner."""
    prompt = (
        f"Altın (XAU/USD) için {tarih_str} tarihine ait piyasa analizi yap.\n"
        f"Bilgi kesim tarihin Ağustos 2025 ise bile, genel makroekonomik koşullar "
        f"(Fed politikası, dolar gücü, jeopolitik riskler, enflasyon beklentileri) "
        f"çerçevesinde o dönem için makul bir tahmin üret.\n\n"
        f"SADECE şu formatı kullan, başka hiçbir şey yazma:\n"
        f"SENTIMENT: BULLISH veya BEARISH veya NOTR\n"
        f"ETKI: 1-10\n"
        f"HABER_SKORU: -15 ile +15 arasında sayı\n"
        f"OZET: tek cümle Türkçe özet"
    )
    try:
        yanit = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        metin = yanit.content[0].text.strip()
        satir = {}
        for line in metin.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                satir[k.strip()] = v.strip()
        return {
            "sentiment":   satir.get("SENTIMENT", "NOTR").upper(),
            "etki":        int(satir.get("ETKI", "5")),
            "haber_skoru": float(satir.get("HABER_SKORU", "0")),
            "ozet":        satir.get("OZET", "Veri yok"),
        }
    except Exception as e:
        print(f"  [HABER] {tarih_str} hatası: {e}")
        return {"sentiment": "NOTR", "etki": 5, "haber_skoru": 0.0, "ozet": "API hatası"}


def haberler_hazirla(gunler: list) -> dict:
    """Tüm günler için haber skorlarını döner (önbellekten veya Claude'dan)."""
    gecmis = _haber_gecmisi_yukle()
    eksik  = [g for g in gunler if g not in gecmis]

    if eksik:
        print(f"  {len(eksik)} gün için Claude sorgulanıyor ({len(gecmis)} önbellekte)...")
        claude = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        for i, g in enumerate(eksik, 1):
            print(f"    [{i:02d}/{len(eksik)}] {g} ...", end=" ", flush=True)
            gecmis[g] = _gun_haberi_cek(g, claude)
            print(gecmis[g]["sentiment"], "|", gecmis[g]["ozet"][:50])
            _haber_gecmisi_kaydet(gecmis)
            if i < len(eksik):
                time.sleep(1)
    else:
        print(f"  Tüm {len(gunler)} gün önbellekte, Claude sorgulanmıyor.")

    return gecmis


# ══════════════════════════════════════════════════════════════════════
# 3. MAKRO VERİ — yfinance tarihsel
# ══════════════════════════════════════════════════════════════════════
def _dxy_skoru(d: float) -> float:
    return round(max(-9.0, min(9.0, -(d / 0.5) * 9)), 2)

def _vix_skoru(d: float) -> float:
    if d >= 0:
        return round(min((d / 10) * 6, 6.0), 2)
    return round(max((d / 10) * 3, -3.0), 2)

def _tnx_skoru(d: float) -> float:
    return round(max(-5.0, min(5.0, -(d / 2) * 5)), 2)

def _sp500_skoru(d: float) -> float:
    if d >= 0:
        return round(max(-(d / 1) * 3, -3.0), 2)
    return round(min(-(d / 1) * 4, 4.0), 2)

def _makro_yorumla(skor: float) -> str:
    if skor >= 15:  return "GUCLU_BULLISH"
    if skor >= 8:   return "BULLISH"
    if skor >= 3:   return "ZAYIF_BULLISH"
    if skor > -3:   return "NOTR"
    if skor > -8:   return "ZAYIF_BEARISH"
    if skor > -15:  return "BEARISH"
    return "GUCLU_BEARISH"


def makro_veri_hazirla(baslangic: datetime, bitis: datetime) -> dict:
    """
    Her iş günü için makro skoru hesaplar.
    Dönüş: {"YYYY-MM-DD": {"skor": float, "yorum": str}}
    """
    semboller = {"dxy": "DX-Y.NYB", "vix": "^VIX", "tnx": "^TNX", "sp500": "^GSPC"}
    start_str = (baslangic - timedelta(days=7)).strftime("%Y-%m-%d")
    end_str   = (bitis + timedelta(days=2)).strftime("%Y-%m-%d")

    veriler = {}
    for isim, sembol in semboller.items():
        try:
            df_y = yf.download(sembol, start=start_str, end=end_str,
                               progress=False, auto_adjust=True)
            if not df_y.empty:
                seri = df_y["Close"].squeeze().dropna()
                veriler[isim] = seri
        except Exception as e:
            print(f"  [MAKRO] {isim} yüklenemedi: {e}")

    if not veriler:
        print("  [MAKRO] Hiç veri alınamadı, tüm günler skor=0.")
        return {}

    # Ortak tarihler üzerinden hesapla
    ortak = sorted(set.intersection(*[set(s.index) for s in veriler.values()]))
    makro_dict = {}

    for i in range(1, len(ortak)):
        gun    = ortak[i]
        onceki = ortak[i - 1]
        tarih_str = pd.Timestamp(gun).strftime("%Y-%m-%d")
        try:
            skor = 0.0
            for isim, seri in veriler.items():
                g = float(seri.loc[gun])
                o = float(seri.loc[onceki])
                d = (g - o) / o * 100
                if isim == "dxy":    skor += _dxy_skoru(d)
                elif isim == "vix":  skor += _vix_skoru(d)
                elif isim == "tnx":  skor += _tnx_skoru(d)
                elif isim == "sp500": skor += _sp500_skoru(d)
            makro_dict[tarih_str] = {"skor": round(skor, 2), "yorum": _makro_yorumla(skor)}
        except Exception:
            pass

    print(f"  [MAKRO] {len(makro_dict)} gün hesaplandı.")
    return makro_dict


# ══════════════════════════════════════════════════════════════════════
# 4. TEKNİK SİNYAL — kural tabanlı (RSI/MACD/BB/MA)
# ══════════════════════════════════════════════════════════════════════
def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, float("inf"))
    return float((100 - 100 / (1 + rs)).iloc[-1])


def teknik_sinyal(df: pd.DataFrame, idx: int) -> dict:
    """
    Son 60 muma kadar pencere alır.
    RSI(±1/±2) + MACD(±1) + BB(±1) + MA50(±1) → puan
    puan≥3 → AL | puan≤-3 → SAT | diğer → BEKLE
    """
    pencere = df.iloc[max(0, idx - 59): idx + 1].copy()
    close   = pencere["kapanis"]

    if len(close) < 30:
        return {"sinyal": "BEKLE", "guven": 0, "puan": 0, "rsi": 50.0, "yorum": "Yetersiz veri"}

    puan = 0
    yorumlar = []

    # RSI
    rsi = _rsi(close)
    if rsi < 30:
        puan += 2; yorumlar.append(f"RSI aşırı satım {rsi:.1f}")
    elif rsi < 45:
        puan += 1; yorumlar.append(f"RSI düşük {rsi:.1f}")
    elif rsi > 70:
        puan -= 2; yorumlar.append(f"RSI aşırı alım {rsi:.1f}")
    elif rsi > 55:
        puan -= 1; yorumlar.append(f"RSI yüksek {rsi:.1f}")

    # MACD
    macd   = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal = macd.ewm(span=9).mean()
    hist   = float((macd - signal).iloc[-1])
    if hist > 0:
        puan += 1; yorumlar.append("MACD+")
    else:
        puan -= 1; yorumlar.append("MACD-")

    # Bollinger
    ma20  = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    son   = float(close.iloc[-1])
    if son < float((ma20 - 2 * std20).iloc[-1]):
        puan += 1; yorumlar.append("BB alt")
    elif son > float((ma20 + 2 * std20).iloc[-1]):
        puan -= 1; yorumlar.append("BB üst")

    # MA50 trend
    if len(close) >= 50:
        ma50 = float(close.rolling(50).mean().iloc[-1])
        if son > ma50:
            puan += 1; yorumlar.append("MA50 üstü")
        else:
            puan -= 1; yorumlar.append("MA50 altı")

    if puan >= 3:
        sinyal = "AL"
    elif puan <= -3:
        sinyal = "SAT"
    else:
        sinyal = "BEKLE"

    guven = min(10, max(0, abs(puan) + 3))

    return {
        "sinyal": sinyal,
        "guven":  guven,
        "puan":   puan,
        "rsi":    round(rsi, 2),
        "yorum":  " | ".join(yorumlar[:2]),
    }


# ══════════════════════════════════════════════════════════════════════
# 5. KARAR MANTIĞI — kural tabanlı (Claude çağrısı yok)
# ══════════════════════════════════════════════════════════════════════
def _yon(deger, tip: str) -> str:
    if tip == "sentiment":
        s = str(deger).upper()
        return s if s in ("BULLISH", "BEARISH") else "NOTR"
    if tip == "makro":
        skor = float(deger)
        if skor > 3:  return "BULLISH"
        if skor < -3: return "BEARISH"
        return "NOTR"
    if tip == "teknik":
        s = str(deger).upper()
        if s == "AL":  return "BULLISH"
        if s == "SAT": return "BEARISH"
        return "NOTR"
    return "NOTR"


def karar_ver(teknik_s: dict, haber: dict, makro_skor: float, takvim_mod: str) -> dict:
    """decision_agent mantığını Claude çağrısı olmadan uygular."""
    if takvim_mod == "YUKSEK_RISK":
        return {"karar": "BEKLE", "guven": 0, "gerekce": "Yüksek etkili ekonomik veri"}

    min_guven = 8 if takvim_mod == "DIKKATLI" else MIN_GUVEN
    sinyal    = teknik_s["sinyal"]
    guven     = teknik_s["guven"]

    if sinyal == "BEKLE":
        return {"karar": "BEKLE", "guven": 0, "gerekce": "Teknik sinyal yok"}

    makro_yon  = _yon(makro_skor, "makro")
    haber_yon  = _yon(haber.get("sentiment", "NOTR"), "sentiment")
    teknik_yon = _yon(sinyal, "teknik")

    if makro_yon == haber_yon and makro_yon != "NOTR":
        if teknik_yon == makro_yon:
            guven = min(10, guven + 2)
        elif teknik_yon != "NOTR":
            return {"karar": "BEKLE", "guven": 0, "gerekce": "Makro/haber & teknik çelişiyor"}

    if guven < min_guven:
        return {"karar": "BEKLE", "guven": guven, "gerekce": f"Güven düşük ({guven}<{min_guven})"}

    return {
        "karar":   sinyal,
        "guven":   guven,
        "gerekce": f"M:{makro_yon} H:{haber_yon} T:{teknik_yon}",
    }


# ══════════════════════════════════════════════════════════════════════
# 6. GRAFİK — 3 panelli matplotlib
# ══════════════════════════════════════════════════════════════════════
def grafik_olustur(df: pd.DataFrame, sermaye_serisi: list, islemler: list,
                   haber_dict: dict, gunler: list):
    """3 panelli koyu tema grafik: sermaye eğrisi / haber skoru / işlem noktaları."""
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 11))
    fig.patch.set_facecolor("#1a1a2e")

    for ax in (ax1, ax2, ax3):
        ax.set_facecolor("#16213e")
        ax.tick_params(colors="#cccccc", labelsize=8)
        for sp in ax.spines.values():
            sp.set_color("#444")

    # ── Panel 1: Sermaye eğrisi ────────────────────────────────────
    if len(sermaye_serisi) > 1:
        zs = [s[0] for s in sermaye_serisi]
        ss = [s[1] for s in sermaye_serisi]
        ax1.plot(zs, ss, color="#00d4ff", linewidth=1.5)
        ax1.fill_between(zs, BASLANGIC_KAP, ss,
                         where=[v >= BASLANGIC_KAP for v in ss],
                         color="#00d4ff", alpha=0.15)
        ax1.fill_between(zs, BASLANGIC_KAP, ss,
                         where=[v < BASLANGIC_KAP for v in ss],
                         color="#ff4444", alpha=0.15)
        ax1.axhline(BASLANGIC_KAP, color="#888", linestyle="--", linewidth=0.8)

        for t in islemler:
            renk = "#00ff88" if t["sonuc"] == "KAR" else ("#ff4444" if t["sonuc"] == "ZARAR" else "#ffaa00")
            ax1.scatter(t["cikis_zaman"], t["sermaye"], color=renk, s=35, zorder=5)

    final = sermaye_serisi[-1][1] if sermaye_serisi else BASLANGIC_KAP
    kzl   = final - BASLANGIC_KAP
    ax1.set_title(f"Sermaye  |  Final: ${final:.2f}  ({kzl:+.2f}$  %{kzl/BASLANGIC_KAP*100:+.1f})",
                  color="#fff", fontsize=10, pad=5)
    ax1.set_ylabel("Sermaye ($)", color="#ccc", fontsize=8)

    # ── Panel 2: Günlük haber skoru ───────────────────────────────
    gun_dt    = [datetime.strptime(g, "%Y-%m-%d") for g in gunler]
    gun_skor  = [haber_dict.get(g, {}).get("haber_skoru", 0.0) for g in gunler]
    renkler   = ["#00ff88" if s > 0 else "#ff4444" for s in gun_skor]
    ax2.bar(gun_dt, gun_skor, color=renkler, alpha=0.75, width=0.8)
    ax2.axhline(0, color="#888", linewidth=0.8)
    ax2.set_title("Günlük Haber Skoru", color="#fff", fontsize=10, pad=5)
    ax2.set_ylabel("Skor", color="#ccc", fontsize=8)

    # ── Panel 3: İşlem giriş / çıkış ─────────────────────────────
    test_df = df.iloc[WARMUP:].copy()
    ax3.plot(test_df["zaman"], test_df["kapanis"], color="#888", linewidth=0.6, alpha=0.7)

    for t in islemler:
        mg = "^" if t["yon"] == "AL" else "v"
        rg = "#00ff88" if t["yon"] == "AL" else "#ff4444"
        rc = "#00ff88" if t["sonuc"] == "KAR" else ("#ff4444" if t["sonuc"] == "ZARAR" else "#ffaa00")
        ax3.scatter(t["giris_zaman"],  t["giris"],  color=rg, marker=mg, s=55, zorder=5)
        ax3.scatter(t["cikis_zaman"],  t["cikis"],  color=rc, marker="x", s=55, zorder=5)
        ax3.plot([t["giris_zaman"], t["cikis_zaman"]], [t["giris"], t["cikis"]],
                 color="#666", linewidth=0.5, alpha=0.5)

    ax3.set_title("Fiyat + İşlem Noktaları  (▲AL  ▼SAT  × Çıkış)", color="#fff", fontsize=10, pad=5)
    ax3.set_ylabel("Fiyat ($)", color="#ccc", fontsize=8)

    for ax in (ax1, ax2, ax3):
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=40, ha="right")

    plt.suptitle(
        f"30 Günlük Backtest  |  {BASLANGIC_KAP}$ → {final:.2f}$  |  {LEVERAGE}x Kaldıraç",
        color="#fff", fontsize=12, y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(GRAFIK_DOSYA, dpi=120, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close()


# ══════════════════════════════════════════════════════════════════════
# 7. ANA BACKTEST
# ══════════════════════════════════════════════════════════════════════
def calistir():
    print("\n" + "═" * 65)
    print("  HABER + MAKRO + TAKVİM 30 GÜNLÜK BACKTEST")
    print(f"  {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("═" * 65)

    # ── 1. Binance verisi ──────────────────────────────────────────
    print("\n[1/5] Binance'den 15dk veri çekiliyor...")
    df = veri_cek()
    print(f"  Toplam mum  : {len(df)}")
    print(f"  Aralık      : {df['zaman'].iloc[0].strftime('%d.%m.%Y')} → {df['zaman'].iloc[-1].strftime('%d.%m.%Y')}")

    test_df  = df.iloc[WARMUP:].copy().reset_index(drop=True)
    gunler   = sorted(test_df["zaman"].dt.strftime("%Y-%m-%d").unique().tolist())
    print(f"  Test mumları: {len(test_df)} | Test günleri: {len(gunler)}")

    # ── 2. Haberler ────────────────────────────────────────────────
    print("\n[2/5] Haber verileri hazırlanıyor...")
    haber_dict = haberler_hazirla(gunler)

    # ── 3. Makro ───────────────────────────────────────────────────
    print("\n[3/5] Makro verileri hazırlanıyor...")
    makro_dict = makro_veri_hazirla(df["zaman"].iloc[0].to_pydatetime(),
                                    df["zaman"].iloc[-1].to_pydatetime())

    # ── 4. Backtest döngüsü ────────────────────────────────────────
    print("\n[4/5] Backtest çalışıyor...")

    sermaye        = BASLANGIC_KAP
    pozisyon       = None   # dict veya None
    islemler       = []
    sermaye_serisi = [(df["zaman"].iloc[WARMUP], sermaye)]

    for rel_idx, abs_idx in enumerate(range(WARMUP, len(df))):
        zaman     = df["zaman"].iloc[abs_idx]
        tarih_str = zaman.strftime("%Y-%m-%d")

        # Açık pozisyonu takip et
        if pozisyon is not None:
            h   = float(df["yuksek"].iloc[abs_idx])
            l   = float(df["dusuk"].iloc[abs_idx])
            yon = pozisyon["yon"]
            g   = pozisyon["giris"]
            sl  = g * (1 - SL_PCT) if yon == "AL" else g * (1 + SL_PCT)
            tp  = g * (1 + TP_PCT) if yon == "AL" else g * (1 - TP_PCT)

            kapandi = None
            if yon == "AL":
                if l <= sl:   kapandi = ("ZARAR", sl)
                elif h >= tp: kapandi = ("KAR",   tp)
            else:
                if h >= sl:   kapandi = ("ZARAR", sl)
                elif l <= tp: kapandi = ("KAR",   tp)

            if kapandi:
                sonuc_tipi, cikis_fiyat = kapandi
                pct = (cikis_fiyat - g) / g * 100 * LEVERAGE
                if yon == "SAT":
                    pct = -pct
                kzl     = round(sermaye * pct / 100, 2)
                sermaye = round(sermaye + kzl, 2)

                islemler.append({
                    "giris_zaman": pozisyon["zaman"],
                    "cikis_zaman": zaman,
                    "yon":         yon,
                    "guven":       pozisyon["guven"],
                    "giris":       g,
                    "cikis":       cikis_fiyat,
                    "sonuc":       sonuc_tipi,
                    "kzl":         kzl,
                    "sermaye":     sermaye,
                    "tarih":       tarih_str,
                })
                sermaye_serisi.append((zaman, sermaye))
                pozisyon = None

        # Yeni pozisyon aç
        if pozisyon is None:
            if tarih_str in YUKSEK_RISK:
                takvim_mod = "YUKSEK_RISK"
            elif tarih_str in DIKKATLI:
                takvim_mod = "DIKKATLI"
            else:
                takvim_mod = "NORMAL"

            haber    = haber_dict.get(tarih_str, {"sentiment": "NOTR", "haber_skoru": 0.0})
            makro_s  = makro_dict.get(tarih_str, {}).get("skor", 0.0)
            teknik_s = teknik_sinyal(df, abs_idx)
            karar    = karar_ver(teknik_s, haber, makro_s, takvim_mod)

            if karar["karar"] in ("AL", "SAT"):
                pozisyon = {
                    "yon":   karar["karar"],
                    "giris": float(df["kapanis"].iloc[abs_idx]),
                    "zaman": zaman,
                    "guven": karar["guven"],
                    "tarih": tarih_str,
                }

    # Hâlâ açık pozisyon varsa son kapanış fiyatından kapat
    if pozisyon is not None:
        cikis = float(df["kapanis"].iloc[-1])
        pct   = (cikis - pozisyon["giris"]) / pozisyon["giris"] * 100 * LEVERAGE
        if pozisyon["yon"] == "SAT":
            pct = -pct
        kzl     = round(sermaye * pct / 100, 2)
        sermaye = round(sermaye + kzl, 2)
        islemler.append({
            "giris_zaman": pozisyon["zaman"],
            "cikis_zaman": df["zaman"].iloc[-1],
            "yon":         pozisyon["yon"],
            "guven":       pozisyon["guven"],
            "giris":       pozisyon["giris"],
            "cikis":       cikis,
            "sonuc":       "ACIK",
            "kzl":         kzl,
            "sermaye":     sermaye,
            "tarih":       pozisyon["tarih"],
        })
        sermaye_serisi.append((df["zaman"].iloc[-1], sermaye))

    # ── 5. Rapor ──────────────────────────────────────────────────
    print("\n[5/5] Rapor hazırlanıyor...")
    kar   = sum(1 for t in islemler if t["sonuc"] == "KAR")
    zarar = sum(1 for t in islemler if t["sonuc"] == "ZARAR")
    acik  = sum(1 for t in islemler if t["sonuc"] == "ACIK")
    toplam_kzl = round(sermaye - BASLANGIC_KAP, 2)

    print("\n" + "═" * 65)
    print("  ÖZET RAPOR")
    print("═" * 65)
    print(f"\n  Başlangıç sermayesi : ${BASLANGIC_KAP:.2f}")
    print(f"  Final sermayesi     : ${sermaye:.2f}")
    print(f"  Toplam K/Z          : ${toplam_kzl:+.2f}  (%{toplam_kzl/BASLANGIC_KAP*100:+.1f})")
    print(f"\n  Toplam işlem : {len(islemler)}")
    print(f"  Kar          : {kar}")
    print(f"  Zarar        : {zarar}")
    print(f"  Açık         : {acik}")
    if kar + zarar > 0:
        print(f"  Başarı oranı : %{kar/(kar+zarar)*100:.1f}")

    # Haber doğruluk analizi
    dogru = yanlis = 0
    for g in gunler[:-1]:
        sent = haber_dict.get(g, {}).get("sentiment", "NOTR")
        if sent == "NOTR":
            continue
        ertesi  = (datetime.strptime(g, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        gun_df  = test_df[test_df["zaman"].dt.strftime("%Y-%m-%d") == g]
        ert_df  = test_df[test_df["zaman"].dt.strftime("%Y-%m-%d") == ertesi]
        if gun_df.empty or ert_df.empty:
            continue
        gercek = "BULLISH" if float(ert_df["kapanis"].iloc[-1]) > float(gun_df["kapanis"].iloc[-1]) else "BEARISH"
        if sent == gercek:
            dogru += 1
        else:
            yanlis += 1

    if dogru + yanlis > 0:
        print(f"\n  Haber Sentiment Doğruluğu:")
        print(f"    Doğru  : {dogru}")
        print(f"    Yanlış : {yanlis}")
        print(f"    Oran   : %{dogru/(dogru+yanlis)*100:.1f}")

    # Son işlemler
    if islemler:
        print(f"\n  Son İşlemler:")
        print(f"  {'Tarih':<13} {'Yön':<5} {'Giriş':>8} {'Çıkış':>8} {'K/Z':>8}  Sonuç")
        print("  " + "─" * 55)
        for t in islemler[-15:]:
            zt = t["giris_zaman"].strftime("%d.%m %H:%M")
            print(f"  {zt:<13} {t['yon']:<5} {t['giris']:>8.2f} {t['cikis']:>8.2f} {t['kzl']:>+8.2f}  {t['sonuc']}")

    # Grafik
    grafik_olustur(df, sermaye_serisi, islemler, haber_dict, gunler)
    print(f"\n  Grafik kaydedildi: {GRAFIK_DOSYA}")
    print("\n" + "═" * 65)


if __name__ == "__main__":
    calistir()
