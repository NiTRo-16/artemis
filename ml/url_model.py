"""Score a web address with the trained URL model and explain the score.

    from ml.url_model import score
    score("paypa1-secure-login.top")
    # {"probability": 0.97, "flagged": True, "reasons": ["The address imitates a known brand's name", ...]}

The reasons are the features that pushed this address's score up the most, worked out by LightGBM's
built-in SHAP values (pred_contrib), so each explanation is specific to the address scored.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from ml.url_features import NAMES, REASONS, features

MODELS = Path(__file__).resolve().parent / "models"


@lru_cache(maxsize=1)
def _load():
    import lightgbm as lgb   # imported here so the app starts even if the model isn't installed
    meta = json.loads((MODELS / "url_model.json").read_text(encoding="utf-8"))
    if meta["features"] != NAMES:
        raise RuntimeError("url_model.txt was trained on different features; retrain it")
    return lgb.Booster(model_file=str(MODELS / "url_model.txt")), meta["threshold"]


def score(url: str, max_reasons: int = 3) -> dict:
    model, threshold = _load()
    x = np.array([features(url)], dtype=np.float32)
    probability = float(model.predict(x)[0])
    contributions = model.predict(x, pred_contrib=True)[0][:-1]   # the last column is the base value
    pushing_up = sorted((c, n) for c, n in zip(contributions, NAMES) if c > 0.05)
    flagged = probability > threshold
    return {"probability": round(probability, 3), "flagged": flagged,
            "reasons": [REASONS[n] for _, n in reversed(pushing_up[-max_reasons:])] if flagged else []}
