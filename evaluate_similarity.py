# evaluate_similarity.py - هل كان فلتر "التشابه" سيُحسّن النتائج؟ (walk-forward بلا تسريب مستقبلي)
# الاستعمال:  python evaluate_similarity.py [trade_memory.json]
# يقارن لكل صفقة: أقرب K صفقات *سابقة لها فقط*، ثم يحسب نتيجة الصفقات التي كان الفلتر سيسمح بها.
import json, math, sys

path = sys.argv[1] if len(sys.argv) > 1 else "trade_memory.json"
COMPS = [("timeframe_points", 20), ("volume_points", 15), ("rsi_points", 10), ("momentum_points", 10),
         ("price_action_points", 8), ("order_book_points", 10), ("funding_oi_points", 10), ("market_points", 5)]

def vec(t):
    sd = t["score_details"]
    v = [float(sd.get(k, 0) or 0) / m for k, m in COMPS]
    v.append(min(float(t.get("volume_ratio", 0) or 0), 4) / 4)
    v.append(1.0 if t["direction"] == "BUY" else 0.0)
    return v

d = json.load(open(path, encoding="utf-8"))
T = [t for t in d["trades"] if t.get("pnl_verified") and abs(t.get("pnl", 0)) >= 0.10 and t.get("score_details")]
T.sort(key=lambda t: t["entry_time"])
V = [vec(t) for t in T]
W = [1 if t["pnl"] > 0 else 0 for t in T]
P = [t["pnl"] for t in T]
dist = lambda a, b: math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

print(f"صفقات موثّقة مستخدمة: {len(T)}  | صافي: {sum(P):.2f}$")
if len(T) < 60:
    print("⚠️ العيّنة صغيرة - النتائج ضوضاء غالباً. اجمع 150+ صفقة قبل أي قرار.")

for k in (5, 10, 15):
    rows = []
    for i in range(30, len(T)):
        nb = sorted(range(i), key=lambda j: dist(V[i], V[j]))[:k]
        rows.append((sum(W[j] for j in nb) / k, P[i]))
    if not rows:
        continue
    base = sum(p for _, p in rows)
    print(f"\nK={k}  (الأساس: n={len(rows)} صافي={base:.1f} متوسط={base/len(rows):.2f})")
    for thr in (0.35, 0.5, 0.6):
        ok = [p for w, p in rows if w >= thr]
        if ok:
            print(f"  السماح فقط إن نجاح الجيران >= {thr:.0%}: n={len(ok)} صافي={sum(ok):.1f} "
                  f"متوسط={sum(ok)/len(ok):.2f} نجاح={sum(1 for p in ok if p>0)/len(ok):.0%}")
    xs = [w for w, _ in rows]; ys = [p for _, p in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    if den:
        c = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / den
        print(f"  الارتباط بين توقّع الفلتر والنتيجة الفعلية: {c:+.2f}  (يجب أن يكون موجباً بوضوح ليستحق التفعيل)")
