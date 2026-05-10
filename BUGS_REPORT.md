# Bug Investigation — `basira-engine/basira_app.py`
_Investigation 2026-05-10. Source code NOT modified — diffs proposed below for review._

Inputs reviewed:
- `basira-engine/uploads/7cd820b277_basira_regression_stress.csv` (150 rows × 10 cols)
- `basira-engine/outputs/7cd820b277_audit_basira_regression_stress.html`
- `basira-engine/outputs/7cd820b277_config_basira_regression_stress.json`
- `basira-engine/basira_app.py`

---

## BUG #1 (CRITICAL) — Missing-token standardization is **absent**, not just out of order

### Your description
> "Missing token standardization runs AFTER column type detection, not before."

### What I actually found
**There is no missing-token standardization step in `basira_app.py` at all.** A grep across the entire file for any of the 20+ tokens listed in CLAUDE.md (`?`, `-`, `.`, `missing`, `لا يوجد`, `بدون`, `غير معروف`, `لاشيء`, `غير محدد`, `لا شي`, …) and for any `na_values=`, `to_replace=`, or `MISSING_TOKENS` constant returns **zero hits**:

```
$ grep -nE '(MISSING_TOK|NULL_TOK|NAN_TOK|na_values|بدون|غير|لا يوجد|لاشيء)' basira_app.py
(no matches)
```

The only NaN handling is whatever pandas does by default at read time (`pd.read_csv(...)` is called at line 1145 with no `na_values=` argument). Pandas' default set covers only:
`'', '#N/A', '#N/A N/A', '#NA', '-NaN', '-nan', 'N/A', 'NA', 'NULL', 'NaN', 'None', 'n/a', 'nan', 'null', '<NA>'` etc.

It does **not** cover any of: `?`, `-`, `.`, `missing`, or any of the Arabic tokens. Those values stay in the column as ordinary strings.

### Evidence from the stress run

The cells that should be NaN became sticky string values, which broke type inference. From the input CSV (rows 16, 18, 26, 27, etc.):

| Column        | Sample values that should be NaN (from input)                                  |
|---------------|--------------------------------------------------------------------------------|
| `unit_price`  | `بدون`, `غير محدد`, `غير معروف`, `?`, `.`, `n/a`, `NULL`                      |
| `discount_pct`| `missing`, `غير معروف`, `لاشيء`, `.`, `?`, `null`, `n/a`, `غير معروف`         |
| `shipping_cost`| `لا يوجد`, `?`, `غير معروف`, `missing`, `null`, `لا شي`, `NA`                  |

`_detect_type` then runs the 95% numeric-coercion test (`basira_app.py:118–123`) and these dirty tokens push parse rate below 95%, so the column gets routed to the categorical branch at line 135–139. The audit/config confirms it:

```json
"col_types": {
  "unit_price":    "categorical",   // should be float
  "discount_pct":  "categorical",   // should be float
  "shipping_cost": "categorical"    // should be float
}
```

### The "smoking gun" (mode-imputed with `?`)

In `discount_pct`, `?` and `بدون` and `missing` end up in `value_counts()`. The mode imputer in step 10c picks the most frequent — which is the missing token itself. From the audit step "Missing Value Imputation":

> `unit_price`: mode=**"بدون"** (12 filled)
> `discount_pct`: mode=**"missing"** (13 filled)
> `shipping_cost`: mode=**"62.7"** (6 filled)  ← only this one got a real number, by luck

And the encoding map in the config preserves the dirty tokens as legitimate categories:

```json
"unit_price.top5":   { "بدون": 0.107, "غير محدد": 0.02, "غير معروف": 0.02, ... }
"discount_pct.top5": { "missing": 0.113, "غير معروف": 0.02, "لاشيء": 0.02, ".": 0.02, ... }
"shipping_cost.top5":{ "?": 0.013, "غير معروف": 0.013, "missing": 0.013, ... }
```

Even the supposedly clean target column `customer_segment_ar` is contaminated: the audit reports **10 distinct values**, but the dataset has only 4 real customer segments (`عميل ذهبي/فضي/جديد/برونزي` = gold/silver/new/bronze). The 6 extras are missing-token strings (`لا يوجد`, `لاشيء`, `غير معروف`, `N/A`, etc.) being treated as legitimate categories.

### Root cause

CLAUDE.md states:

> Replace 20+ missing tokens (English + Arabic, e.g. `N/A`, `لا يوجد`) → `NaN`

That replacement step exists in the spec but was never coded into `basira_app.py`. (It may live in the per-cell `_normalize_text` for text-typed columns at line 287, but that runs in step 11, after column types are already locked in at step 1, and it doesn't substitute NaN — it just lowercases / unicode-normalizes.)

So your description is correct in spirit but understates it: this isn't an ordering bug, it's a **missing feature**.

### Proposed fix

Add a `MISSING_TOKENS` constant and a one-pass standardization at the top of `preprocess()`, before column-type detection. This runs once over every column, so it costs nothing and unblocks `_detect_type`'s 95% coercion test.

```diff
--- a/basira-engine/basira_app.py
+++ b/basira-engine/basira_app.py
@@ -54,6 +54,21 @@ INCIDENT_KEYWORDS = {
     "ticket", "incident", "case", "request", "sla", "resolution", "issue",
     "error", "pr", "po", "rfx", "vendor", "root_cause", "complaint", "defect",
     "fault", "bug", "problem", "escalation",
 }

+# Tokens that should be treated as missing values regardless of language.
+# Compared CASE-INSENSITIVELY after .strip(); Arabic compared as-is (case-folding
+# is a no-op for Arabic but cheap, so we lowercase the column first).
+# CLAUDE.md spec: "Replace 20+ missing tokens (English + Arabic) → NaN".
+MISSING_TOKENS = {
+    # English / sentinel
+    "", "?", "-", ".", "n/a", "na", "null", "none", "nan",
+    "missing", "unknown", "tbd", "tba", "#n/a",
+    # Arabic
+    "لا يوجد", "لا شي", "لاشيء", "بدون", "غير معروف", "غير محدد",
+    "لا شيء", "لا توجد", "غير متوفر", "مجهول", "فارغ",
+}
+
+
 # ─────────────────────────────────────────────────────────────
 # COLUMN TYPE DETECTION
 # ─────────────────────────────────────────────────────────────
@@ -473,6 +488,21 @@ def preprocess(df: pd.DataFrame, file_name: str) -> dict:
     audit = []
     original_shape = df.shape

+    # ── 0. STANDARDIZE MISSING-VALUE TOKENS → NaN ────────────
+    # MUST run before _detect_type — otherwise dirty tokens push numeric
+    # columns below the 95% coerce threshold and they get misclassified
+    # as categorical (and later mode-imputed with "?", "بدون", etc.).
+    n_token_replacements = 0
+    for col in df.columns:
+        s = df[col]
+        if s.dtype != object:
+            continue
+        # strip whitespace, lowercase ASCII letters; Arabic is unaffected by .lower()
+        norm = s.astype(str).str.strip().str.lower()
+        mask = norm.isin(MISSING_TOKENS)
+        if mask.any():
+            n_token_replacements += int(mask.sum())
+            df.loc[mask, col] = pd.NA
+    audit.append({
+        "step": "Missing-Token Standardization",
+        "detail": (
+            f"Replaced {n_token_replacements} cell(s) matching the "
+            f"{len(MISSING_TOKENS)}-token missing list (English + Arabic) with NaN. "
+            "Runs before type detection so numeric columns are not misclassified."
+        ),
+    })
+
     # ── READINESS CHECK (BEFORE) ────────────────────────────
     rb = _readiness_check(df, "before_preprocessing")
     audit.append({
```

**Why this exact placement matters:** it must run before `_readiness_check` reports `max_missing_ratio` so that ratio counts the dirty tokens too — otherwise the readiness check stays optimistically green while the data is still polluted.

### Expected outcome on the stress dataset

After this fix, on `basira_regression_stress.csv`:
- `unit_price` → `float` (currently categorical)
- `discount_pct` → `float` (currently categorical)
- `shipping_cost` → `float` (currently categorical)
- `customer_segment_ar` → still categorical, but with **4 distinct values** instead of 10
- Numeric imputation strategy will switch from `simple` (because there were no numeric missing) to `mice` or `knn` (because there are now 3 numeric columns with material missingness)

---

## BUG #2 — `_auto_detect` prefers categorical over continuous numeric

### Current scoring (`basira_app.py:420–461`)

```python
score = 0
if any(k in cn for k in TARGET_KEYWORDS):
    score += 10
score += {"categorical": 5, "bool": 4, "int": 2, "float": 2}.get(ctype, 0)
null_pct = df[col].isna().mean()
if null_pct < 0.05:   score += 3
elif null_pct > 0.40: score -= 8
n_u = df[col].nunique()
if   2 <= n_u <= 30:  score += 2
elif n_u > 100:       score -= 2
```

### Why `customer_segment_ar` beat `total_revenue`

| Column                   | type       | name match | type pts | nullity pts | cardinality pts | **total** |
|---|---|---|---|---|---|---|
| `customer_segment_ar`    | categorical| no         | +5       | +3 (low null) | +2 (10 distinct) | **+10**  |
| `total_revenue` (target) | float      | no         | +2       | +3 (low null) | −2 (150 distinct) | **+3**  |

The categorical type bonus alone is +3 over float, before any other signal. Add the cardinality penalty for 100%-unique floats and the gap widens to +7.

### What "natural" target choice should look like

A continuous numeric column with 100% unique values isn't a bad regression target — it's a **good** one. The current scoring punishes it twice: once with the lower type weight (+2 vs +5), once with the >100-unique penalty (−2). The cardinality bracket `2 ≤ n_u ≤ 30` is essentially "looks like a classification target", which shouldn't be applied indiscriminately to numeric columns.

### Proposed fix — three options, you pick

#### Option A (lightest touch) — equalize weights, gate the cardinality penalty
Lift `float`/`int` to parity with `categorical`, and stop penalizing high cardinality on numeric types (those values are evidence of regression-suitability, not noise):

```diff
--- a/basira-engine/basira_app.py
+++ b/basira-engine/basira_app.py
@@ -425,18 +425,27 @@ def _auto_detect(df: pd.DataFrame, col_types: dict) -> tuple:
         cn = col.lower().replace(" ", "_")
         score = 0
         if any(k in cn for k in TARGET_KEYWORDS):
             score += 10
-        score += {"categorical": 5, "bool": 4, "int": 2, "float": 2}.get(ctype, 0)
+        # Type-base score. Continuous numerics are equally good targets —
+        # for regression they're the *only* good target.
+        score += {"categorical": 5, "bool": 4, "int": 5, "float": 5}.get(ctype, 0)
         null_pct = df[col].isna().mean()
         if null_pct < 0.05:
             score += 3
         elif null_pct > 0.40:
             score -= 8
         n_u = df[col].nunique()
-        if 2 <= n_u <= 30:
+        # Cardinality bonus only applies to candidate classification targets.
+        # Penalising high-uniqueness floats was punishing legitimate
+        # regression targets (e.g., total_revenue with 150 unique values).
+        if ctype in ("categorical", "bool", "int") and 2 <= n_u <= 30:
             score += 2
-        elif n_u > 100:
+        elif ctype not in ("int", "float") and n_u > 100:
             score -= 2
         if score > best_score:
             best_score, best = score, col
```

After this: `customer_segment_ar` scores +10, `total_revenue` scores +8 — categorical still nudges ahead by 2 in this dataset, and only because the keyword "revenue" isn't in TARGET_KEYWORDS.

#### Option B (more decisive) — add domain keywords for regression targets
On top of A, extend `TARGET_KEYWORDS` to include common continuous-target terms. They'd give the +10 keyword bonus to `total_revenue`, `price`, `cost`, etc.:

```diff
 TARGET_KEYWORDS = {
     "label", "target", "class", "category", "output", "result", "outcome",
     "status", "type", "grade", "verdict", "sentiment", "fraud", "churn",
     "risk", "diagnosis", "disease", "approved", "prediction",
+    # Common regression-target words
+    "price", "cost", "revenue", "amount", "value", "score", "rating",
+    "duration", "spend", "sales", "profit", "loss", "margin",
+    "السعر", "التكلفه", "التكلفة", "الايراد", "القيمه", "القيمة",
     "تصنيف", "فئة", "نتيجة", "هدف", "نوع", "حالة", "درجة",
 }
```

With both A + B applied, `total_revenue` would score `+10 (keyword) + 5 (float) + 3 (low-null) = +18`, vs `customer_segment_ar`'s +10 — clear winner.

#### Option C (structural) — return `(target, alternates)` and let the UI choose
Bigger change: have `_auto_detect` return a ranked list (top 2–3) and let the user pick in the preprocessor UI before the run. Avoids hardcoding our own heuristic preferences. Out of scope for a one-line fix — flagging only.

**My recommendation:** Apply **A + B together**. Option A alone leaves the result still decided by which TARGET_KEYWORDS happen to match. Option B teaches the system what regression targets typically look like in your domain (the dataset has Arabic columns, so I included Arabic equivalents). Option C is the right long-term answer but is a UX change, not a code-only fix.

---

## BUG #3 — `product_notes` (6% unique) misclassified as ID

### Why it happened — `_is_id_col`, line 87

```python
def _is_id_col(col_name: str, series: pd.Series) -> bool:
    cn = col_name.lower().replace(" ", "_")
    parts = set(cn.replace("-", "_").split("_"))
    if parts & ID_KEYWORDS or any(k in cn for k in ID_KEYWORDS):
        return True
    ...
```

For `product_notes`:
1. `cn = "product_notes"`
2. `parts = {"product", "notes"}`
3. `parts & ID_KEYWORDS` → `set()` (clean — neither "product" nor "notes" is an ID keyword)
4. **`any(k in cn for k in ID_KEYWORDS)`** — substring check — **matches `"no"` in `"notes"`** → returns `True`

The substring check is the bug. `ID_KEYWORDS` contains short tokens like `"no"`, `"id"`, `"key"`, `"code"`, `"num"`, `"ref"`. A substring search makes any of these match inside ordinary words:

| Innocent column name | Falsely matches |
|---|---|
| `product_**no**tes`     | `no`   |
| `mon**key**_data`       | `key`  |
| `en**code**d_features`  | `code` |
| `ig**no**re_flag`       | `no`   |
| `cus**id**ial_status`   | `id`   |
| `**ref**erral_count`    | `ref`  |

The 95% uniqueness rule (the docstring's stated criterion) was never reached for `product_notes` — uniqueness is 9/119 = 7.6%. The function returned `True` purely on the substring false-positive, and the audit even displays the rule's stated text correctly:

> ID if name pattern or uniqueness≥95%

…but the implementation's "name pattern" half is misimplemented as a substring search.

### Why the token-set check (`parts & ID_KEYWORDS`) was correct

The earlier line `parts = set(cn.replace("-", "_").split("_"))` already does the right thing — it splits the column name on underscores/hyphens and only matches whole tokens. `{"product", "notes"} & {"id", "no", "code", "key", ...}` is empty. The substring-OR clause undoes this safety.

### Proposed fix — drop the substring-OR, keep the token-set

```diff
--- a/basira-engine/basira_app.py
+++ b/basira-engine/basira_app.py
@@ -83,11 +83,16 @@ def _is_id_col(col_name: str, series: pd.Series) -> bool:
     """ID if name pattern matches OR uniqueness ratio ≥ 95% in object/int column."""
     cn = col_name.lower().replace(" ", "_")
-    parts = set(cn.replace("-", "_").split("_"))
-    if parts & ID_KEYWORDS or any(k in cn for k in ID_KEYWORDS):
-        return True
+    # Tokenize on _ and - so multi-word names match cleanly.
+    # We deliberately do NOT use substring matching: short keywords like
+    # "no", "id", "key", "code" trigger false positives inside ordinary words
+    # (e.g. product_notes, monkey_data, encoded_features).
+    parts = set(cn.replace("-", "_").split("_"))
+    if parts & ID_KEYWORDS:
+        return True
     non_null = series.dropna()
     n_total = len(non_null)
     if n_total > 20 and non_null.nunique() / n_total >= 0.95:
         if series.dtype == object or pd.api.types.is_integer_dtype(series):
             return True
     return False
```

### Expected outcome on the stress dataset

After this fix, `product_notes`:
- Hits neither name match (`{"product", "notes"} & ID_KEYWORDS = ∅`) nor uniqueness ≥ 95% (it's 7.6%).
- Will fall through to the categorical/text branch in `_detect_type` (likely **categorical** with 9 distinct values — exactly what it should be).
- Will no longer be silently dropped from the model under `Column Selection` ("ID columns excluded from model: ['transaction_id', 'product_notes']").

### Side check — what about legitimate ID-keyworded columns?

The remaining `parts & ID_KEYWORDS` token-set check still catches all of: `customer_id`, `user_uuid`, `account_no`, `phone_number`, `product_code`, `serial_key`, `record_pk`, `case_ref`, `معرف_العميل`, `رقم_الفاتورة`. So nothing legitimate is lost.

---

## Summary

| Bug | Severity | Root cause | Lines | Fix size |
|---|---|---|---|---|
| #1 | Critical  | Missing-token standardization is **absent**, not out-of-order  | new constant + new step at top of `preprocess()` | ~25 lines |
| #2 | High      | Categorical (+5) outweighs continuous numeric (+2); cardinality penalty hits regression targets | `basira_app.py:420–461`, optionally `48–53` (TARGET_KEYWORDS) | ~10 lines |
| #3 | Medium    | Substring-search over `ID_KEYWORDS` produces false positives on short tokens (`no`, `key`, `code`)| `basira_app.py:87` | 1 line removed |

All three fixes are local, do not change any threshold listed in CLAUDE.md as load-bearing, and do not alter engine boundaries. None are applied yet — awaiting your fix-by-fix approval.
