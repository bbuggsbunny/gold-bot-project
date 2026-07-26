# backtest/strateji_breakout.py
# ─────────────────────────────────────────────
# Breakout (Kırılım) Stratejisi:
# Son N mumun en yüksek/düşük noktası kırılınca
# hacim teyidiyle giriş yapar.
# Sabit SL yerine ATR tabanlı dinamik SL kullanır.
# ─────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

VERI_KLASOR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veri")
SONUC_KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sonuclar")


def gostergeler_ekle(df):
    df = df.copy()
    # ATR — piyasanın ortalama dalgalanma aralığı
    df['atr']       = (df['high'] - df['low']).rolling(14).mean()
    df['hacim_ort'] = df['volume'].rolling(20).mean()
    df['ma50']      = df['close'].rolling(50).mean()
    df['ma200']     = df['close'].rolling(200).mean()

    # Kırılım seviyeleri — son 20 mumun en yüksek/düşüğü
    df['direnc']    = df['high'].rolling(20).max().shift(1)
    df['destek']    = df['low'].rolling(20).min().shift(1)
    return df.dropna()


def timezone_temizle(df):
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def trend_belirle(df_gunluk, tarih):
    try:
        tarih_naive = tarih.replace(tzinfo=None) if hasattr(tarih, 'tzinfo') else tarih
        gecmis = df_gunluk[df_gunluk.index <= tarih_naive]
        if len(gecmis) < 5:
            return "NOTR"
        son = gecmis.iloc[-1]
        if son['ma50'] > son['ma200']:
            return "YUKARI"
        elif son['ma50'] < son['ma200']:
            return "ASAGI"
        return "NOTR"
    except:
        return "NOTR"


def sinyal_uret(satir, trend):
    """
    Breakout sinyali:
    - Fiyat direnç seviyesini kırdı + hacim ortalamanın üstünde → AL
    - Fiyat destek seviyesini kırdı + hacim ortalamanın üstünde → SAT
    - Trend filtresine aykırı sinyaller iptal edilir
    """
    fiyat   = satir['close']
    yuksek  = satir['high']
    dusuk   = satir['low']
    direnc  = satir['direnc']
    destek  = satir['destek']
    hacim   = satir['volume']
    h_ort   = satir['hacim_ort']

    # Hacim teyidi — ortalamanın en az 1.2 katı olmalı
    hacim_teyit = hacim > h_ort * 1.2

    if not hacim_teyit:
        return "BEKLE"

    # Yukarı kırılım
    if yuksek > direnc:
        if trend != "ASAGI":  # düşüş trendinde AL yapma
            return "AL"

    # Aşağı kırılım
    if dusuk < destek:
        if trend != "YUKARI":  # yükseliş trendinde SAT yapma
            return "SAT"

    return "BEKLE"


def calistir(dosya, sermaye=1000, kaldirac=10,
             atr_carpan_sl=1.5, atr_carpan_tp=3.0,
             max_gunluk_zarar=75):
    """
    atr_carpan_sl: Stop-loss = ATR × bu değer
    atr_carpan_tp: Take-profit = ATR × bu değer
    Örn: ATR=5$, carpan_sl=1.5 → SL 7.5$ uzakta
    """
    dosya_yol = os.path.join(VERI_KLASOR, dosya)
    if not os.path.exists(dosya_yol):
        print(f"HATA: {dosya_yol} bulunamadı.")
        return None

    df = pd.read_csv(dosya_yol, index_col="tarih", parse_dates=True)
    df = timezone_temizle(df)
    df = gostergeler_ekle(df)

    # Günlük trend filtresi
    gunluk_dosya = os.path.join(VERI_KLASOR, "altin_1d_2004.csv")
    df_gunluk    = None
    if os.path.exists(gunluk_dosya):
        df_gunluk = pd.read_csv(gunluk_dosya, index_col="tarih", parse_dates=True)
        df_gunluk = timezone_temizle(df_gunluk)
        df_gunluk['ma50']  = df_gunluk['close'].rolling(50).mean()
        df_gunluk['ma200'] = df_gunluk['close'].rolling(200).mean()
        df_gunluk = df_gunluk.dropna()

    print(f"\n{'='*55}")
    print(f"  BREAKOUT BACKTEST: {dosya}")
    print(f"  Sermaye: ${sermaye} | Kaldıraç: {kaldirac}x")
    print(f"  ATR SL çarpanı: {atr_carpan_sl}x | TP çarpanı: {atr_carpan_tp}x")
    print(f"  Max günlük zarar: ${max_gunluk_zarar}")
    print(f"  Mum sayısı: {len(df)}")
    print(f"{'='*55}\n")

    portfoy        = sermaye
    pozisyon       = None
    giris_fiyat    = 0
    stop_fiyat     = 0
    tp_fiyat       = 0
    en_iyi_fiy     = 0
    islemler       = []
    portfoy_gecmis = []
    gunluk_zarar   = 0
    son_gun        = None

    for tarih, satir in df.iterrows():
        fiyat = satir['close']
        atr   = satir['atr']
        gun   = tarih.date() if hasattr(tarih, 'date') else tarih

        if gun != son_gun:
            gunluk_zarar = 0
            son_gun      = gun

        if gunluk_zarar >= max_gunluk_zarar:
            portfoy_gecmis.append({"tarih": tarih, "portfoy": portfoy})
            continue

        trend = trend_belirle(df_gunluk, tarih) if df_gunluk is not None else "NOTR"

        # Açık pozisyon kontrolü — trailing stop
        if pozisyon is not None:
            if pozisyon == "LONG":
                en_iyi_fiy = max(en_iyi_fiy, fiyat)
                # Trailing: stop fiyat yükseldikçe yukarı çeker
                yeni_stop  = en_iyi_fiy - (atr * atr_carpan_sl)
                stop_fiyat = max(stop_fiyat, yeni_stop)
                degisim    = (fiyat - giris_fiyat) / giris_fiyat * 100
                kapandi    = fiyat <= stop_fiyat or fiyat >= tp_fiyat
                tip        = "TP" if fiyat >= tp_fiyat else "TSL"

            else:  # SHORT
                en_iyi_fiy = min(en_iyi_fiy, fiyat)
                yeni_stop  = en_iyi_fiy + (atr * atr_carpan_sl)
                stop_fiyat = min(stop_fiyat, yeni_stop)
                degisim    = (giris_fiyat - fiyat) / giris_fiyat * 100
                kapandi    = fiyat >= stop_fiyat or fiyat <= tp_fiyat
                tip        = "TP" if fiyat <= tp_fiyat else "TSL"

            if kapandi:
                kar_zarar    = portfoy * (abs(degisim) / 100) * kaldirac * (1 if degisim > 0 else -1)
                portfoy     += kar_zarar
                gunluk_zarar += abs(kar_zarar) if kar_zarar < 0 else 0
                islemler.append({
                    "tarih":     tarih,
                    "tip":       tip,
                    "yon":       pozisyon,
                    "giris":     giris_fiyat,
                    "cikis":     fiyat,
                    "kar_zarar": kar_zarar,
                    "portfoy":   portfoy
                })
                pozisyon = None

        # Yeni sinyal
        if pozisyon is None:
            sinyal = sinyal_uret(satir, trend)

            if sinyal == "AL":
                pozisyon    = "LONG"
                giris_fiyat = fiyat
                en_iyi_fiy  = fiyat
                stop_fiyat  = fiyat - (atr * atr_carpan_sl)
                tp_fiyat    = fiyat + (atr * atr_carpan_tp)

            elif sinyal == "SAT":
                pozisyon    = "SHORT"
                giris_fiyat = fiyat
                en_iyi_fiy  = fiyat
                stop_fiyat  = fiyat + (atr * atr_carpan_sl)
                tp_fiyat    = fiyat - (atr * atr_carpan_tp)

        portfoy_gecmis.append({"tarih": tarih, "portfoy": portfoy})

    # Sonuçlar
    islem_df   = pd.DataFrame(islemler)
    portfoy_df = pd.DataFrame(portfoy_gecmis)

    if islem_df.empty:
        print("Hiç işlem yapılmadı.")
        return None

    karli        = islem_df[islem_df['kar_zarar'] > 0]
    zararli      = islem_df[islem_df['kar_zarar'] < 0]
    basari_orani = len(karli) / len(islem_df) * 100
    toplam_kar   = islem_df['kar_zarar'].sum()

    portfoy_df['zirve']    = portfoy_df['portfoy'].cummax()
    portfoy_df['drawdown'] = (portfoy_df['portfoy'] - portfoy_df['zirve']) / portfoy_df['zirve'] * 100
    max_drawdown           = portfoy_df['drawdown'].min()

    print(f"  SONUÇLAR:")
    print(f"  Başlangıç : ${sermaye:.2f}")
    print(f"  Final     : ${portfoy:.2f}")
    print(f"  Kar/Zarar : ${toplam_kar:.2f} ({toplam_kar/sermaye*100:.1f}%)")
    print(f"  İşlem     : {len(islem_df)} (Karlı: {len(karli)} | Zararlı: {len(zararli)})")
    print(f"  Başarı    : %{basari_orani:.1f}")
    print(f"  Max DD    : %{max_drawdown:.1f}")
    print(f"{'='*55}\n")

    # Grafik
    os.makedirs(SONUC_KLASOR, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
    fig.suptitle(
        f"Breakout Backtest | Başarı: %{basari_orani:.1f} | Kar: ${toplam_kar:.2f}",
        fontsize=12
    )

    ax1.plot(df.index, df['close'],  color='gray',   linewidth=0.8, label='Fiyat')
    ax1.plot(df.index, df['direnc'], color='red',    linewidth=0.8, alpha=0.6, label='Direnç')
    ax1.plot(df.index, df['destek'], color='green',  linewidth=0.8, alpha=0.6, label='Destek')

    al_ist  = islem_df[islem_df['yon'] == 'LONG']
    sat_ist = islem_df[islem_df['yon'] == 'SHORT']
    ax1.scatter(al_ist['tarih'],  al_ist['giris'],  marker='^', color='green', s=50, zorder=5, label='AL')
    ax1.scatter(sat_ist['tarih'], sat_ist['giris'], marker='v', color='red',   s=50, zorder=5, label='SAT')
    ax1.set_ylabel('Fiyat ($)')
    ax1.legend(fontsize=7)
    ax1.grid(True, alpha=0.3)

    ax2.plot(portfoy_df['tarih'], portfoy_df['portfoy'], color='green', linewidth=1)
    ax2.axhline(y=sermaye, color='gray', linestyle='--', linewidth=0.8)
    ax2.fill_between(portfoy_df['tarih'], portfoy_df['portfoy'], sermaye,
                     where=portfoy_df['portfoy'] >= sermaye, alpha=0.3, color='green')
    ax2.fill_between(portfoy_df['tarih'], portfoy_df['portfoy'], sermaye,
                     where=portfoy_df['portfoy'] < sermaye,  alpha=0.3, color='red')
    ax2.set_ylabel('Portföy ($)')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    grafik = os.path.join(
        SONUC_KLASOR,
        f"breakout_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    )
    plt.savefig(grafik, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Grafik: {grafik}")

    return {
        "final_portfoy": portfoy,
        "toplam_kar":    toplam_kar,
        "basari_orani":  basari_orani,
        "islem_sayisi":  len(islem_df),
        "max_drawdown":  max_drawdown,
        "grafik":        grafik
    }


if __name__ == "__main__":
    print("BREAKOUT STRATEJİSİ — 5 DAKİKALIK MUM")
    calistir(
        dosya="altin_5m_2026.csv",
        sermaye=1000,
        kaldirac=10,
        atr_carpan_sl=1.5,
        atr_carpan_tp=3.0,
        max_gunluk_zarar=75
    )
