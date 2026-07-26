# backtest/motor.py
# ─────────────────────────────────────────────
# Güncellenmiş backtest motoru v3:
# Timezone uyuşmazlığı düzeltildi
# Uzun vadeli eşik düşürüldü (6→5)
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


# ── Teknik Göstergeler ───────────────────────

def hesapla_rsi(close, periyot=14):
    delta = close.diff()
    kazan = delta.clip(lower=0).ewm(com=periyot-1, min_periods=periyot).mean()
    kayip = (-delta.clip(upper=0)).ewm(com=periyot-1, min_periods=periyot).mean()
    rs    = kazan / kayip.replace(0, float('inf'))
    return 100 - (100 / (1 + rs))

def hesapla_macd(close):
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    sinyal = macd.ewm(span=9, adjust=False).mean()
    return macd, sinyal

def hesapla_bollinger(close, periyot=20, std=2):
    ort   = close.rolling(periyot).mean()
    sapma = close.rolling(periyot).std()
    return ort + (sapma * std), ort, ort - (sapma * std)

def hesapla_adx(high, low, close, periyot=14):
    """ADX (Average Directional Index) — Wilder smoothing ile."""
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    up_move   = high - prev_high
    down_move = prev_low - low
    dm_pos = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index)
    dm_neg = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index)
    atr14  = tr.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean()
    dmp14  = dm_pos.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean()
    dmn14  = dm_neg.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean()
    di_pos = 100 * dmp14 / atr14.replace(0, np.nan)
    di_neg = 100 * dmn14 / atr14.replace(0, np.nan)
    dx     = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
    return dx.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean().fillna(20.0)

def gostergeler_ekle(df):
    df = df.copy()
    df['rsi']                              = hesapla_rsi(df['close'])
    df['macd'], df['macd_sinyal']          = hesapla_macd(df['close'])
    df['macd_hist']                        = df['macd'] - df['macd_sinyal']
    df['bb_ust'], df['bb_ort'], df['bb_alt'] = hesapla_bollinger(df['close'])
    df['ma20']                             = df['close'].rolling(20).mean()
    df['ma50']                             = df['close'].rolling(50).mean()
    df['ma200']                            = df['close'].rolling(200).mean()
    df['atr']                              = (df['high'] - df['low']).rolling(14).mean()
    df['hacim_ort']                        = df['volume'].rolling(20).mean()
    df['adx']                              = hesapla_adx(df['high'], df['low'], df['close'])
    # Son 50 mumun fiyat aralığı — yatay piyasa tespiti için
    h50 = df['high'].rolling(50).max()
    l50 = df['low'].rolling(50).min()
    df['yatay_aralik'] = (h50 - l50) / l50 * 100
    return df.dropna()

def timezone_temizle(df):
    """Timezone bilgisini kaldır — karşılaştırma hatalarını önler"""
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


# ── Trend Filtresi ───────────────────────────

def trend_belirle(df_gunluk, tarih):
    """
    Günlük veriyle büyük trendi belirle.
    MA50 > MA200 → YUKARI
    MA50 < MA200 → ASAGI
    """
    try:
        # Timezone'suz karşılaştırma
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
    except Exception as e:
        return "NOTR"


# ── Sinyal Üretici ───────────────────────────

def sinyal_uret(satir, trend, mod="kisa"):
    rsi   = satir['rsi']
    macd  = satir['macd']
    msin  = satir['macd_sinyal']
    fiy   = satir['close']
    bb_u  = satir['bb_ust']
    bb_a  = satir['bb_alt']
    ma20  = satir['ma20']
    ma50  = satir['ma50']
    hacim = satir['volume']
    h_ort = satir['hacim_ort']

    # Hacim filtresi
    if h_ort > 0 and hacim < h_ort * 0.8:
        return "BEKLE"

    if mod in ["kisa", "sadece_al"]:
        al_skor  = 0
        sat_skor = 0

        if rsi < 35:        al_skor  += 2
        elif rsi < 45:      al_skor  += 1
        if rsi > 65:        sat_skor += 2
        elif rsi > 55:      sat_skor += 1

        if macd > msin:     al_skor  += 2
        else:               sat_skor += 2

        if fiy < bb_a:      al_skor  += 2
        elif fiy > bb_u:    sat_skor += 2

        if ma20 > ma50:     al_skor  += 1
        else:               sat_skor += 1

        # Trend filtresi
        if trend == "YUKARI" and sat_skor >= 5:
            return "BEKLE"
        if trend == "ASAGI"  and al_skor  >= 5:
            return "BEKLE"

        if mod == "sadece_al" and al_skor >= 4: return "AL"
        if mod != "sadece_al" and al_skor >= 5: return "AL"
        elif mod != "sadece_al" and sat_skor >= 5: return "SAT"
        return "BEKLE"

    else:  # uzun
        al_skor  = 0
        sat_skor = 0

        if ma20 > ma50:     al_skor  += 2
        else:               sat_skor += 2

        if rsi < 40:        al_skor  += 2
        elif rsi > 60:      sat_skor += 2

        if macd > msin:     al_skor  += 2
        else:               sat_skor += 2

        if fiy < bb_a:      al_skor  += 1
        elif fiy > bb_u:    sat_skor += 1

        # Trend filtresi
        if trend == "YUKARI" and sat_skor >= 5:
            return "BEKLE"
        if trend == "ASAGI"  and al_skor  >= 5:
            return "BEKLE"

        if mod == "sadece_al" and al_skor >= 4: return "AL"
        if mod != "sadece_al" and al_skor >= 5: return "AL"
        elif mod != "sadece_al" and sat_skor >= 5: return "SAT"
        return "BEKLE"


# ── Backtest Motoru ──────────────────────────

def calistir(dosya, mod="kisa", sermaye=1000, kaldirac=10,
             stop_loss_pct=0.5, take_profit_pct=1.0,
             max_gunluk_zarar=75, trailing_stop=True):

    dosya_yol = os.path.join(VERI_KLASOR, dosya)
    if not os.path.exists(dosya_yol):
        print(f"HATA: {dosya_yol} bulunamadı.")
        return None

    df = pd.read_csv(dosya_yol, index_col="tarih", parse_dates=True)
    df = timezone_temizle(df)
    df = gostergeler_ekle(df)

    # Günlük veri
    gunluk_dosya = os.path.join(VERI_KLASOR, "altin_1d_2004.csv")
    df_gunluk    = None
    if os.path.exists(gunluk_dosya):
        df_gunluk = pd.read_csv(gunluk_dosya, index_col="tarih", parse_dates=True)
        df_gunluk = timezone_temizle(df_gunluk)
        df_gunluk = gostergeler_ekle(df_gunluk)

    print(f"\n{'='*55}")
    print(f"  BACKTEST: {dosya} | Mod: {mod.upper()}")
    print(f"  Sermaye: ${sermaye} | Kaldıraç: {kaldirac}x")
    print(f"  SL: %{stop_loss_pct} | TP: %{take_profit_pct}")
    print(f"  Trailing Stop: {'AÇIK' if trailing_stop else 'KAPALI'}")
    print(f"  Trend Filtresi: {'AÇIK' if df_gunluk is not None else 'KAPALI'}")
    print(f"  Mum sayısı: {len(df)}")
    print(f"{'='*55}\n")

    portfoy        = sermaye
    pozisyon       = None
    giris_fiyat    = 0
    en_iyi_fiy     = 0
    islemler       = []
    portfoy_gecmis = []
    gunluk_zarar   = 0
    son_gun        = None

    for tarih, satir in df.iterrows():
        fiyat = satir['close']
        gun   = tarih.date() if hasattr(tarih, 'date') else tarih

        if gun != son_gun:
            gunluk_zarar = 0
            son_gun      = gun

        if gunluk_zarar >= max_gunluk_zarar:
            portfoy_gecmis.append({"tarih": tarih, "portfoy": portfoy})
            continue

        trend = trend_belirle(df_gunluk, tarih) if df_gunluk is not None else "NOTR"

        # Açık pozisyon kontrolü
        if pozisyon is not None:
            if pozisyon == "LONG":
                if trailing_stop:
                    en_iyi_fiy = max(en_iyi_fiy, fiyat)
                    stop_fiyat = en_iyi_fiy * (1 - stop_loss_pct / 100)
                else:
                    stop_fiyat = giris_fiyat * (1 - stop_loss_pct / 100)
                tp_fiyat = giris_fiyat * (1 + take_profit_pct / 100)
                degisim  = (fiyat - giris_fiyat) / giris_fiyat * 100
                kapandi  = fiyat <= stop_fiyat or fiyat >= tp_fiyat
                tip      = "TP" if fiyat >= tp_fiyat else "TSL"

            else:  # SHORT
                if trailing_stop:
                    en_iyi_fiy = min(en_iyi_fiy, fiyat)
                    stop_fiyat = en_iyi_fiy * (1 + stop_loss_pct / 100)
                else:
                    stop_fiyat = giris_fiyat * (1 + stop_loss_pct / 100)
                tp_fiyat = giris_fiyat * (1 - take_profit_pct / 100)
                degisim  = (giris_fiyat - fiyat) / giris_fiyat * 100
                kapandi  = fiyat >= stop_fiyat or fiyat <= tp_fiyat
                tip      = "TP" if fiyat <= tp_fiyat else "TSL"

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
            sinyal = sinyal_uret(satir, trend, mod)
            if sinyal == "AL":
                pozisyon   = "LONG"
                giris_fiyat = fiyat
                en_iyi_fiy  = fiyat
            elif sinyal == "SAT":
                pozisyon   = "SHORT"
                giris_fiyat = fiyat
                en_iyi_fiy  = fiyat

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
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10))
    fig.suptitle(
        f"Backtest: {mod.upper()} | Başarı: %{basari_orani:.1f} | Kar: ${toplam_kar:.2f}",
        fontsize=12
    )

    ax1.plot(df.index, df['close'], color='gray', linewidth=0.8, label='Fiyat')
    ax1.plot(df.index, df['ma20'],  color='blue',   linewidth=0.8, alpha=0.7, label='MA20')
    ax1.plot(df.index, df['ma50'],  color='orange', linewidth=0.8, alpha=0.7, label='MA50')
    ax1.fill_between(df.index, df['bb_ust'], df['bb_alt'], alpha=0.1, color='purple')
    al_ist  = islem_df[islem_df['yon'] == 'LONG']
    sat_ist = islem_df[islem_df['yon'] == 'SHORT']
    ax1.scatter(al_ist['tarih'],  al_ist['giris'],  marker='^', color='green', s=40, zorder=5, label='AL')
    ax1.scatter(sat_ist['tarih'], sat_ist['giris'], marker='v', color='red',   s=40, zorder=5, label='SAT')
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

    ax3.plot(df.index, df['rsi'], color='purple', linewidth=0.8)
    ax3.axhline(y=70, color='red',   linestyle='--', linewidth=0.8, alpha=0.7)
    ax3.axhline(y=30, color='green', linestyle='--', linewidth=0.8, alpha=0.7)
    ax3.set_ylabel('RSI')
    ax3.set_ylim(0, 100)
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    grafik = os.path.join(
        SONUC_KLASOR,
        f"backtest_{mod}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
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


# ── DataFrame Tabanlı Backtest (grafik üretmez) ──────────────────

def calistir_df(df, df_gunluk=None, mod="uzun", sermaye=1000.0, kaldirac=3,
                stop_loss_pct=1.0, take_profit_pct=2.0,
                max_gunluk_zarar=75.0, trailing_stop=True, ilerleme=False):
    """
    DataFrame'den backtest çalıştır — grafik üretmez.

    Parameters
    ----------
    df         : datetime index'li OHLCV DataFrame
    df_gunluk  : günlük trend filtresi için ayrı OHLCV DataFrame
                 (gostergeler_ekle zaten uygulanmışsa tekrar uygulanmaz)
    ilerleme   : True ise her 50k mumda ilerleme yüzdesi basar

    Returns
    -------
    (stats_dict, islem_df, portfoy_df)
      islem_df  — tarih, yil, tip, yon, giris, cikis, kar_zarar, portfoy
      portfoy_df— tarih, portfoy
    """
    df = timezone_temizle(df.copy())
    df = gostergeler_ekle(df)

    if df_gunluk is not None:
        df_gunluk = timezone_temizle(df_gunluk.copy())
        if "ma50" not in df_gunluk.columns:
            df_gunluk = gostergeler_ekle(df_gunluk)

    portfoy        = sermaye
    pozisyon       = None
    giris_fiyat    = 0.0
    en_iyi_fiy     = 0.0
    aktif_kaldirac = kaldirac   # dinamik ADX kaldıracı — pozisyon açılışında güncellenir
    islemler       = []
    portfoy_gec    = []
    gunluk_zarar   = 0.0
    son_gun        = None
    toplam_mum     = len(df)

    for i, (tarih, satir) in enumerate(df.iterrows()):
        if ilerleme and i % 50_000 == 0 and i > 0:
            print(f"    ilerleme: {i:,}/{toplam_mum:,} ({i/toplam_mum*100:.0f}%)")

        fiyat = satir["close"]
        gun   = tarih.date() if hasattr(tarih, "date") else tarih

        if gun != son_gun:
            gunluk_zarar = 0.0
            son_gun      = gun

        if gunluk_zarar >= max_gunluk_zarar:
            portfoy_gec.append({"tarih": tarih, "portfoy": portfoy})
            continue

        trend = trend_belirle(df_gunluk, tarih) if df_gunluk is not None else "NOTR"

        # ── Açık pozisyon kontrolü ──────────────────────────────
        if pozisyon is not None:
            if pozisyon == "LONG":
                if trailing_stop:
                    en_iyi_fiy = max(en_iyi_fiy, fiyat)
                    stop_fiyat = en_iyi_fiy * (1 - stop_loss_pct / 100)
                else:
                    stop_fiyat = giris_fiyat * (1 - stop_loss_pct / 100)
                tp_fiyat = giris_fiyat * (1 + take_profit_pct / 100)
                degisim  = (fiyat - giris_fiyat) / giris_fiyat * 100
                kapandi  = fiyat <= stop_fiyat or fiyat >= tp_fiyat
                tip      = "TP" if fiyat >= tp_fiyat else "TSL"

            else:  # SHORT
                if trailing_stop:
                    en_iyi_fiy = min(en_iyi_fiy, fiyat)
                    stop_fiyat = en_iyi_fiy * (1 + stop_loss_pct / 100)
                else:
                    stop_fiyat = giris_fiyat * (1 + stop_loss_pct / 100)
                tp_fiyat = giris_fiyat * (1 - take_profit_pct / 100)
                degisim  = (giris_fiyat - fiyat) / giris_fiyat * 100
                kapandi  = fiyat >= stop_fiyat or fiyat <= tp_fiyat
                tip      = "TP" if fiyat <= tp_fiyat else "TSL"

            if kapandi:
                kz = portfoy * (abs(degisim) / 100) * aktif_kaldirac * (1 if degisim > 0 else -1)
                portfoy      += kz
                gunluk_zarar += abs(kz) if kz < 0 else 0.0
                islemler.append({
                    "tarih":     tarih,
                    "yil":       tarih.year,
                    "tip":       tip,
                    "yon":       pozisyon,
                    "giris":     giris_fiyat,
                    "cikis":     fiyat,
                    "kar_zarar": kz,
                    "portfoy":   portfoy,
                    "kaldirac":  aktif_kaldirac,
                })
                pozisyon = None

        # ── Yeni sinyal ─────────────────────────────────────────
        if pozisyon is None:
            # Yatay piyasa filtresi: son 50 mum aralığı %1 altındaysa işlem yapma
            yatay = ('yatay_aralik' in satir
                     and not np.isnan(satir['yatay_aralik'])
                     and satir['yatay_aralik'] < 1.0)
            sinyal = "BEKLE" if yatay else sinyal_uret(satir, trend, mod)

            if sinyal == "AL":
                pozisyon    = "LONG"
                giris_fiyat = fiyat
                en_iyi_fiy  = fiyat
                # Dinamik kaldıraç — ADX'e göre
                adx_val = satir['adx'] if 'adx' in satir else 20.0
                aktif_kaldirac = 3 if adx_val > 25 else (2 if adx_val >= 15 else 1)
            elif sinyal == "SAT":
                pozisyon    = "SHORT"
                giris_fiyat = fiyat
                en_iyi_fiy  = fiyat
                adx_val = satir['adx'] if 'adx' in satir else 20.0
                aktif_kaldirac = 3 if adx_val > 25 else (2 if adx_val >= 15 else 1)

        portfoy_gec.append({"tarih": tarih, "portfoy": portfoy})

    islem_df   = pd.DataFrame(islemler)
    portfoy_df = pd.DataFrame(portfoy_gec)

    if islem_df.empty:
        return (
            {"final_portfoy": portfoy, "baslangic": sermaye,
             "toplam_kar": 0.0, "getiri_pct": 0.0,
             "basari_orani": 0.0, "islem_sayisi": 0,
             "karli_islem": 0, "zararli_islem": 0, "max_drawdown": 0.0},
            islem_df, portfoy_df,
        )

    karli        = islem_df[islem_df["kar_zarar"] > 0]
    zararli      = islem_df[islem_df["kar_zarar"] < 0]
    basari_orani = len(karli) / len(islem_df) * 100
    toplam_kar   = islem_df["kar_zarar"].sum()

    portfoy_df["zirve"]    = portfoy_df["portfoy"].cummax()
    portfoy_df["drawdown"] = (
        (portfoy_df["portfoy"] - portfoy_df["zirve"]) / portfoy_df["zirve"] * 100
    )
    max_drawdown = portfoy_df["drawdown"].min()

    stats = {
        "final_portfoy": portfoy,
        "baslangic":     sermaye,
        "toplam_kar":    toplam_kar,
        "getiri_pct":    toplam_kar / sermaye * 100,
        "basari_orani":  basari_orani,
        "islem_sayisi":  len(islem_df),
        "karli_islem":   len(karli),
        "zararli_islem": len(zararli),
        "max_drawdown":  max_drawdown,
    }

    return stats, islem_df, portfoy_df


if __name__ == "__main__":
    print("KISA VADELİ BACKTEST (10x kaldıraç)")
    calistir(
        dosya="altin_5m_2026.csv",
        mod="kisa",
        sermaye=1000,
        kaldirac=10,
        stop_loss_pct=0.5,
        take_profit_pct=1.0,
        max_gunluk_zarar=75,
        trailing_stop=True
    )

    print("UZUN VADELİ BACKTEST (3x kaldıraç)")
    calistir(
        dosya="altin_15m_2026.csv",
        mod="uzun",
        sermaye=1000,
        kaldirac=3,
        stop_loss_pct=1.0,
        take_profit_pct=2.0,
        max_gunluk_zarar=75,
        trailing_stop=True
    )
