import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


def _gonder(mesaj: str) -> bool:
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Telegram] Hata: {e}")
        return False


def bildir_sinyal(yon: str, fiyat: float, strateji: str, guven: int):
    """AL/SAT sinyali bildirimi."""
    emoji = "🟢" if yon == "AL" else "🔴"
    mesaj = (
        f"{emoji} <b>{yon} SİNYALİ</b>\n"
        f"💰 Fiyat: <b>${fiyat:,.2f}</b>\n"
        f"📊 Strateji: {strateji}\n"
        f"🎯 Güven: {guven}/10"
    )
    return _gonder(mesaj)


def bildir_emir(yon: str, fiyat: float, miktar: float, sl: float, tp: float):
    """Emir gönderildi bildirimi."""
    emoji = "🟢" if yon == "AL" else "🔴"
    mesaj = (
        f"{emoji} <b>EMİR GÖNDERİLDİ</b>\n"
        f"Yön: {yon} | Miktar: {miktar} oz\n"
        f"Fiyat: ${fiyat:,.2f}\n"
        f"🛡 SL: ${sl:,.2f}\n"
        f"🎯 TP: ${tp:,.2f}"
    )
    return _gonder(mesaj)


def bildir_kapanis(yon: str, kar_zarar: float):
    """Pozisyon kapandı bildirimi."""
    emoji = "✅" if kar_zarar >= 0 else "❌"
    mesaj = (
        f"{emoji} <b>POZİSYON KAPANDI</b>\n"
        f"Yön: {yon}\n"
        f"K/Z: <b>${kar_zarar:+.2f}</b>"
    )
    return _gonder(mesaj)


def bildir_hata(hata: str):
    """Hata bildirimi."""
    return _gonder(f"⚠️ <b>HATA</b>\n{hata}")


def bildir_durum(mesaj: str):
    """Genel durum bildirimi (bot başlangıcı, durdurma vb.)"""
    return _gonder(f"ℹ️ {mesaj}")


def bildir_ozet(gun_kar_zarar: float, islem_sayisi: int, bakiye: float):
    """Günlük özet bildirimi."""
    emoji = "📈" if gun_kar_zarar >= 0 else "📉"
    mesaj = (
        f"{emoji} <b>GÜNLÜK ÖZET</b>\n"
        f"K/Z: <b>${gun_kar_zarar:+.2f}</b>\n"
        f"İşlem: {islem_sayisi}\n"
        f"Bakiye: ${bakiye:,.2f}"
    )
    return _gonder(mesaj)
