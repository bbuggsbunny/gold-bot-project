# main.py
# ─────────────────────────────────────────────
# Giriş noktası. İş mantığı bot/ paketinde:
#   bot/durum.py  — paylaşılan bağlam + günlük zarar takibi
#   bot/dongu.py  — analiz hattı ve zamanlayıcı
# ─────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from agents.telegram_agent import bildir_durum
from bot.durum import BaglamDurumu, ZararTakibi
from bot.dongu import KISA, UZUN, zamanlayici


def _banner():
    print("\n" + "★" * 52)
    print("  ALTIN TRADİNG BOTU — 2 KATMANLI SİSTEM")
    print(f"  Kısa vadeli : 1 dk   | {KISA.strateji:<13} | {KISA.kaldirac}x")
    print(f"  Makro       : 15 dk  | DXY/VIX/TNX   |")
    print(f"  Takvim      : 1 saat | Ekonomik veri |")
    print(f"  Uzun vadeli : 4 saat | {UZUN.strateji:<13} | {UZUN.kaldirac}x")
    print(f"  Mod         : {'TESTNET' if config.TESTNET else '*** GERÇEK PARA ***'}")
    print("  Durdurmak için: Ctrl+C")
    print("★" * 52)


def main():
    _banner()

    mod = "TESTNET" if config.TESTNET else "GERÇEK PARA"
    bildir_durum(f"Altın Trading Botu başlatıldı.\nMod: {mod} | Sembol: {config.SYMBOL}")

    durum = BaglamDurumu()
    zarar = ZararTakibi(limit=config.MAX_GUNLUK_ZARAR, miktar=config.QUANTITY)

    try:
        zamanlayici(durum, zarar)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
