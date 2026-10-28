# Machine learning

## URL model (first version)

A LightGBM classifier that scores how much a web address's **hostname** looks like a phishing one, and
explains its score in plain language using SHAP values. It looks at the name only (length, digits,
hyphens, how random it looks, brand and bait words, the domain ending, free hosting), never the page.

| File | What it does |
|---|---|
| `url_features.py` | Turns an address into 20 features, each with a plain-language reason |
| `train_url_model.py` | Trains the model, picks the threshold and writes the evaluation |
| `url_model.py` | `score(url)` for the app: probability, flagged or not, and the top reasons |
| `models/` | The trained model (`url_model.txt`, a small text file), its settings and `url_model_report.md` |

### Retraining

```bash
pip install lightgbm scikit-learn
# 1. The PhiUSIIL dataset (14.7 MB zip) from the UCI repository, into ml/data/phiusiil/:
#    https://archive.ics.uci.edu/dataset/967/phiusiil+phishing+url+dataset
# 2. Optional fresh test links from the server:
scp -i ~/.ssh/artemis-oracle.key ubuntu@144.24.102.226:/opt/artemis/evaluation/data/dataset.jsonl ml/data/artemis/
python ml/train_url_model.py
```

`ml/data/` isn't committed. Training takes about a minute.

### Design choices

- **Hostname only.** In PhiUSIIL every genuine address is a bare `https://www.` homepage, so a model given
  the whole address learns "has a path, so phishing". Using the hostname without `www.` removes that shortcut.
- **Split by owner.** Training and test data never share a registered domain (on free hosting, a
  subdomain), so the test measures sites the model has never seen.
- **Threshold for few false alarms.** It's set so at most 1% of genuine sites in validation are flagged.
- **Tested on fresh data.** Links collected by the server in 2026 show how the model does on today's
  phishing rather than the 2023 dataset's.

### Limits

- Hacked ordinary sites (`lyndenfloordesign.com`) have innocent names, so no address model can catch them.
  The planned page model, trained on what Artemis's sandboxed browser sees, is for those.
- Long-established company names with a brand word and a hyphen (`google-analytics.com`) can score high.
  Weigh the score together with the domain's age, which Artemis already looks up.

Data: Prasad, A. and Chandra, S. (2024). PhiUSIIL Phishing URL (Website). UCI Machine Learning Repository,
CC BY 4.0. https://doi.org/10.1016/j.cose.2023.103545
