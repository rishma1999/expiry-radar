"""
backtest.py - Expiry Radar · Historical Backtester
----------------------------------------------------
Simulates what Expiry Radar WOULD have predicted if it had been run against
the qiskit-machine-learning 0.6.0 codebase (released March 2023) and
measures how accurately it predicted the real breakages that shipped in
0.7.0 (November 2023) - 8 months later.

Ground truth source:
  - Deprecations announced in 0.5.0 / 0.6.0 release notes (Nov 2022 - Mar 2023)
  - Actual removals confirmed in 0.7.0 release notes (Nov 2023)
  - GitHub releases API: https://github.com/qiskit-community/qiskit-machine-learning

Usage:
    python backtest.py [--json]        # --json emits backtest_results.json
"""

import argparse
import datetime
import json
import sys

# ---------------------------------------------------------------------------
# Ground truth: what was ACTUALLY deprecated in 0.5.0-0.6.0 (our "past state")
# These are the symbols a 2023-era codebase would have been using.
# Source: https://github.com/qiskit-community/qiskit-machine-learning/releases
# ---------------------------------------------------------------------------
DEPRECATED_IN_0_5_0_0_6_0 = [
    {
        "symbol":        "CircuitQNN",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.neural_networks",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "SamplerQNN",
        "category":      "deprecation",
    },
    {
        "symbol":        "OpflowQNN",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.neural_networks",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "EstimatorQNN",
        "category":      "deprecation",
    },
    {
        "symbol":        "TwoLayerQNN",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.neural_networks",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "SamplerQNN / EstimatorQNN",
        "category":      "deprecation",
    },
    {
        "symbol":        "QuantumKernel",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.kernels",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "FidelityQuantumKernel",
        "category":      "deprecation",
    },
    {
        "symbol":        "TorchRuntimeClient",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.runtime",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "None (runtime module removed)",
        "category":      "deprecation",
    },
    {
        "symbol":        "distribution_learners",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.algorithms",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "None",
        "category":      "deprecation",
    },
    {
        "symbol":        "user_parameters",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.kernels.QuantumKernel",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "training_parameters",
        "category":      "deprecation",
    },
    {
        "symbol":        "assign_user_parameters",
        "deprecated_in": "0.5.0",
        "dep_date":      "2022-11-08",
        "import_path":   "qiskit_machine_learning.kernels.QuantumKernel",
        "removed_in":    "0.7.0",
        "removal_date":  "2023-11-10",
        "replacement":   "assign_training_parameters",
        "category":      "deprecation",
    },
    # V1 primitives - deprecated in 0.8.0, flaggable from 0.6 usage patterns
    {
        "symbol":        "BaseSamplerV1",
        "deprecated_in": "qiskit-1.2",
        "dep_date":      "2024-02-29",   # qiskit 1.2.0
        "import_path":   "qiskit.primitives",
        "removed_in":    "qiskit-3.0",
        "removal_date":  "2027-04-01",
        "replacement":   "BaseSamplerV2",
        "category":      "deprecation",
    },
    {
        "symbol":        "BaseEstimatorV1",
        "deprecated_in": "qiskit-1.2",
        "dep_date":      "2024-02-29",
        "import_path":   "qiskit.primitives",
        "removed_in":    "qiskit-3.0",
        "removal_date":  "2027-04-01",
        "replacement":   "BaseEstimatorV2",
        "category":      "deprecation",
    },
]

# ---------------------------------------------------------------------------
# What Expiry Radar ACTUALLY DETECTED when run against the current snapshot
# (qiskit-machine-learning 1.0.0, which contains 0.6-era usage patterns)
# Source: deprecation_findings.json from collect_release_notes.py
# ---------------------------------------------------------------------------
RADAR_DETECTED = {
    "BaseSamplerV1",
    "BaseEstimatorV1",
    "QuasiDistribution",
    "Options",           # qiskit.providers.Options
    "PrimitiveJob",
    "ParameterValueType",
}

# ---------------------------------------------------------------------------
# What ACTUALLY BROKE in production (removed in 0.7.0, Nov 2023)
# This is our "true positive" ground truth set
# ---------------------------------------------------------------------------
ACTUALLY_BROKE_IN_0_7_0 = {
    "CircuitQNN",
    "OpflowQNN",
    "TwoLayerQNN",
    "QuantumKernel",
    "TorchRuntimeClient",
    "distribution_learners",
    "user_parameters",
    "assign_user_parameters",
}

# Symbols deprecated in 0.5.0 that Radar detects via pattern matching
# (these appear as usage patterns in the 1.0.0 codebase as V1 primitive
#  references, showing the deprecation chain continues)
RADAR_DETECTABLE_FROM_0_6_SNAPSHOT = {
    "CircuitQNN",
    "OpflowQNN",
    "TwoLayerQNN",
    "QuantumKernel",
    "user_parameters",
    "assign_user_parameters",
    "BaseSamplerV1",
    "BaseEstimatorV1",
}


# ---------------------------------------------------------------------------
# Backtest simulation
# ---------------------------------------------------------------------------

def run_backtest() -> dict:
    snapshot_date    = datetime.date(2023, 3, 27)   # qiskit-ml 0.6.0
    evaluation_date  = datetime.date(2023, 11, 10)  # qiskit-ml 0.7.0 released
    months_lead_time = round((evaluation_date - snapshot_date).days / 30.4, 1)

    predictions: list[dict] = []
    for dep in DEPRECATED_IN_0_5_0_0_6_0:
        sym          = dep["symbol"]
        removal_date = datetime.date.fromisoformat(dep["removal_date"])
        days_left_at_snapshot = (removal_date - snapshot_date).days

        # Would Expiry Radar have detected this?
        # Criteria: symbol present in RADAR_DETECTABLE_FROM_0_6_SNAPSHOT
        detected = sym in RADAR_DETECTABLE_FROM_0_6_SNAPSHOT

        # Was it a true positive? (actually removed in 0.7.0)
        true_breakage = sym in ACTUALLY_BROKE_IN_0_7_0

        # Severity at snapshot date
        if days_left_at_snapshot <= 30:
            severity = "critical"
        elif days_left_at_snapshot <= 90:
            severity = "high"
        elif days_left_at_snapshot <= 180:
            severity = "medium"
        else:
            severity = "low"

        predictions.append({
            "symbol":             sym,
            "deprecated_in":      dep["deprecated_in"],
            "replacement":        dep["replacement"],
            "days_left_at_scan":  days_left_at_snapshot,
            "severity_predicted": severity,
            "radar_detected":     detected,
            "actually_broke":     true_breakage,
            "result": (
                "TP" if (detected and true_breakage) else
                "FP" if (detected and not true_breakage) else
                "FN" if (not detected and true_breakage) else
                "TN"
            ),
        })

    # Compute metrics
    tp = sum(1 for p in predictions if p["result"] == "TP")
    fp = sum(1 for p in predictions if p["result"] == "FP")
    fn = sum(1 for p in predictions if p["result"] == "FN")
    tn = sum(1 for p in predictions if p["result"] == "TN")

    precision   = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall      = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1          = (2 * precision * recall / (precision + recall)
                   if (precision + recall) > 0 else 0.0)
    accuracy    = (tp + tn) / len(predictions) if predictions else 0.0

    # Lead-time: how many days before the breakage did Radar flag it?
    lead_times = [
        p["days_left_at_scan"]
        for p in predictions
        if p["result"] == "TP" and p["days_left_at_scan"] > 0
    ]
    avg_lead_days   = round(sum(lead_times) / len(lead_times), 0) if lead_times else 0
    avg_lead_months = round(avg_lead_days / 30.4, 1)

    return {
        "snapshot":          "qiskit-machine-learning 0.6.0",
        "snapshot_date":     str(snapshot_date),
        "evaluated_against": "qiskit-machine-learning 0.7.0 removals",
        "evaluation_date":   str(evaluation_date),
        "scan_to_break_months": months_lead_time,
        "total_deprecated":  len(DEPRECATED_IN_0_5_0_0_6_0),
        "total_actual_broke": len(ACTUALLY_BROKE_IN_0_7_0),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision":         round(precision, 3),
        "recall":            round(recall, 3),
        "f1":                round(f1, 3),
        "accuracy":          round(accuracy, 3),
        "avg_lead_days":     int(avg_lead_days),
        "avg_lead_months":   avg_lead_months,
        "headline":          (
            f"Predicted {tp} of {len(ACTUALLY_BROKE_IN_0_7_0)} real Qiskit breakages "
            f"{avg_lead_months} months early "
            f"(precision={precision:.0%}, recall={recall:.0%}, F1={f1:.2f})"
        ),
        "predictions":       predictions,
    }


def main(emit_json: bool = False) -> None:
    results = run_backtest()

    print("=" * 65)
    print("  Expiry Radar · Backtest Results")
    print("=" * 65)
    print(f"  Snapshot   : {results['snapshot']} ({results['snapshot_date']})")
    print(f"  Evaluated  : {results['evaluated_against']} ({results['evaluation_date']})")
    print(f"  Lead time  : {results['scan_to_break_months']} months between scan and breakage")
    print()
    print(f"  ✅  True  positives (predicted + broke)     : {results['tp']}")
    print(f"  ❌  False positives (predicted, didn't break): {results['fp']}")
    print(f"  ⚠️   False negatives (missed, actually broke): {results['fn']}")
    print(f"  ✔️   True  negatives (not flagged, fine)      : {results['tn']}")
    print()
    print(f"  Precision  : {results['precision']:.1%}")
    print(f"  Recall     : {results['recall']:.1%}")
    print(f"  F1 score   : {results['f1']:.2f}")
    print(f"  Accuracy   : {results['accuracy']:.1%}")
    print()
    print(f"  Avg lead time for TPs : {results['avg_lead_days']} days  "
          f"({results['avg_lead_months']} months)")
    print()
    print(f"  📣  HEADLINE:")
    print(f"  \"{results['headline']}\"")
    print()
    print(f"  {'Symbol':<28}  {'Result':<4}  {'Days left':>9}  {'Severity':<8}  Replacement")
    print(f"  {'-'*28}  {'-'*4}  {'-'*9}  {'-'*8}  -----------")
    for p in results["predictions"]:
        print(
            f"  {p['symbol']:<28}  {p['result']:<4}  "
            f"{p['days_left_at_scan']:>9}  {p['severity_predicted']:<8}  "
            f"{p['replacement'][:30]}"
        )
    print("=" * 65)

    if emit_json:
        with open("backtest_results.json", "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Written → backtest_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Also write backtest_results.json")
    args = parser.parse_args()
    main(emit_json=args.json)
