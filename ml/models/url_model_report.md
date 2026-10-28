# URL model evaluation

Trained 2026-10-29 on 154,112 hostnames from PhiUSIIL; threshold 0.714, chosen so at most 1% of genuine sites in validation are flagged. Rates show 95% confidence intervals.

## Held-out PhiUSIIL test set (2023 data, sites the model never saw)

- Detection: 62.7% (61.8 to 63.5)
- False alarms: 0.8% (0.7 to 0.9)
- ROC AUC: 0.8684
- 7620/12156 phishing caught, 164/20212 genuine flagged

## Fresh 2026 links (OpenPhish and Tranco, collected by the server)

726 unique hostnames (73 rows skipped as duplicates or already in training).

| Method | Detection | False alarms |
|---|---|---|
| Artemis's name rules only (lookalike, brand in name) | 10.0% (6.9 to 14.1) | 2.9% (1.7 to 4.8) |
| URL model | 70.1% (64.4 to 75.2) | 6.2% (4.3 to 8.8) |
| Either | 72.7% (67.1 to 77.7) | 7.0% (5.0 to 9.8) |

ROC AUC of the model on fresh links: 0.8707

## What the model relies on most (share of total gain)

- `subdomain_levels`: 45.2%
- `subdomain_length`: 18.6%
- `risky_tld`: 11.9%
- `digits`: 5.0%
- `tld_length`: 3.2%
- `host_length`: 2.6%
- `name_length`: 2.1%
- `vowel_ratio`: 1.9%
- `name_entropy`: 1.7%
- `free_host`: 1.4%
