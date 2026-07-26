"""
XGBoost model eğitimi — XAUUSD 15dk, 2009-2025
  Eğitim : 2009-2022
  Test   : 2023-2025
  Hedef  : -1 (SAT) / 0 (BEKLE) / 1 (AL)
"""
import time
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder

FEATURES_CSV = Path(__file__).parent / "features.csv"
MODEL_PKL    = Path(__file__).parent / "model.pkl"

OZELLIKLER = ["rsi", "macd_hist", "bb_poz", "adx",
              "ma_oran", "volatilite", "atr",
              "yon_3", "momentum_5", "rsi_hiz",
              "saat", "gun"]

t0 = time.time()

# ── 1. Veri yükleme ──────────────────────────────────────────────────────────
print("Veri yükleniyor...")
df = pd.read_csv(FEATURES_CSV, index_col=0, parse_dates=True)
print(f"  Toplam: {len(df):,} satır  |  {df.index[0].date()} → {df.index[-1].date()}")

# ── 2. Zaman bazlı bölme ─────────────────────────────────────────────────────
egitim = df[df.index.year <= 2022]
test   = df[df.index.year >= 2023]

X_egitim = egitim[OZELLIKLER]
y_egitim = egitim["hedef"].astype(int)

X_test = test[OZELLIKLER]
y_test = test["hedef"].astype(int)

print(f"\n  Eğitim (2009-2022): {len(X_egitim):>7,} örnek")
print(f"  Test   (2023-2025): {len(X_test):>7,} örnek")

# XGBoost -1/0/1 etiketlerini 0/1/2 olarak ister → LabelEncoder
le = LabelEncoder()
y_egitim_enc = le.fit_transform(y_egitim)   # -1→0, 0→1, 1→2
y_test_enc   = le.transform(y_test)
# le.classes_ = [-1, 0, 1]

# ── 3. Model eğitimi ─────────────────────────────────────────────────────────
print("\nModel eğitiliyor...")

# Balanced base: her sınıfı eşit ağırlıkla başlat → azınlık sınıflar (AL/SAT) daha ağır
# Sonra BEKLE'yi 3x büyüt → model BEKLE doğruluğuna daha çok önem verir (daha seçici sinyal)
# Sonuç: AL/SAT hâlâ BEKLE'den ağır, ama BEKLE sadece balanced'a göre 3x daha fazla
# le.classes_ = [-1, 0, 1]  →  enc = [0=SAT, 1=BEKLE, 2=AL]
counts          = np.bincount(y_egitim_enc)                          # [n_SAT, n_BEKLE, n_AL]
balanced        = len(y_egitim_enc) / (3 * counts)                  # ~[2.37, 0.47, 2.17]
sinif_agirliklari = balanced.copy()
sinif_agirliklari[1] *= 3                                            # BEKLE 3x boost → ~1.41
ornek_agirliklari = sinif_agirliklari[y_egitim_enc]
print(f"  Sınıf ağırlıkları → SAT:{sinif_agirliklari[0]:.2f}  "
      f"BEKLE:{sinif_agirliklari[1]:.2f}  AL:{sinif_agirliklari[2]:.2f}")

model = XGBClassifier(
    n_estimators     = 300,
    max_depth        = 5,
    learning_rate    = 0.05,
    subsample        = 0.8,
    colsample_bytree = 0.8,
    min_child_weight = 35,
    random_state     = 42,
    n_jobs           = -1,
    eval_metric      = "mlogloss",
    verbosity        = 0,
)

model.fit(
    X_egitim, y_egitim_enc,
    sample_weight = ornek_agirliklari,
    eval_set      = [(X_test, y_test_enc)],
    verbose       = False,
)

t_egitim = time.time() - t0
print(f"  Eğitim süresi: {t_egitim:.1f}s")

# ── 4. Değerlendirme ─────────────────────────────────────────────────────────
y_pred_enc = model.predict(X_test)
y_pred     = le.inverse_transform(y_pred_enc)   # 0/1/2 → -1/0/1

etiketler    = [-1, 0, 1]
etiket_isim  = ["SAT (-1)", "BEKLE (0)", "AL  (1)"]

print("\n" + "=" * 55)
print("  SINIFLANDIRMA RAPORU — Test Seti (2023-2025)")
print("=" * 55)

rapor = classification_report(
    y_test, y_pred,
    labels      = etiketler,
    target_names= etiket_isim,
    zero_division= 0,
    output_dict = True,
)

# Başlık satırı
print(f"  {'Sınıf':<12} {'Precision':>10} {'Recall':>8} {'F1':>8} {'Destek':>9}")
print("  " + "-" * 51)
for isim in etiket_isim:
    r = rapor[isim]
    print(f"  {isim:<12} {r['precision']:>10.3f} {r['recall']:>8.3f} "
          f"{r['f1-score']:>8.3f} {int(r['support']):>9,}")
print("  " + "-" * 51)
acc = rapor["accuracy"]
print(f"  {'Accuracy':<12} {acc:>10.3f}")
wa  = rapor["weighted avg"]
print(f"  {'Weighted avg':<12} {wa['precision']:>10.3f} {wa['recall']:>8.3f} {wa['f1-score']:>8.3f}")

# Confusion matrix
print("\n  Confusion Matrix (satır=gerçek, sütun=tahmin):")
cm = confusion_matrix(y_test, y_pred, labels=etiketler)
baslik = f"  {'':>12} " + "  ".join(f"{n:>10}" for n in etiket_isim)
print(baslik)
for gercek, satir in zip(etiket_isim, cm):
    hucre = "  ".join(f"{v:>10,}" for v in satir)
    print(f"  {gercek:<12} {hucre}")

# ── 5. Olasılık eşiği değerlendirmesi ───────────────────────────────────────
# Varsayılan argmax yerine sadece yüksek güvenli tahminleri AL/SAT say
print("\n  Olasılık eşiği analizi (AL/SAT precision vs sinyal oranı):")
print(f"  {'Eşik':>6}  {'SAT prec':>9}  {'AL prec':>8}  {'Sinyal%':>8}")
print("  " + "-" * 38)
y_proba = model.predict_proba(X_test)   # [SAT=0, BEKLE=1, AL=2]
y_test_arr = np.array(y_test)

KAYIT_ESIGI = 0.40
for esik in [0.30, 0.35, 0.40, 0.45, 0.50]:
    pred = np.ones(len(X_test), dtype=int)           # default: BEKLE=1
    pred[y_proba[:, 0] > esik] = 0                   # SAT
    pred[y_proba[:, 2] > esik] = 2                   # AL
    # Çakışma: her ikisi de eşiği geçerse en yüksek olasılığa bak
    cakisma = (y_proba[:, 0] > esik) & (y_proba[:, 2] > esik)
    if cakisma.any():
        pred[cakisma] = np.where(
            y_proba[cakisma, 0] > y_proba[cakisma, 2], 0, 2
        )
    y_pred_esik = le.inverse_transform(pred)

    r = classification_report(y_test_arr, y_pred_esik,
                               labels=[-1,0,1], output_dict=True, zero_division=0)
    sinyal_pct = (pred != 1).mean() * 100
    sat_prec   = r["SAT (-1)"]["precision"] if "SAT (-1)" in r else r.get("-1",{}).get("precision",0)
    al_prec    = r["AL  (1)"]["precision"]  if "AL  (1)"  in r else r.get("1",{}).get("precision",0)
    # classification_report uses target_names only if given; use labels directly
    sat_p = r["-1"]["precision"] if "-1" in r else 0
    al_p  = r["1"]["precision"]  if "1"  in r else 0
    star  = " ← kaydedildi" if esik == KAYIT_ESIGI else ""
    print(f"  {esik:>6.2f}  {sat_p:>9.3f}  {al_p:>8.3f}  {sinyal_pct:>7.1f}%{star}")

# Kaydetmek için eşik=0.40 kullan
pred_final = np.ones(len(X_test), dtype=int)
pred_final[y_proba[:, 0] > KAYIT_ESIGI] = 0
pred_final[y_proba[:, 2] > KAYIT_ESIGI] = 2
cakisma = (y_proba[:, 0] > KAYIT_ESIGI) & (y_proba[:, 2] > KAYIT_ESIGI)
if cakisma.any():
    pred_final[cakisma] = np.where(
        y_proba[cakisma, 0] > y_proba[cakisma, 2], 0, 2
    )
y_pred_final = le.inverse_transform(pred_final)

print("\n  Seçili eşik (0.40) ile tam rapor:")
print(f"  {'Sınıf':<12} {'Precision':>10} {'Recall':>8} {'F1':>8} {'Destek':>9}")
print("  " + "-" * 51)
r40 = classification_report(y_test_arr, y_pred_final, labels=[-1,0,1],
                             target_names=etiket_isim, zero_division=0, output_dict=True)
for isim in etiket_isim:
    rv = r40[isim]
    print(f"  {isim:<12} {rv['precision']:>10.3f} {rv['recall']:>8.3f} "
          f"{rv['f1-score']:>8.3f} {int(rv['support']):>9,}")

# ── 6. En önemli 5 özellik ───────────────────────────────────────────────────
print("\n  En önemli 5 özellik (gain):")
onem = model.get_booster().get_score(importance_type="gain")
onem_sirali = sorted(onem.items(), key=lambda x: x[1], reverse=True)[:5]
maks = onem_sirali[0][1]
for sira, (ozellik, deger) in enumerate(onem_sirali, 1):
    bar = "█" * int(deger / maks * 25)
    print(f"  {sira}. {ozellik:<14} {deger:>8.1f}  {bar}")

# ── 7. Modeli kaydet ─────────────────────────────────────────────────────────
with open(MODEL_PKL, "wb") as f:
    pickle.dump({"model": model, "label_encoder": le,
                 "ozellikler": OZELLIKLER, "esik": KAYIT_ESIGI}, f)

print(f"\n  Model kaydedildi: {MODEL_PKL.name}")
print(f"  Toplam süre     : {time.time() - t0:.1f}s")
print("=" * 55)
