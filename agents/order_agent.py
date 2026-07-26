# agents/order_agent.py
# ─────────────────────────────────────────────
# Emir Ajanı: Onaylanan kararı Binance Futures'a iletir.
# Stop-loss ve take-profit otomatik ayarlanır.
# Güven skoru düşükse veya BEKLE kararıysa hiçbir şey yapmaz.
# ─────────────────────────────────────────────

import time
from binance.client import Client
from binance.enums import (
    SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_MARKET,
    FUTURE_ORDER_TYPE_STOP_MARKET,
    FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET
)
from datetime import datetime
import config
from tipler import Karar, EmirSonucu
from agents.utils import senkronize_et
from agents.telegram_agent import bildir_hata


def get_client():
    return Client(
        config.BINANCE_API_KEY,
        config.BINANCE_SECRET_KEY,
        testnet=config.TESTNET
    )


def bakiye_getir() -> float:
    """
    USDT futures bakiyesi. Alınamazsa -1.0 döner (bot durmaz).
    Günlük özet bildiriminde gerçek K/Z'yi hesaplamak için kullanılıyor.
    """
    try:
        client = get_client()
        senkronize_et(client)
        for varlik in client.futures_account_balance():
            if varlik.get("asset") == "USDT":
                return float(varlik.get("balance", 0))
    except Exception as e:
        print(f"  [BAKİYE] ⚠️  Alınamadı ({type(e).__name__}): {e}")
    return -1.0


def calistir(karar: Karar, fiyat: float, kaldirac: int) -> EmirSonucu:
    """
    Karar ajanından gelen kararı işle ve Binance'e gönder.

    kaldirac: çağıran katmanın kaldıracı
              (config.KALDIRAC_KISA = 10x / config.KALDIRAC_UZUN = 3x)

    Mantık:
    - BEKLE → hiçbir şey yapma
    - Güven < MIN_GUVEN_SKORU → hiçbir şey yapma
    - AL → long pozisyon aç, stop-loss altında, take-profit üstünde
    - SAT → short pozisyon aç, stop-loss üstünde, take-profit altında
    """
    zaman = datetime.now().strftime("%H:%M:%S")

    # Emir gönderme koşulları
    if not karar.islem_var:
        mesaj = f"[{zaman}] BEKLE — {karar.gerekce}"
        print(mesaj)
        return EmirSonucu(durum="bekle", mesaj=mesaj)

    if karar.guven < config.MIN_GUVEN_SKORU:
        mesaj = f"[{zaman}] Güven skoru düşük ({karar.guven}/10), emir verilmedi."
        print(mesaj)
        return EmirSonucu(durum="dusuk_guven", mesaj=mesaj)

    # Hangi yönde işlem?
    islem_yonu = karar.eylem  # "AL" veya "SAT"
    side       = SIDE_BUY if islem_yonu == "AL" else SIDE_SELL
    kapat_side = SIDE_SELL if islem_yonu == "AL" else SIDE_BUY

    # Stop-loss ve take-profit fiyatlarını hesapla
    if islem_yonu == "AL":
        stop_loss_fiyat   = round(fiyat * (1 - karar.stop_loss_pct / 100), 2)
        take_profit_fiyat = round(fiyat * (1 + karar.take_profit_pct / 100), 2)
    else:
        stop_loss_fiyat   = round(fiyat * (1 + karar.stop_loss_pct / 100), 2)
        take_profit_fiyat = round(fiyat * (1 - karar.take_profit_pct / 100), 2)

    print(f"\n[{zaman}] {'='*45}")
    print(f"  EMİR      : {islem_yonu}")
    print(f"  Fiyat     : {fiyat} USD")
    print(f"  Miktar    : {config.QUANTITY} oz")
    print(f"  Kaldıraç  : {kaldirac}x")
    print(f"  Stop-Loss : {stop_loss_fiyat} USD (-%{karar.stop_loss_pct})")
    print(f"  Take-Prof : {take_profit_fiyat} USD (+%{karar.take_profit_pct})")
    print(f"  Güven     : {karar.guven}/10")
    print(f"  Gerekçe   : {karar.gerekce}")
    print(f"  Mod       : {'TESTNET' if config.TESTNET else 'GERÇEK PARA'}")

    client = get_client()
    senkronize_et(client)

    son_hata = None
    for deneme in range(1, 4):
        try:
            # 1. Kaldıraç ayarla
            client.futures_change_leverage(
                symbol=config.SYMBOL,
                leverage=kaldirac
            )

            # 2. Ana piyasa emri
            emir = client.futures_create_order(
                symbol=config.SYMBOL,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=config.QUANTITY
            )
            print(f"\n  Ana emir gönderildi. ID: {emir['orderId']}")

            # 3. Stop-Loss emri
            sl_emir = client.futures_create_order(
                symbol=config.SYMBOL,
                side=kapat_side,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                stopPrice=stop_loss_fiyat,
                closePosition=True
            )
            print(f"  Stop-Loss ayarlandı. ID: {sl_emir['orderId']}")

            # 4. Take-Profit emri
            tp_emir = client.futures_create_order(
                symbol=config.SYMBOL,
                side=kapat_side,
                type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                stopPrice=take_profit_fiyat,
                closePosition=True
            )
            print(f"  Take-Profit ayarlandı. ID: {tp_emir['orderId']}")
            print(f"\n  Tüm emirler başarıyla gönderildi.")

            return EmirSonucu(
                islem=islem_yonu,
                fiyat=fiyat,
                stop_loss=stop_loss_fiyat,
                take_profit=take_profit_fiyat,
                emir_id=emir["orderId"],
            )

        except Exception as e:
            son_hata = e
            print(f"\n  [Retry {deneme}/3] Emir hatası: {e}")
            if deneme < 3:
                time.sleep(5)

    bildir_hata(f"order_agent emir gönderilemedi (3 deneme): {son_hata}")
    return EmirSonucu.hata(son_hata)


if __name__ == "__main__":
    # Gerçek emir GÖNDERİLMEZ — sadece emir öncesi kontroller test edilir.
    print("Emir ajani test ediliyor (BEKLE senaryosu)...\n")
    sonuc = calistir(
        Karar(eylem="BEKLE", guven=4, gerekce="Sinyal yetersiz"),
        4536.26, config.KALDIRAC_KISA,
    )
    print(f"Sonuc: {sonuc.durum}\n")

    print("Dusuk guven senaryosu...\n")
    sonuc = calistir(
        Karar(eylem="AL", guven=3, gerekce="Zayif sinyal"),
        4536.26, config.KALDIRAC_KISA,
    )
    print(f"Sonuc: {sonuc.durum}")
