"""
BASIRA CHARTS ENGINE — PIPELINE-COMPATIBLE EDITION
====================================================
Chart recommendation system compatible with both the old Basira payload format
and the final Basira pipeline outputs from:
  - supervised_engine_F.py
  - unsupervised_engine_F.py
  - rca_engine_F.py
  - insight_engine_F.py

Key changes from previous version
-----------------------------------
1. normalize_feature_importance()  — accepts impact / impact_pct / importance
2. intelligent_chart_suggestions() — safe fallbacks, no crash on empty inputs,
                                     supports supervised + unsupervised modes
3. prepare_chart_data()            — recognises new data-source keys
4. get_color_scheme_config()       — unchanged (kept for backward compat)
5. New section builders:
   build_model_leaderboard_chart()
   build_confusion_matrix_chart()
   build_cluster_profile_chart()
   build_anomaly_chart()
   build_rca_chart()
   build_insight_cards_chart()
   build_actual_vs_predicted_chart()
   build_residuals_chart()
   build_class_distribution_chart()
   build_pca_scatter_chart()
"""

import math
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Feature-importance normalisation
# ---------------------------------------------------------------------------

def normalize_feature_importance(raw_list):
    """
    Accept feature importance in any of the three legacy/new formats and
    return a unified list where every entry has:
        feature, impact, impact_pct, importance
    All numeric values are plain Python floats (JSON-safe).

    Accepted input shapes
    ---------------------
    [{'feature': ..., 'impact': ...}]                   ← old format
    [{'feature': ..., 'impact_pct': ...}]               ← new supervised engine
    [{'feature': ..., 'importance': ...}]               ← sklearn raw
    Mixed / partially populated dicts are handled safely.
    """
    if not raw_list or not isinstance(raw_list, list):
        return []

    normalised = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue
        feature = str(entry.get('feature', entry.get('name', 'unknown')))

        # Resolve the numeric value from whichever key exists
        raw_val = (
            entry.get('impact_pct')
            or entry.get('impact')
            or entry.get('importance')
            or 0.0
        )
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            val = 0.0
        if math.isnan(val) or math.isinf(val):
            val = 0.0

        normalised.append({
            'feature':    feature,
            'impact':     round(val, 4),
            'impact_pct': round(val, 4),
            'importance': round(val, 4),
            'direction':  entry.get('direction', 'unknown'),
            'importance_level': entry.get('importance_level', ''),
        })

    return normalised


# ---------------------------------------------------------------------------
# Main chart suggestion entry point
# ---------------------------------------------------------------------------

def intelligent_chart_suggestions(
    df,
    numeric_df,
    feature_impact,
    target_col,
    task_type='classification',
    engine_chart_data=None,
    engine_chart_recommendations=None,
):
    """
    Generate 6-8 decision-oriented chart recommendations.

    Parameters
    ----------
    df                        : full DataFrame
    numeric_df                : numeric columns only
    feature_impact            : list of feature dicts (any accepted format)
    target_col                : target column name or None
    task_type                 : 'classification' | 'regression' | 'unsupervised'
    engine_chart_data         : chart_data dict from supervised/unsupervised engine (optional)
    engine_chart_recommendations : list from engine (optional) — preserved as-is if supplied

    Returns
    -------
    List of chart recommendation dicts (Chart.js friendly, JSON-safe)
    """

    # ── Normalise feature importance ──────────────────────────────────────
    feature_impact = normalize_feature_importance(feature_impact or [])

    # ── If the engine already produced chart recommendations, honour them ──
    # We enrich each entry to ensure required keys exist, then return.
    if engine_chart_recommendations and isinstance(engine_chart_recommendations, list):
        enriched = []
        for rec in engine_chart_recommendations:
            if not isinstance(rec, dict):
                continue
            rec.setdefault('editable', True)
            rec.setdefault('priority', 'medium')
            rec.setdefault('chartData', rec.get('data_source', 'impact'))
            rec.setdefault('data_source', rec.get('chartData', 'impact'))
            # If inline data is already in the rec, keep it
            if 'datasets' not in rec and feature_impact:
                _inject_impact_datasets(rec, feature_impact)
            enriched.append(rec)
        return enriched[:8]

    # ── Build from scratch ────────────────────────────────────────────────
    suggestions = []
    n_features  = len(feature_impact)
    n_samples   = max(len(df), 1) if df is not None else 1

    top2_impact  = sum(f['impact'] for f in feature_impact[:2])  if n_features >= 2 else 0
    impacts_list = [f['impact'] for f in feature_impact]
    impact_std   = float(np.std(impacts_list)) if impacts_list else 0
    is_balanced  = impact_std < 15

    # ── Chart 1: Feature Impact Ranking (always, if we have features) ─────
    if n_features >= 1:
        feats    = [f['feature'] for f in feature_impact]
        imp_vals = [f['impact']  for f in feature_impact]
        ctype    = 'horizontalBar' if n_features <= 10 else 'bar'
        suggestions.append({
            'id':          'impact_ranking',
            'type':        ctype,
            'title':       'Feature Impact Ranking',
            'reason':      f'{n_features} features — ranking shows decision hierarchy',
            'insight':     'Identifies which features have the strongest influence on model output.',
            'priority':    'critical',
            'chartData':   'impact',
            'data_source': 'impact',
            'labels':      feats,
            'datasets': [{
                'label':           'Impact %',
                'data':            imp_vals,
                'backgroundColor': [f'rgba(0, 212, 255, {max(0.3, 0.9 - i * 0.07)})' for i in range(len(feats))],
                'borderColor':     'rgba(0, 212, 255, 1)',
                'borderWidth':     2,
            }],
            'config': {
                'indexAxis':          'y' if ctype == 'horizontalBar' else 'x',
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': False}},
            },
            'editable': True,
        })

    # ── Chart 2: Decision Weight Allocation (doughnut) ────────────────────
    if top2_impact > 50 and n_features >= 4:
        feats    = [f['feature'] for f in feature_impact[:6]]
        imp_vals = [f['impact']  for f in feature_impact[:6]]
        suggestions.append({
            'id':          'weight_allocation',
            'type':        'doughnut',
            'title':       'Decision Weight Allocation',
            'reason':      f'Top 2 features control {top2_impact:.0f}% of signal',
            'insight':     'Shows Pareto concentration in the feature set.',
            'priority':    'high',
            'chartData':   'impact',
            'data_source': 'impact',
            'labels':      feats,
            'datasets': [{
                'label':           'Decision Weight',
                'data':            imp_vals,
                'backgroundColor': [
                    'rgba(0, 212, 255, 0.85)',
                    'rgba(139, 92, 246, 0.85)',
                    'rgba(99, 102, 241, 0.85)',
                    'rgba(245, 158, 11, 0.80)',
                    'rgba(34, 197, 94, 0.80)',
                    'rgba(139, 146, 181, 0.70)',
                ],
                'borderColor': '#0a0e27',
                'borderWidth':  2,
            }],
            'config': {
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': True, 'position': 'right'}},
            },
            'editable': True,
        })

    # ── Chart 3: Cumulative Decision Power ────────────────────────────────
    if n_features >= 4:
        feats      = [f['feature'] for f in feature_impact]
        cumulative = np.cumsum(impacts_list).tolist()
        suggestions.append({
            'id':          'cumulative_power',
            'type':        'line',
            'title':       'Cumulative Decision Power',
            'reason':      'Shows minimum feature set needed to reach 80% threshold',
            'insight':     'Guides resource allocation for feature monitoring.',
            'priority':    'high',
            'chartData':   'cumulative',
            'data_source': 'cumulative',
            'labels':      feats,
            'datasets': [
                {
                    'label':           'Cumulative Impact %',
                    'data':            cumulative,
                    'backgroundColor': 'rgba(0, 212, 255, 0.2)',
                    'borderColor':     'rgba(0, 212, 255, 1)',
                    'borderWidth':     3,
                    'fill':            True,
                    'tension':         0.4,
                },
                {
                    'label':           '80% Threshold',
                    'data':            [80] * len(feats),
                    'backgroundColor': 'transparent',
                    'borderColor':     'rgba(245, 158, 11, 0.8)',
                    'borderWidth':     2,
                    'borderDash':      [5, 5],
                    'pointRadius':     0,
                },
            ],
            'config': {
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': True}},
                'scales': {
                    'y': {
                        'min': 0,
                        'max': 100,
                        'title': {'display': True, 'text': 'Cumulative Impact %'},
                    }
                },
            },
            'editable': True,
        })

    # ── Chart 4: Impact Decay Curve ───────────────────────────────────────
    if n_features >= 5:
        feats    = [f['feature'] for f in feature_impact]
        imp_vals = [f['impact']  for f in feature_impact]
        suggestions.append({
            'id':          'decay_curve',
            'type':        'line',
            'title':       'Impact Decay Curve',
            'reason':      'Visualizes how decision power drops across features',
            'insight':     'Steep decay = top-heavy structure. Gradual = balanced distribution.',
            'priority':    'medium',
            'chartData':   'impact',
            'data_source': 'impact',
            'labels':      feats,
            'datasets': [{
                'label':                'Impact %',
                'data':                 imp_vals,
                'backgroundColor':      'rgba(139, 92, 246, 0.2)',
                'borderColor':          'rgba(139, 92, 246, 1)',
                'borderWidth':          3,
                'fill':                 True,
                'tension':              0.4,
                'pointRadius':          6,
                'pointBackgroundColor': 'rgba(139, 92, 246, 1)',
            }],
            'config': {
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': False}},
            },
            'editable': True,
        })

    # ── Chart 5: Multi-Driver Radar ───────────────────────────────────────
    if 4 <= n_features <= 12:
        feats    = [f['feature'] for f in feature_impact]
        imp_vals = [f['impact']  for f in feature_impact]
        suggestions.append({
            'id':          'decision_profile',
            'type':        'radar',
            'title':       'Multi-Driver Decision Profile',
            'reason':      f'{n_features} dimensions ideal for radar view',
            'insight':     'Reveals whether decisions are concentrated or balanced across features.',
            'priority':    'high',
            'chartData':   'impact',
            'data_source': 'impact',
            'labels':      feats,
            'datasets': [{
                'label':                'Feature Impact',
                'data':                 imp_vals,
                'backgroundColor':      'rgba(0, 212, 255, 0.3)',
                'borderColor':          'rgba(0, 212, 255, 1)',
                'borderWidth':          2,
                'pointBackgroundColor': 'rgba(0, 212, 255, 1)',
                'pointBorderColor':     '#fff',
                'pointRadius':          5,
            }],
            'config': {
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': False}},
                'scales': {'r': {'min': 0, 'beginAtZero': True}},
            },
            'editable': True,
        })

    # ── Chart 6: Top Driver Interaction (scatter) ─────────────────────────
    if (n_samples >= 50 and n_features >= 2
            and numeric_df is not None
            and target_col and target_col in numeric_df.columns):
        feat1 = feature_impact[0]['feature']
        feat2 = feature_impact[1]['feature']
        if feat1 in numeric_df.columns and feat2 in numeric_df.columns:
            sample_size = min(100, n_samples)
            indices     = np.random.choice(n_samples, sample_size, replace=False)
            x_vals      = numeric_df[feat1].iloc[indices].values
            y_vals      = numeric_df[feat2].iloc[indices].values
            scatter_pts = [
                {'x': float(x), 'y': float(y)}
                for x, y in zip(x_vals, y_vals)
                if math.isfinite(float(x)) and math.isfinite(float(y))
            ]
            suggestions.append({
                'id':          'top_interaction',
                'type':        'scatter',
                'title':       'Top Driver Interaction',
                'reason':      f'{n_samples} samples — relationship between top 2 drivers',
                'insight':     f'Shows how {feat1} and {feat2} relate.',
                'priority':    'medium',
                'chartData':   'scatter',
                'data_source': 'scatter',
                'feat1':       feat1,
                'feat2':       feat2,
                'labels':      [f'{feat1} vs {feat2}'],
                'datasets': [{
                    'label':           f'{feat1} vs {feat2}',
                    'data':            scatter_pts,
                    'backgroundColor': 'rgba(99, 102, 241, 0.6)',
                    'borderColor':     'rgba(99, 102, 241, 1)',
                    'borderWidth':     1,
                    'pointRadius':     5,
                }],
                'config': {
                    'responsive':         True,
                    'maintainAspectRatio': False,
                    'plugins': {'legend': {'display': False}},
                    'scales': {
                        'x': {'title': {'display': True, 'text': feat1}},
                        'y': {'title': {'display': True, 'text': feat2}},
                    },
                },
                'editable': True,
            })

    # ── Chart 7: Balanced Feature Landscape (polarArea) ───────────────────
    if is_balanced and n_features >= 5:
        feats    = [f['feature'] for f in feature_impact]
        imp_vals = [f['impact']  for f in feature_impact]
        PALETTE  = [
            'rgba(0, 212, 255, 0.7)', 'rgba(139, 92, 246, 0.7)',
            'rgba(99, 102, 241, 0.7)', 'rgba(245, 158, 11, 0.7)',
            'rgba(34, 197, 94, 0.7)',  'rgba(139, 146, 181, 0.7)',
            'rgba(251, 146, 60, 0.7)', 'rgba(168, 85, 247, 0.7)',
        ]
        suggestions.append({
            'id':          'balanced_distribution',
            'type':        'polarArea',
            'title':       'Balanced Feature Landscape',
            'reason':      'Balanced distribution detected — polar view shows 360° landscape',
            'insight':     'No single feature dominates. Decisions are collaborative.',
            'priority':    'medium',
            'chartData':   'impact',
            'data_source': 'impact',
            'labels':      feats,
            'datasets': [{
                'label':           'Feature Impact',
                'data':            imp_vals,
                'backgroundColor': [PALETTE[i % len(PALETTE)] for i in range(len(feats))],
                'borderColor':     '#0a0e27',
                'borderWidth':     2,
            }],
            'config': {
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': True, 'position': 'right'}},
            },
            'editable': True,
        })

    # ── Chart 8: Lever Comparison (bar) ───────────────────────────────────
    if 5 <= n_features <= 10:
        feats    = [f['feature'] for f in feature_impact]
        imp_vals = [f['impact']  for f in feature_impact]
        suggestions.append({
            'id':          'lever_comparison',
            'type':        'bar',
            'title':       'Decision Lever Comparison',
            'reason':      f'{n_features} features — direct magnitude comparison',
            'insight':     'Supports prioritization of monitoring and intervention strategies.',
            'priority':    'low',
            'chartData':   'impact',
            'data_source': 'impact',
            'labels':      feats,
            'datasets': [{
                'label':           'Impact %',
                'data':            imp_vals,
                'backgroundColor': 'rgba(34, 197, 94, 0.7)',
                'borderColor':     'rgba(34, 197, 94, 1)',
                'borderWidth':     2,
            }],
            'config': {
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': False}},
            },
            'editable': True,
        })

    # ── Sort and return ───────────────────────────────────────────────────
    priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    suggestions.sort(key=lambda x: priority_order.get(x.get('priority', 'low'), 99))
    return suggestions[:8]


# ---------------------------------------------------------------------------
# Specialised section builders (new — called by the bridge/orchestrator)
# ---------------------------------------------------------------------------

def build_model_leaderboard_chart(cv_results):
    """
    Build a horizontal bar chart from the model leaderboard.

    Parameters
    ----------
    cv_results : list of dicts with 'model_name' and 'main_score' (from supervised engine)

    Returns
    -------
    dict — chart recommendation ready for Chart.js
    """
    if not cv_results or not isinstance(cv_results, list):
        return None

    valid = [r for r in cv_results if isinstance(r, dict) and r.get('status') == 'success']
    if not valid:
        return None

    labels = [r.get('model_name', 'Unknown') for r in valid]
    scores = []
    for r in valid:
        s = r.get('main_score') or r.get('cv_metrics', {}).get('f1_macro', 0)
        try:
            scores.append(round(float(s) * 100, 2))
        except (TypeError, ValueError):
            scores.append(0.0)

    return {
        'id':          'model_leaderboard',
        'type':        'horizontalBar',
        'title':       'Model Leaderboard',
        'reason':      f'{len(labels)} models compared by validation score',
        'insight':     'Shows which algorithm achieved the best cross-validated performance.',
        'priority':    'critical',
        'chartData':   'leaderboard',
        'data_source': 'leaderboard',
        'labels':      labels,
        'datasets': [{
            'label':           'Score (%)',
            'data':            scores,
            'backgroundColor': [
                'rgba(0, 212, 255, 0.9)' if i == 0 else 'rgba(139, 92, 246, 0.7)'
                for i in range(len(labels))
            ],
            'borderColor':     'rgba(0, 212, 255, 1)',
            'borderWidth':     2,
        }],
        'config': {
            'indexAxis':          'y',
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': False}},
            'scales': {
                'x': {'min': 0, 'max': 100, 'title': {'display': True, 'text': 'Score %'}},
            },
        },
        'editable': True,
    }


def build_confusion_matrix_chart(conf_mat, label_classes):
    """
    Represent confusion matrix counts as a grouped bar chart.
    A true heatmap is not natively supported in Chart.js 4 without plugins,
    so we use per-actual-class bars.

    Parameters
    ----------
    conf_mat      : list[list[int]]
    label_classes : list[str]

    Returns
    -------
    dict or None
    """
    if not conf_mat or not label_classes:
        return None
    try:
        arr      = [[int(v) for v in row] for row in conf_mat]
        n        = len(arr)
        classes  = [str(c) for c in label_classes[:n]]
        PALETTE  = [
            'rgba(0, 212, 255, 0.75)',  'rgba(139, 92, 246, 0.75)',
            'rgba(34, 197, 94, 0.75)',  'rgba(245, 158, 11, 0.75)',
            'rgba(255, 51, 102, 0.75)', 'rgba(99, 102, 241, 0.75)',
        ]
        datasets = []
        for j, pred_cls in enumerate(classes):
            datasets.append({
                'label':           f'Pred: {pred_cls}',
                'data':            [arr[i][j] if j < len(arr[i]) else 0 for i in range(n)],
                'backgroundColor': PALETTE[j % len(PALETTE)],
                'borderWidth':     1,
            })
        return {
            'id':          'confusion_matrix',
            'type':        'bar',
            'title':       'Confusion Matrix',
            'reason':      'Shows how classes are predicted vs actual',
            'insight':     'Tall off-diagonal bars indicate class confusion pairs.',
            'priority':    'high',
            'chartData':   'confusion',
            'data_source': 'confusion',
            'labels':      [f'Actual: {c}' for c in classes],
            'datasets':    datasets,
            'config': {
                'responsive':         True,
                'maintainAspectRatio': False,
                'plugins': {'legend': {'display': True}},
                'scales': {
                    'x': {'stacked': False, 'ticks': {'color': '#8b92b5'}},
                    'y': {'stacked': False, 'ticks': {'color': '#8b92b5'},
                          'title': {'display': True, 'text': 'Count'}},
                },
            },
            'editable': True,
        }
    except Exception:
        return None


def build_actual_vs_predicted_chart(error_cases, target_col='target'):
    """
    Build a scatter chart of actual vs predicted for regression tasks.

    Parameters
    ----------
    error_cases : list of dicts with 'actual' and 'predicted' keys
    target_col  : str, for axis labelling
    """
    if not error_cases or not isinstance(error_cases, list):
        return None
    pts = []
    for c in error_cases[:200]:
        try:
            x = float(c.get('actual', 0))
            y = float(c.get('predicted', 0))
            if math.isfinite(x) and math.isfinite(y):
                pts.append({'x': x, 'y': y})
        except (TypeError, ValueError):
            continue
    if not pts:
        return None

    vals     = [p['x'] for p in pts]
    min_v    = min(vals)
    max_v    = max(vals)
    diag_pts = [{'x': min_v, 'y': min_v}, {'x': max_v, 'y': max_v}]

    return {
        'id':          'actual_vs_predicted',
        'type':        'scatter',
        'title':       'Actual vs Predicted',
        'reason':      'Evaluates regression accuracy point-by-point',
        'insight':     'Points near the diagonal indicate accurate predictions.',
        'priority':    'high',
        'chartData':   'scatter',
        'data_source': 'scatter',
        'labels':      [target_col],
        'datasets': [
            {
                'label':           'Predictions',
                'data':            pts,
                'backgroundColor': 'rgba(0, 212, 255, 0.6)',
                'borderColor':     'rgba(0, 212, 255, 1)',
                'borderWidth':     1,
                'pointRadius':     4,
            },
            {
                'label':      'Perfect Fit',
                'data':       diag_pts,
                'type':       'line',
                'borderColor': 'rgba(255, 51, 102, 0.8)',
                'borderWidth':  2,
                'borderDash':   [6, 4],
                'pointRadius':  0,
                'fill':         False,
            },
        ],
        'config': {
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': True}},
            'scales': {
                'x': {'title': {'display': True, 'text': 'Actual'}},
                'y': {'title': {'display': True, 'text': 'Predicted'}},
            },
        },
        'editable': True,
    }


def build_residuals_chart(error_cases):
    """
    Build a bar/line chart of residuals (predicted − actual).

    Parameters
    ----------
    error_cases : list of dicts with 'residual' or ('actual','predicted') keys
    """
    if not error_cases or not isinstance(error_cases, list):
        return None
    residuals = []
    for c in error_cases[:150]:
        try:
            r = c.get('residual')
            if r is None:
                r = float(c.get('predicted', 0)) - float(c.get('actual', 0))
            residuals.append(round(float(r), 4))
        except (TypeError, ValueError):
            continue
    if not residuals:
        return None

    return {
        'id':          'residuals',
        'type':        'bar',
        'title':       'Prediction Residuals',
        'reason':      'Identifies systematic over/under-prediction patterns',
        'insight':     'Residuals near zero = good fit. Skew indicates systematic bias.',
        'priority':    'high',
        'chartData':   'residuals',
        'data_source': 'residuals',
        'labels':      [str(i) for i in range(len(residuals))],
        'datasets': [{
            'label':           'Residual',
            'data':            residuals,
            'backgroundColor': [
                'rgba(255, 51, 102, 0.7)' if r < 0 else 'rgba(34, 197, 94, 0.7)'
                for r in residuals
            ],
            'borderColor':     'rgba(139, 146, 181, 0.3)',
            'borderWidth':     1,
        }],
        'config': {
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': False}},
            'scales': {
                'x': {'display': False},
                'y': {'title': {'display': True, 'text': 'Residual'}},
            },
        },
        'editable': True,
    }


def build_class_distribution_chart(target_summary):
    """
    Build a doughnut chart from classification target distribution.

    Parameters
    ----------
    target_summary : dict with 'class_distribution' key (from supervised engine)
    """
    if not target_summary or not isinstance(target_summary, dict):
        return None
    dist = target_summary.get('class_distribution', {})
    if not dist:
        return None
    labels = [str(k) for k in dist.keys()]
    values = []
    for v in dist.values():
        try:
            values.append(int(v))
        except (TypeError, ValueError):
            values.append(0)
    PALETTE = [
        'rgba(0, 212, 255, 0.85)', 'rgba(139, 92, 246, 0.85)',
        'rgba(34, 197, 94, 0.85)', 'rgba(245, 158, 11, 0.85)',
        'rgba(255, 51, 102, 0.85)', 'rgba(99, 102, 241, 0.85)',
    ]
    return {
        'id':          'class_distribution',
        'type':        'doughnut',
        'title':       'Class Distribution',
        'reason':      'Shows label balance in the test set',
        'insight':     'Large imbalance between slices signals class weighting may be needed.',
        'priority':    'high',
        'chartData':   'class_dist',
        'data_source': 'class_dist',
        'labels':      labels,
        'datasets': [{
            'label':           'Count',
            'data':            values,
            'backgroundColor': [PALETTE[i % len(PALETTE)] for i in range(len(labels))],
            'borderColor':     '#0a0e27',
            'borderWidth':     2,
        }],
        'config': {
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': True, 'position': 'right'}},
        },
        'editable': True,
    }


def build_cluster_profile_chart(cluster_profiles):
    """
    Build a horizontal bar chart of cluster sizes.

    Parameters
    ----------
    cluster_profiles : list of dicts with 'cluster_id', 'label', 'size_pct'
    """
    if not cluster_profiles or not isinstance(cluster_profiles, list):
        return None
    labels = []
    sizes  = []
    for p in cluster_profiles:
        if not isinstance(p, dict):
            continue
        labels.append(str(p.get('label', f"Cluster {p.get('cluster_id', '?')}")))
        try:
            sizes.append(round(float(p.get('size_pct', 0)), 2))
        except (TypeError, ValueError):
            sizes.append(0.0)
    if not labels:
        return None
    PALETTE = [
        'rgba(0, 212, 255, 0.80)', 'rgba(139, 92, 246, 0.80)',
        'rgba(34, 197, 94, 0.80)', 'rgba(245, 158, 11, 0.80)',
        'rgba(255, 51, 102, 0.80)', 'rgba(99, 102, 241, 0.80)',
        'rgba(251, 146, 60, 0.80)', 'rgba(168, 85, 247, 0.80)',
    ]
    return {
        'id':          'cluster_sizes',
        'type':        'horizontalBar',
        'title':       'Cluster Size Distribution',
        'reason':      'Shows population share of each discovered cluster',
        'insight':     'Very small clusters may represent anomalies or rare segments.',
        'priority':    'critical',
        'chartData':   'cluster_sizes',
        'data_source': 'cluster_sizes',
        'labels':      labels,
        'datasets': [{
            'label':           'Share (%)',
            'data':            sizes,
            'backgroundColor': [PALETTE[i % len(PALETTE)] for i in range(len(labels))],
            'borderColor':     'rgba(0, 212, 255, 0.3)',
            'borderWidth':     1,
        }],
        'config': {
            'indexAxis':          'y',
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': False}},
            'scales': {
                'x': {'min': 0, 'max': 100, 'title': {'display': True, 'text': 'Population %'}},
            },
        },
        'editable': True,
    }


def build_anomaly_chart(anomaly_report):
    """
    Build a bar chart showing top anomaly records by score.

    Parameters
    ----------
    anomaly_report : dict from unsupervised engine with 'top_anomalies' list
    """
    if not anomaly_report or not isinstance(anomaly_report, dict):
        return None
    top = anomaly_report.get('top_anomalies', [])
    if not top:
        return None
    labels = []
    scores = []
    for a in top[:20]:
        if not isinstance(a, dict):
            continue
        labels.append(f"Row {a.get('source_row_index', a.get('row_position', '?'))}")
        try:
            scores.append(round(float(a.get('anomaly_score', 0)), 4))
        except (TypeError, ValueError):
            scores.append(0.0)
    if not labels:
        return None
    return {
        'id':          'anomaly_scores',
        'type':        'bar',
        'title':       'Top Anomaly Records',
        'reason':      'Highlights records with the highest anomaly scores',
        'insight':     'High anomaly score = significant deviation from cluster norms.',
        'priority':    'high',
        'chartData':   'anomaly',
        'data_source': 'anomaly',
        'labels':      labels,
        'datasets': [{
            'label':           'Anomaly Score',
            'data':            scores,
            'backgroundColor': 'rgba(255, 51, 102, 0.75)',
            'borderColor':     'rgba(255, 51, 102, 1)',
            'borderWidth':     2,
        }],
        'config': {
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': False}},
            'scales': {
                'y': {'min': 0, 'title': {'display': True, 'text': 'Score'}},
            },
        },
        'editable': True,
    }


def build_pca_scatter_chart(pca_coords, labels, n_clusters=None):
    """
    Build a scatter chart from PCA 2D coordinates coloured by cluster.

    Parameters
    ----------
    pca_coords : list of [x, y] or {'x': ..., 'y': ...}
    labels     : list of int cluster labels (same length as pca_coords)
    n_clusters : int or None
    """
    if not pca_coords or not labels:
        return None
    PALETTE = [
        'rgba(0, 212, 255, 0.7)',   'rgba(139, 92, 246, 0.7)',
        'rgba(34, 197, 94, 0.7)',   'rgba(245, 158, 11, 0.7)',
        'rgba(255, 51, 102, 0.7)',  'rgba(99, 102, 241, 0.7)',
        'rgba(251, 146, 60, 0.7)',  'rgba(168, 85, 247, 0.7)',
    ]
    cluster_ids = sorted(set(int(l) for l in labels if l != -1))
    datasets    = []
    for cid in cluster_ids:
        pts = []
        for i, coord in enumerate(pca_coords):
            if int(labels[i]) != cid:
                continue
            try:
                if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                    x, y = float(coord[0]), float(coord[1])
                else:
                    x, y = float(coord['x']), float(coord['y'])
                if math.isfinite(x) and math.isfinite(y):
                    pts.append({'x': x, 'y': y})
            except (TypeError, KeyError, IndexError, ValueError):
                continue
        datasets.append({
            'label':           f'Cluster {cid}',
            'data':            pts,
            'backgroundColor': PALETTE[cid % len(PALETTE)],
            'borderColor':     PALETTE[cid % len(PALETTE)].replace('0.7', '1'),
            'borderWidth':     1,
            'pointRadius':     4,
        })
    if not datasets:
        return None
    return {
        'id':          'pca_scatter',
        'type':        'scatter',
        'title':       'PCA Cluster Scatter',
        'reason':      'Reduced-dimension view of cluster structure',
        'insight':     'Tight, well-separated clouds indicate clean cluster boundaries.',
        'priority':    'high',
        'chartData':   'pca_scatter',
        'data_source': 'pca_scatter',
        'labels':      [f'Cluster {cid}' for cid in cluster_ids],
        'datasets':    datasets,
        'config': {
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': True}},
            'scales': {
                'x': {'title': {'display': True, 'text': 'PC1'}},
                'y': {'title': {'display': True, 'text': 'PC2'}},
            },
        },
        'editable': True,
    }


def build_rca_chart(findings):
    """
    Build a horizontal bar chart from RCA findings ranked by severity count.

    Parameters
    ----------
    findings : list of RCAFinding dicts (from rca_engine_F.py)
    """
    if not findings or not isinstance(findings, list):
        return None
    from collections import Counter
    sev_counts = Counter()
    for f in findings:
        if isinstance(f, dict):
            sev_counts[f.get('severity', 'info')] += 1
    order  = ['critical', 'high', 'medium', 'low', 'info']
    labels = [s.capitalize() for s in order if sev_counts.get(s, 0) > 0]
    values = [sev_counts[s] for s in order if sev_counts.get(s, 0) > 0]
    colours = {
        'critical': 'rgba(255, 51, 102, 0.85)',
        'high':     'rgba(245, 158, 11, 0.85)',
        'medium':   'rgba(99, 102, 241, 0.85)',
        'low':      'rgba(34, 197, 94, 0.85)',
        'info':     'rgba(139, 146, 181, 0.70)',
    }
    bg = [colours.get(s, 'rgba(139, 146, 181, 0.70)') for s in order if sev_counts.get(s, 0) > 0]
    return {
        'id':          'rca_severity_summary',
        'type':        'bar',
        'title':       'RCA Finding Severity Summary',
        'reason':      f'{len(findings)} root-cause findings classified by severity',
        'insight':     'Critical and high findings require immediate attention.',
        'priority':    'critical',
        'chartData':   'rca_summary',
        'data_source': 'rca_summary',
        'labels':      labels,
        'datasets': [{
            'label':           'Finding Count',
            'data':            values,
            'backgroundColor': bg,
            'borderColor':     'rgba(139, 146, 181, 0.3)',
            'borderWidth':     1,
        }],
        'config': {
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': False}},
            'scales': {
                'y': {
                    'beginAtZero': True,
                    'ticks': {'stepSize': 1},
                    'title': {'display': True, 'text': 'Count'},
                },
            },
        },
        'editable': True,
    }


def build_insight_cards_chart(insights):
    """
    Build a doughnut chart showing insight layer distribution.

    Parameters
    ----------
    insights : list of Insight dicts (from insight_engine_F.py)
    """
    if not insights or not isinstance(insights, list):
        return None
    from collections import Counter
    layer_counts = Counter()
    for ins in insights:
        if isinstance(ins, dict):
            layer_counts[ins.get('layer', 'other')] += 1
    if not layer_counts:
        return None
    labels = list(layer_counts.keys())
    values = list(layer_counts.values())
    PALETTE = [
        'rgba(0, 212, 255, 0.85)', 'rgba(139, 92, 246, 0.85)',
        'rgba(34, 197, 94, 0.85)', 'rgba(245, 158, 11, 0.85)',
        'rgba(255, 51, 102, 0.85)', 'rgba(99, 102, 241, 0.85)',
        'rgba(251, 146, 60, 0.85)', 'rgba(168, 85, 247, 0.85)',
    ]
    return {
        'id':          'insight_layer_distribution',
        'type':        'doughnut',
        'title':       'Insight Layer Distribution',
        'reason':      f'{len(insights)} insights across {len(layer_counts)} analytical layers',
        'insight':     'Shows which analytical dimensions generated the most evidence.',
        'priority':    'medium',
        'chartData':   'insight_dist',
        'data_source': 'insight_dist',
        'labels':      [l.capitalize() for l in labels],
        'datasets': [{
            'label':           'Insights',
            'data':            values,
            'backgroundColor': [PALETTE[i % len(PALETTE)] for i in range(len(labels))],
            'borderColor':     '#0a0e27',
            'borderWidth':     2,
        }],
        'config': {
            'responsive':         True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': True, 'position': 'right'}},
        },
        'editable': True,
    }


# ---------------------------------------------------------------------------
# prepare_chart_data — extended for new source keys
# ---------------------------------------------------------------------------

def prepare_chart_data(data_source, feature_impact, numeric_df, target_col):
    """
    Prepare data for specific chart types.

    Accepted data_source values
    ---------------------------
    'impact'       — feature importance bars
    'cumulative'   — cumulative impact line
    'correlation'  — correlation with target
    'scatter'      — scatter of top 2 features
    'leaderboard'  — model leaderboard (requires pre-built rec)
    'confusion'    — confusion matrix  (requires pre-built rec)
    'cluster_sizes'— cluster size bars (requires pre-built rec)
    'anomaly'      — anomaly scores    (requires pre-built rec)
    'pca_scatter'  — PCA scatter       (requires pre-built rec)
    'rca_summary'  — RCA severity bars (requires pre-built rec)
    'insight_dist' — insight layer dist(requires pre-built rec)

    For the 'requires pre-built' sources the caller should use the
    corresponding build_*_chart() helper above, not this function.
    Returns {'labels': [], 'datasets': []} as safe fallback.
    """
    feature_impact = normalize_feature_importance(feature_impact or [])

    if data_source == 'impact' and feature_impact:
        feats    = [f['feature'] for f in feature_impact]
        imp_vals = [f['impact']  for f in feature_impact]
        return {
            'labels': feats,
            'datasets': [{
                'label':           'Impact %',
                'data':            imp_vals,
                'backgroundColor': [f'rgba(0, 212, 255, {max(0.3, 0.9 - i * 0.08)})' for i in range(len(feats))],
                'borderColor':     'rgba(0, 212, 255, 1)',
                'borderWidth':     2,
            }],
        }

    if data_source == 'cumulative' and feature_impact:
        feats      = [f['feature'] for f in feature_impact]
        imp_vals   = [f['impact']  for f in feature_impact]
        cumulative = np.cumsum(imp_vals).tolist()
        return {
            'labels': feats,
            'datasets': [{
                'label':           'Cumulative Impact %',
                'data':            cumulative,
                'backgroundColor': 'rgba(0, 212, 255, 0.2)',
                'borderColor':     'rgba(0, 212, 255, 1)',
                'borderWidth':     3,
                'fill':            True,
            }],
        }

    if data_source == 'correlation' and numeric_df is not None and target_col and target_col in numeric_df.columns:
        correlations = numeric_df.corr()[target_col].abs().drop(labels=[target_col], errors='ignore')
        top_corr     = correlations.nlargest(10)
        return {
            'labels': top_corr.index.tolist(),
            'datasets': [{
                'label':           'Correlation',
                'data':            [round(float(v), 4) for v in top_corr.values],
                'backgroundColor': 'rgba(139, 92, 246, 0.7)',
                'borderColor':     'rgba(139, 92, 246, 1)',
                'borderWidth':     2,
            }],
        }

    if data_source == 'scatter' and len(feature_impact) >= 2 and numeric_df is not None:
        feat1 = feature_impact[0]['feature']
        feat2 = feature_impact[1]['feature']
        if feat1 in numeric_df.columns and feat2 in numeric_df.columns:
            x_vals = numeric_df[feat1].values[:100]
            y_vals = numeric_df[feat2].values[:100]
            scatter_data = [
                {'x': float(x), 'y': float(y)}
                for x, y in zip(x_vals, y_vals)
                if math.isfinite(float(x)) and math.isfinite(float(y))
            ]
            return {
                'datasets': [{
                    'label':           f'{feat1} vs {feat2}',
                    'data':            scatter_data,
                    'backgroundColor': 'rgba(99, 102, 241, 0.6)',
                    'borderColor':     'rgba(99, 102, 241, 1)',
                    'borderWidth':     1,
                }],
            }

    # Safe fallback — no crash
    return {'labels': [], 'datasets': []}


# ---------------------------------------------------------------------------
# get_color_scheme_config — unchanged for backward compatibility
# ---------------------------------------------------------------------------

def get_color_scheme_config(scheme_name):
    """
    Return backgroundColor / borderColor arrays for the given scheme.
    Kept identical to the previous version for backward compatibility.
    """
    schemes = {
        'basira_cyan': {
            'backgroundColor': ['rgba(0, 212, 255, 0.7)', 'rgba(0, 212, 255, 0.6)', 'rgba(0, 212, 255, 0.5)'],
            'borderColor':     ['rgba(0, 212, 255, 1)',   'rgba(0, 212, 255, 1)',    'rgba(0, 212, 255, 1)'],
        },
        'basira_purple': {
            'backgroundColor': ['rgba(139, 92, 246, 0.7)', 'rgba(139, 92, 246, 0.6)', 'rgba(139, 92, 246, 0.5)'],
            'borderColor':     ['rgba(139, 92, 246, 1)',   'rgba(139, 92, 246, 1)',    'rgba(139, 92, 246, 1)'],
        },
        'gradient': {
            'backgroundColor': [
                'rgba(0, 212, 255, 0.7)',  'rgba(139, 92, 246, 0.7)',
                'rgba(99, 102, 241, 0.7)', 'rgba(0, 255, 136, 0.7)',
                'rgba(245, 158, 11, 0.7)', 'rgba(34, 197, 94, 0.7)',
            ],
            'borderColor': [
                'rgba(0, 212, 255, 1)',  'rgba(139, 92, 246, 1)',
                'rgba(99, 102, 241, 1)', 'rgba(0, 255, 136, 1)',
                'rgba(245, 158, 11, 1)', 'rgba(34, 197, 94, 1)',
            ],
        },
        'success': {
            'backgroundColor': ['rgba(34, 197, 94, 0.7)', 'rgba(34, 197, 94, 0.6)', 'rgba(34, 197, 94, 0.5)'],
            'borderColor':     ['rgba(34, 197, 94, 1)',   'rgba(34, 197, 94, 1)',    'rgba(34, 197, 94, 1)'],
        },
        'warning': {
            'backgroundColor': ['rgba(245, 158, 11, 0.7)', 'rgba(245, 158, 11, 0.6)', 'rgba(245, 158, 11, 0.5)'],
            'borderColor':     ['rgba(245, 158, 11, 1)',   'rgba(245, 158, 11, 1)',    'rgba(245, 158, 11, 1)'],
        },
    }
    return schemes.get(scheme_name, schemes['basira_cyan'])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _inject_impact_datasets(rec, feature_impact):
    """Populate missing datasets field on a recommendation dict in-place."""
    feats    = [f['feature'] for f in feature_impact]
    imp_vals = [f['impact']  for f in feature_impact]
    rec['labels']   = feats
    rec['datasets'] = [{
        'label':           'Impact %',
        'data':            imp_vals,
        'backgroundColor': [f'rgba(0, 212, 255, {max(0.3, 0.9 - i * 0.08)})' for i in range(len(feats))],
        'borderColor':     'rgba(0, 212, 255, 1)',
        'borderWidth':     2,
    }]
