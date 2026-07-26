#!/usr/bin/env python3
"""
backtest/histdata_backtest.py
──────────────────────────────
17 Yıllık XAUUSD Histdata Backtesti (2009–2025)

• M1 veri → 15dk mumlarına yeniden örneklenir
• RSI/MACD/BB kural tabanlı strateji (motor.py uzun mod)
• Kaldıraç: 3x | SL: %1 | TP: %2 | Trailing stop: AÇIK
• Her yıl için ayrı performans raporu
• 2009 (2008 krizi ardı) ve 2020 (COVID) dönem analizi

Çalıştırma:
    source ~/gold-bot/bin/activate
    python3 -m backtest.histdata_backtest
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime

from backtest.veri_yukle import yukle_aralik
from backtest.motor import gostergeler_ekle, calistir_df, timezone_temizle

SONUC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sonuclar")

# ── Backtest parametreleri ─────────────────────────────────────────
SERMAYE       = 1_000.0   # Başlangıç sermayesi ($)
KALDIRAC      = 3          # Kaldıraç
SL_PCT        = 1.0        # Stop-loss (%)
TP_PCT        = 2.0        # Take-profit (%)
MAX_GUN_ZARAR = 75.0       # Günlük max zarar ($)
MOD           = "uzun"     # motor.py strateji modu
BASLANGIC_YIL = 2009
BITIS_YIL     = 2025

# Özel dönemler (grafik vurgulaması için)
OZEL_DONEMLER = [
    (2009, "2008 Krizi Ardı", "#FF9800"),
    (2020, "COVID",           "#F44336"),
]


# ── Yıllık istatistik çıkarıcı ────────────────────────────────────

def yillik_istatistikler(islem_df: pd.DataFrame,
                          portfoy_df: pd.DataFrame) -> dict:
    """İşlem ve portföy DataFramelerinden yıllık istatistikleri çıkar."""
    if portfoy_df.empty:
        return {}

    pf = portfoy_df.copy()
    pf["tarih"] = pd.to_datetime(pf["tarih"])
    pf["yil"]   = pf["tarih"].dt.year

    yillar   = sorted(pf["yil"].unique())
    sonuclar = {}

    for yil in yillar:
        yil_pf = pf[pf["yil"] == yil]
        if yil_pf.empty:
            continue

        bas_pf = yil_pf.iloc[0]["portfoy"]
        bit_pf = yil_pf.iloc[-1]["portfoy"]

        # Yıl içi drawdown
        yp = yil_pf.copy()
        yp["zirve"] = yp["portfoy"].cummax()
        yp["dd"]    = (yp["portfoy"] - yp["zirve"]) / yp["zirve"] * 100
        max_dd      = yp["dd"].min()

        # Yıl içi işlemler
        if not islem_df.empty and "yil" in islem_df.columns:
            yil_ist = islem_df[islem_df["yil"] == yil]
        elif not islem_df.empty:
            yil_ist = islem_df[pd.to_datetime(islem_df["tarih"]).dt.year == yil]
        else:
            yil_ist = pd.DataFrame()

        islem_say = len(yil_ist)
        if islem_say > 0:
            karli     = yil_ist[yil_ist["kar_zarar"] > 0]
            basari    = len(karli) / islem_say * 100
            toplam_kz = yil_ist["kar_zarar"].sum()
            ort_kar   = yil_ist[yil_ist["kar_zarar"] > 0]["kar_zarar"].mean() if len(karli) > 0 else 0
            ort_zarar = yil_ist[yil_ist["kar_zarar"] < 0]["kar_zarar"].mean() if (islem_say - len(karli)) > 0 else 0
        else:
            basari    = 0.0
            toplam_kz = 0.0
            ort_kar   = 0.0
            ort_zarar = 0.0

        getiri_pct = (bit_pf - bas_pf) / bas_pf * 100

        sonuclar[yil] = {
            "baslangic":   bas_pf,
            "bitis":       bit_pf,
            "kar_zarar":   bit_pf - bas_pf,
            "getiri_pct":  getiri_pct,
            "islem_say":   islem_say,
            "basari_pct":  basari,
            "max_dd":      max_dd,
            "ort_kar":     ort_kar,
            "ort_zarar":   ort_zarar,
            "mum_sayisi":  len(yil_pf),
        }

    return sonuclar


# ── Rapor ─────────────────────────────────────────────────────────

def rapor_yazdir(yil_stats: dict, genel_stats: dict) -> None:
    """Konsola kapsamlı performans raporu yaz."""
    sep = "=" * 80

    print(f"\n{sep}")
    print("  17 YIL XAUUSD BACKTEST RAPORU — 2009–2025")
    print("  Strateji : RSI/MACD/BB kural tabanlı | Mod: UZUN")
    print(f"  Kaldıraç : Dinamik ADX (1x/2x/3x) | SL: %{SL_PCT} | TP: %{TP_PCT} | Trailing: AÇIK")
    print("  Filtre   : Yatay piyasa filtresi AÇIK (50 mum aralığı <%1 → işlem yok)")
    print(f"  Başlangıç: ${SERMAYE:,.0f}")
    print(sep)

    # Tablo başlığı
    print(f"\n{'YIL':<5}  {'BAŞL':>9}  {'BİTİŞ':>9}  {'K/Z':>9}  "
          f"{'GETİRİ':>8}  {'İŞLEM':>5}  {'BAŞARI':>7}  {'MAX DD':>7}  NOT")
    print("-" * 80)

    for yil in sorted(yil_stats.keys()):
        s = yil_stats[yil]

        getiri_str = f"%{s['getiri_pct']:+.1f}"
        kz_str     = f"${s['kar_zarar']:+.2f}"
        dd_str     = f"%{s['max_dd']:.1f}"

        not_str = ""
        for yd, etiket, _ in OZEL_DONEMLER:
            if yil == yd:
                not_str = f"← {etiket}"

        print(f"{yil:<5}  ${s['baslangic']:>8.2f}  ${s['bitis']:>8.2f}  "
              f"{kz_str:>9}  {getiri_str:>8}  {s['islem_say']:>5}  "
              f"%{s['basari_pct']:>5.1f}  {dd_str:>7}  {not_str}")

    print("-" * 80)

    # Genel özet
    ilk  = min(yil_stats.keys())
    son  = max(yil_stats.keys())
    bas  = yil_stats[ilk]["baslangic"]
    bit  = yil_stats[son]["bitis"]
    r    = (bit - bas) / bas * 100
    yil_sayisi = son - ilk + 1
    cagr = ((bit / bas) ** (1 / yil_sayisi) - 1) * 100 if bas > 0 else 0
    tis  = sum(s["islem_say"] for s in yil_stats.values())

    print(f"\n  TOPLAM İŞLEM   : {tis:,}")
    print(f"  BAŞLANGIÇ      : ${bas:,.2f}")
    print(f"  FİNAL          : ${bit:,.2f}")
    print(f"  TOPLAM GETİRİ  : ${bit - bas:,.2f}  (%{r:+.1f})")
    print(f"  CAGR           : %{cagr:.1f}/yıl")

    # En iyi / en kötü
    en_iyi  = max(yil_stats.items(), key=lambda x: x[1]["getiri_pct"])
    en_kotu = min(yil_stats.items(), key=lambda x: x[1]["getiri_pct"])
    en_dd   = min(yil_stats.items(), key=lambda x: x[1]["max_dd"])
    pozitif = [y for y, s in yil_stats.items() if s["getiri_pct"] >= 0]
    negatif = [y for y, s in yil_stats.items() if s["getiri_pct"] < 0]

    print(f"\n  EN İYİ YIL     : {en_iyi[0]} — "
          f"%{en_iyi[1]['getiri_pct']:+.1f} (${en_iyi[1]['kar_zarar']:+.2f})")
    print(f"  EN KÖTÜ YIL    : {en_kotu[0]} — "
          f"%{en_kotu[1]['getiri_pct']:+.1f} (${en_kotu[1]['kar_zarar']:+.2f})")
    print(f"  MAX DRAWDOWN   : {en_dd[0]} — %{en_dd[1]['max_dd']:.1f}")
    print(f"  KÂRLı YIL SAYISI: {len(pozitif)}/{yil_sayisi}  "
          f"({', '.join(str(y) for y in pozitif)})")
    print(f"  ZARARLIYIL SAY : {len(negatif)}/{yil_sayisi}"
          + (f"  ({', '.join(str(y) for y in negatif)})" if negatif else "  (yok)"))

    # Özel dönem analizleri
    _donem_analizi(yil_stats, 2009,
                   "2009 — 2008 Küresel Finans Krizi Ardı",
                   "Altın $800→$1200 yükseldi. Fed sıfır faiz politikası.")
    _donem_analizi(yil_stats, 2020,
                   "2020 — COVID-19 Salgını",
                   "Altın $1550→$2067 (tarihsel rekor). Mart çöküşü + güçlü toparlanma.")

    print(sep)


def _donem_analizi(yil_stats: dict, yil: int, baslik: str, not_str: str) -> None:
    """Tek bir özel dönem analizi yazar."""
    if yil not in yil_stats:
        return
    s = yil_stats[yil]
    print(f"\n  {baslik}")
    print(f"    Getiri  : %{s['getiri_pct']:+.1f}  (${s['kar_zarar']:+.2f})")
    print(f"    İşlem   : {s['islem_say']}  |  Başarı: %{s['basari_pct']:.1f}")
    print(f"    Max DD  : %{s['max_dd']:.1f}")
    print(f"    Not     : {not_str}")


# ── Grafik ────────────────────────────────────────────────────────

def grafik_olustur(yil_stats: dict, portfoy_df: pd.DataFrame,
                   islem_df: pd.DataFrame) -> str:
    """3 panelli özet grafik oluştur ve kaydet. Grafik yolunu döner."""
    os.makedirs(SONUC_DIR, exist_ok=True)

    # Portföy eğrisini günlük örnekle (çizim hızı için)
    pf = portfoy_df.copy()
    pf["tarih"] = pd.to_datetime(pf["tarih"])
    pf = pf.set_index("tarih").resample("1D")["portfoy"].last().dropna().reset_index()

    yillar    = sorted(yil_stats.keys())
    getiriler = [yil_stats[y]["getiri_pct"] for y in yillar]
    max_dds   = [yil_stats[y]["max_dd"]     for y in yillar]

    # 17 yıllık final portföyü ve CAGR
    ilk = yillar[0]; son = yillar[-1]
    bas = yil_stats[ilk]["baslangic"]; bit = yil_stats[son]["bitis"]
    yil_say = son - ilk + 1
    cagr = ((bit / bas) ** (1 / yil_say) - 1) * 100 if bas > 0 else 0
    toplam_r = (bit - bas) / bas * 100

    fig = plt.figure(figsize=(20, 14))
    fig.suptitle(
        f"17 Yıl XAUUSD Backtesti (2009–2025)  |  "
        f"RSI/MACD/BB | Dinamik ADX (1-3x) + Yatay Filtre | SL%{SL_PCT} TP%{TP_PCT}\n"
        f"${bas:,.0f} → ${bit:,.2f}  |  "
        f"Toplam: %{toplam_r:+.1f}  |  CAGR: %{cagr:.1f}/yıl",
        fontsize=13, fontweight="bold", y=0.99
    )
    gs = gridspec.GridSpec(3, 1, figure=fig, hspace=0.45,
                           height_ratios=[2.5, 1, 1])

    # ── Panel 1: Kümülatif portföy eğrisi ──────────────────────
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(pf["tarih"], pf["portfoy"], color="#1565C0",
             linewidth=1.2, label="Portföy ($)", zorder=3)
    ax1.axhline(y=SERMAYE, color="gray", linestyle="--",
                linewidth=0.8, alpha=0.7, label=f"Başlangıç ${SERMAYE:,.0f}")
    ax1.fill_between(pf["tarih"], pf["portfoy"], SERMAYE,
                     where=(pf["portfoy"] >= SERMAYE),
                     alpha=0.15, color="green", zorder=2)
    ax1.fill_between(pf["tarih"], pf["portfoy"], SERMAYE,
                     where=(pf["portfoy"] < SERMAYE),
                     alpha=0.15, color="red", zorder=2)

    # Yıl sınırları
    for y in yillar[1:]:
        ax1.axvline(x=pd.Timestamp(f"{y}-01-01"), color="gray",
                    linewidth=0.4, alpha=0.5, zorder=1)

    # Özel dönem vurgulaması
    for yd, etiket, renk in OZEL_DONEMLER:
        if yd in yillar:
            ax1.axvspan(pd.Timestamp(f"{yd}-01-01"),
                        pd.Timestamp(f"{yd + 1}-01-01"),
                        alpha=0.12, color=renk, label=etiket, zorder=1)

    # Yıl etiketleri
    for y in yillar[::2]:
        ax1.text(pd.Timestamp(f"{y}-07-01"),
                 ax1.get_ylim()[0] * 1.005 if ax1.get_ylim()[0] > 0 else SERMAYE * 0.98,
                 str(y), fontsize=7, color="gray", ha="center")

    ax1.set_ylabel("Portföy ($)", fontsize=10)
    ax1.legend(fontsize=8, loc="upper left", ncol=2)
    ax1.grid(True, alpha=0.3)
    ax1.set_title("Kümülatif Portföy Değeri (Bileşik)", fontsize=10, pad=4)

    # ── Panel 2: Yıllık getiri çubukları ───────────────────────
    ax2 = fig.add_subplot(gs[1])
    renkler = ["#43A047" if g >= 0 else "#E53935" for g in getiriler]
    bars = ax2.bar(yillar, getiriler, color=renkler, alpha=0.85,
                   edgecolor="white", linewidth=0.5)
    ax2.axhline(y=0, color="black", linewidth=0.8)

    for bar, g in zip(bars, getiriler):
        offset = 0.4 if g >= 0 else -1.2
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 g + offset, f"{g:+.1f}%",
                 ha="center", va="bottom", fontsize=7)

    ax2.set_ylabel("Yıllık Getiri (%)", fontsize=10)
    ax2.set_xticks(yillar)
    ax2.set_xticklabels([str(y) for y in yillar], rotation=45, fontsize=8)
    ax2.grid(True, alpha=0.3, axis="y")
    ax2.set_title("Yıllık Getiri (%)", fontsize=10, pad=4)

    # Özel dönemler için ok
    for yd, etiket, renk in OZEL_DONEMLER:
        if yd in yillar:
            ax2.axvline(x=yd, color=renk, linewidth=1.5,
                        alpha=0.7, linestyle=":")

    # ── Panel 3: Max drawdown çubukları ────────────────────────
    ax3 = fig.add_subplot(gs[2])
    ax3.bar(yillar, max_dds, color="#EF6C00", alpha=0.8,
            edgecolor="white", linewidth=0.5)
    ax3.axhline(y=-15, color="red", linestyle="--", linewidth=0.8,
                alpha=0.7, label="Hedef limit -%15")
    ax3.set_ylabel("Max Drawdown (%)", fontsize=10)
    ax3.set_xticks(yillar)
    ax3.set_xticklabels([str(y) for y in yillar], rotation=45, fontsize=8)
    ax3.grid(True, alpha=0.3, axis="y")
    ax3.set_title("Yıllık Max Drawdown (%)", fontsize=10, pad=4)
    ax3.legend(fontsize=8)

    grafik_yol = os.path.join(
        SONUC_DIR,
        f"histdata_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    )
    plt.savefig(grafik_yol, dpi=150, bbox_inches="tight")
    plt.close()
    return grafik_yol


# ── Ana çalıştırıcı ───────────────────────────────────────────────

def main():
    baslangic_t = datetime.now()
    print("\n" + "=" * 65)
    print("  17 YIL XAUUSD HISTDATA BACKTESTI")
    print(f"  Mod: {MOD.upper()} | Kaldıraç: Dinamik ADX (1-3x) | "
          f"SL: %{SL_PCT} | TP: %{TP_PCT}")
    print(f"  Sermaye: ${SERMAYE:,.0f} | Yıllar: {BASLANGIC_YIL}–{BITIS_YIL}")
    print("=" * 65)

    # 1. Veri yükle (1dk → 15dk örnekleme)
    print(f"\n[1/4] Histdata yükleniyor ({BASLANGIC_YIL}–{BITIS_YIL}, 15dk)...")
    df_15m = yukle_aralik(BASLANGIC_YIL, BITIS_YIL, zaman_aralik="15min")
    print(f"  Toplam: {len(df_15m):,} mum  |  "
          f"{df_15m.index[0].date()} → {df_15m.index[-1].date()}")
    print(f"  Fiyat aralığı: ${df_15m['close'].min():.0f}–${df_15m['close'].max():.0f}")

    # 2. Günlük trend filtresi
    print("\n[2/4] Günlük trend filtresi hazırlanıyor...")
    df_gunluk = (
        df_15m.resample("1D")
        .agg({"open": "first", "high": "max",
              "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
    )
    df_gunluk = timezone_temizle(df_gunluk)
    df_gunluk = gostergeler_ekle(df_gunluk)
    print(f"  Günlük mum: {len(df_gunluk):,}  |  "
          f"MA200 ısınma: ilk {min(200, len(df_gunluk))} gün")

    # 3. Backtest
    print(f"\n[3/4] Backtest çalışıyor ({len(df_15m):,} mum)...")
    print("    Bu işlem birkaç dakika sürebilir...")
    t0 = datetime.now()
    genel_stats, islem_df, portfoy_df = calistir_df(
        df_15m, df_gunluk,
        mod=MOD,
        sermaye=SERMAYE,
        kaldirac=KALDIRAC,
        stop_loss_pct=SL_PCT,
        take_profit_pct=TP_PCT,
        max_gunluk_zarar=MAX_GUN_ZARAR,
        trailing_stop=True,
        ilerleme=True,
    )
    sure = (datetime.now() - t0).total_seconds()
    print(f"  Tamamlandı ({sure:.1f}s) | Toplam işlem: {genel_stats['islem_sayisi']:,}")

    # 4. Yıllık istatistikler
    print("\n[4/4] Yıllık istatistikler hesaplanıyor...")
    yil_stats = yillik_istatistikler(islem_df, portfoy_df)

    # Rapor
    rapor_yazdir(yil_stats, genel_stats)

    # Grafik
    if yil_stats:
        print("\nGrafik oluşturuluyor...")
        grafik_yol = grafik_olustur(yil_stats, portfoy_df, islem_df)
        print(f"  Grafik: {grafik_yol}")

    # İşlem listesi CSV
    if not islem_df.empty:
        os.makedirs(SONUC_DIR, exist_ok=True)
        csv_yol = os.path.join(SONUC_DIR, "histdata_islemler.csv")
        islem_df.to_csv(csv_yol, index=False, float_format="%.4f")
        print(f"  İşlem CSV: {csv_yol}")

    toplam_sure = (datetime.now() - baslangic_t).total_seconds()
    print(f"\n  Toplam süre: {toplam_sure:.1f}s")


if __name__ == "__main__":
    main()
