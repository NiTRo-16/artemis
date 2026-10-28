"""Train and evaluate the URL model: a LightGBM classifier on hostname features (ml/url_features.py).

    python ml/train_url_model.py

Training data: the PhiUSIIL Phishing URL dataset (Prasad and Chandra, 2024; CC BY 4.0), downloaded to
ml/data/phiusiil/. Fresh test data: evaluation/data/dataset.jsonl from the server (OpenPhish and Tranco,
2026), copied to ml/data/artemis/dataset.jsonl. The model never trains on it, so it shows how the model
does on today's phishing rather than the dataset's.

Writes ml/models/url_model.txt (the model), url_model.json (threshold and feature names) and
url_model_report.md (the evaluation).
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from impersonation import registrable_domain  # noqa: E402
from ml.url_features import FREE_HOSTS, NAMES, features, hostname  # noqa: E402

PHIUSIIL = ROOT / "ml" / "data" / "phiusiil" / "PhiUSIIL_Phishing_URL_Dataset.csv"
FRESH = ROOT / "ml" / "data" / "artemis" / "dataset.jsonl"
CACHE = ROOT / "ml" / "data" / "phiusiil" / "features.npz"
MODELS = ROOT / "ml" / "models"
MAX_FALSE_ALARMS = 0.01   # the threshold flags at most 1% of genuine sites in validation
SEED = 7


def group_of(host: str) -> str:
    """Hosts with one owner share a group, so the same site can't be in both training and test data.
    On free hosting every subdomain has a different owner, so each is its own group."""
    return host if any(host.endswith("." + f) for f in FREE_HOSTS) else registrable_domain(host)


def load_phiusiil() -> tuple[list[str], np.ndarray]:
    labels: dict[str, set[int]] = {}
    with PHIUSIIL.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            host = hostname(row["URL"])
            if host:
                labels.setdefault(host, set()).add(0 if row["label"] == "1" else 1)   # 1 = phishing here
    hosts = sorted(h for h, ls in labels.items() if len(ls) == 1)   # drop hosts labelled both ways
    return hosts, np.array([labels[h].pop() for h in hosts])


def featurise(hosts: list[str]) -> np.ndarray:
    with Pool() as pool:
        return np.array(pool.map(features, hosts, chunksize=2000), dtype=np.float32)


def wilson(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    p, z = k / n, 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{100 * p:.1f}% ({100 * max(0, centre - half):.1f} to {100 * min(1, centre + half):.1f})"


def rates(y: np.ndarray, flagged: np.ndarray) -> dict:
    caught, phish = int((flagged & (y == 1)).sum()), int((y == 1).sum())
    alarms, genuine = int((flagged & (y == 0)).sum()), int((y == 0).sum())
    return {"detection": wilson(caught, phish), "false_alarms": wilson(alarms, genuine),
            "counts": f"{caught}/{phish} phishing caught, {alarms}/{genuine} genuine flagged"}


def main() -> None:
    if not PHIUSIIL.exists():
        sys.exit(f"Download the PhiUSIIL dataset to {PHIUSIIL.parent} first (see ml/README.md).")
    hosts, y = load_phiusiil()
    if CACHE.exists() and list(np.load(CACHE)["hosts"]) == hosts:
        X = np.load(CACHE)["X"]
    else:
        print(f"Computing features for {len(hosts):,} hostnames...")
        X = featurise(hosts)
        np.savez(CACHE, X=X, hosts=np.array(hosts, dtype=str))
    groups = np.array([group_of(h) for h in hosts])
    print(f"{len(hosts):,} unique hostnames: {int(y.sum()):,} phishing, {int((y == 0).sum()):,} genuine")

    # 70% train, 15% validation (early stopping and the threshold), 15% test, split by owner
    first = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=SEED)
    train, rest = next(first.split(X, y, groups))
    second = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=SEED)
    val_i, test_i = next(second.split(X[rest], y[rest], groups[rest]))
    val, test = rest[val_i], rest[test_i]

    params = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 50,
              "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "seed": SEED, "verbose": -1}
    model = lgb.train(params, lgb.Dataset(X[train], y[train], feature_name=NAMES), num_boost_round=2000,
                      valid_sets=[lgb.Dataset(X[val], y[val], feature_name=NAMES)],
                      callbacks=[lgb.early_stopping(50, verbose=False)])

    # Threshold: the lowest score that keeps validation false alarms at or under MAX_FALSE_ALARMS
    genuine_scores = np.sort(model.predict(X[val][y[val] == 0]))
    threshold = float(genuine_scores[int(math.ceil(len(genuine_scores) * (1 - MAX_FALSE_ALARMS))) - 1])

    p_test = model.predict(X[test])
    report = {"dataset": rates(y[test], p_test > threshold), "auc": roc_auc_score(y[test], p_test)}

    fresh = None
    if FRESH.exists():
        rows = [json.loads(l) for l in FRESH.read_text(encoding="utf-8").splitlines() if l.strip()]
        seen, f_hosts, f_y = set(hosts), [], []
        for r in rows:
            h = hostname(r["url"])
            if h and h not in seen and h not in f_hosts:
                f_hosts.append(h)
                f_y.append(1 if r["label"] == "phishing" else 0)
        f_y = np.array(f_y)
        f_X = np.array([features(h) for h in f_hosts], dtype=np.float32)
        p_fresh = model.predict(f_X)
        rule = (f_X[:, NAMES.index("lookalike")] > 0) | (f_X[:, NAMES.index("brand_not_official")] > 0)
        fresh = {"model": rates(f_y, p_fresh > threshold), "rules": rates(f_y, rule),
                 "both": rates(f_y, (p_fresh > threshold) | rule), "auc": roc_auc_score(f_y, p_fresh),
                 "n": len(f_hosts), "overlap": len(rows) - len(f_hosts)}

    MODELS.mkdir(exist_ok=True)
    model.save_model(str(MODELS / "url_model.txt"))
    (MODELS / "url_model.json").write_text(json.dumps(
        {"features": NAMES, "threshold": threshold, "trained": date.today().isoformat(),
         "trees": model.num_trees(), "data": "PhiUSIIL (Prasad and Chandra, 2024), CC BY 4.0"}, indent=2) + "\n")

    gain = model.feature_importance("gain")
    top = sorted(zip(NAMES, gain / gain.sum()), key=lambda t: -t[1])[:10]
    md = ["# URL model evaluation", "",
          f"Trained {date.today().isoformat()} on {len(train):,} hostnames from PhiUSIIL; threshold "
          f"{threshold:.3f}, chosen so at most {MAX_FALSE_ALARMS:.0%} of genuine sites in validation are flagged. "
          "Rates show 95% confidence intervals.", "",
          "## Held-out PhiUSIIL test set (2023 data, sites the model never saw)", "",
          f"- Detection: {report['dataset']['detection']}",
          f"- False alarms: {report['dataset']['false_alarms']}",
          f"- ROC AUC: {report['auc']:.4f}", f"- {report['dataset']['counts']}", ""]
    if fresh:
        md += ["## Fresh 2026 links (OpenPhish and Tranco, collected by the server)", "",
               f"{fresh['n']} unique hostnames ({fresh['overlap']} rows skipped as duplicates or already in training).", "",
               "| Method | Detection | False alarms |", "|---|---|---|",
               f"| Artemis's name rules only (lookalike, brand in name) | {fresh['rules']['detection']} | {fresh['rules']['false_alarms']} |",
               f"| URL model | {fresh['model']['detection']} | {fresh['model']['false_alarms']} |",
               f"| Either | {fresh['both']['detection']} | {fresh['both']['false_alarms']} |", "",
               f"ROC AUC of the model on fresh links: {fresh['auc']:.4f}", ""]
    md += ["## What the model relies on most (share of total gain)", ""]
    md += [f"- `{n}`: {100 * g:.1f}%" for n, g in top]
    (MODELS / "url_model_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
