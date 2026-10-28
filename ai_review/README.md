# AI security review

Finds likely vulnerabilities in Artemis's own code, has an AI model judge each one in context, and tries
to prove the real ones with a test. It follows the same loop that larger AI bug-finding systems use:

```
Semgrep finds candidates  ->  a model judges each one  ->  a proof script runs in a sandbox  ->  report
```

Static tools such as Semgrep catch patterns, not meaning, so they raise many false alarms. The AI step
reads the code around each finding, along with a description of Artemis and its existing defences, and
says whether it is real, how bad it is, how an attacker would use it and how to fix it. A finding counts as
**proved** only when a script that calls Artemis's own code shows the problem happening. The proof step is
what makes the result something to trust rather than an opinion.

## Running it

```bash
pip install -r ai_review/requirements.txt
ollama pull qwen2.5-coder:7b                        # once, about 4.7 GB
python ai_review/review.py --max 5 --no-proofs      # a quick first try
python ai_review/review.py                          # the whole project, up to 20 findings
python ai_review/review.py --base origin/main       # only files changed on this branch
```

The report is written to `ai_review/out/report.md`, with every verdict in `findings.json` and the proof
scripts in `proofs/`. That folder isn't committed.

## Choosing a model

| `--provider` | Model (default) | Cost | Where the code goes |
|---|---|---|---|
| `ollama` (default) | `qwen2.5-coder:7b` | Free | Stays on your computer |
| `github` | `openai/gpt-4.1` | Free within GitHub Models' daily limits | GitHub Models |
| `claude` | `claude-opus-5-5` | A few cents per finding | The Anthropic API |

Any other model can be named with `--model`, for example `--model llama3.2` for a smaller Ollama model.

- **Ollama** runs the model on your own computer. A 7B model fits an 8 GB graphics card and takes about
  half a minute per finding. Small models make more mistakes: expect more false alarms and weaker proofs.
- **GitHub Models** needs a GitHub token in `GITHUB_TOKEN`; in GitHub Actions it is set automatically.
  Free use has daily request limits, so keep `--max` modest. `--model openai/gpt-4.1-mini` has higher
  limits.
- **Claude** is the most accurate of the three. It needs `pip install anthropic` and an API key in
  `ANTHROPIC_API_KEY`, and the script prints the cost at the end.

## Proofs and the sandbox

Proof scripts are written by the model, so they are treated as untrusted code. They run only in a Docker
container with no network, a read-only copy of the project, no Linux capabilities, 512 MB of memory and
a 90-second limit. Build the container once:

```bash
docker build -f ai_review/sandbox.Dockerfile -t artemis-review-sandbox .
```

Without Docker, the scripts are saved to `ai_review/out/proofs/` but never run. Read one before you run
it yourself. A script that doesn't import any of Artemis's modules is rejected, because it can't be
proving anything about Artemis.

## On GitHub

`.github/workflows/ai-review.yml` runs the review with GitHub Models on every pull request (changed files
only) and on demand from the Actions tab (the whole project). It needs no keys or settings: the workflow's
own token is allowed to use GitHub Models. The report appears on the run's summary page and as a
downloadable artifact.

## Files

| File | What it does |
|---|---|
| `review.py` | The four steps: Semgrep, the model's verdicts, proofs, report |
| `rules.yml` | Semgrep rules written for Artemis: redirects that skip the SSRF check, TLS checks turned off, SQL built from strings, HTML built from data |
| `sandbox.Dockerfile` | The container the proof scripts run in |

## Limits

- The AI only sees the code near each finding, not the whole project, so it can miss a defence elsewhere
  (it then tends to answer "unsure") or miss a bug Semgrep never flagged.
- A passing proof is strong evidence, not certainty: read the script before acting on it.
- Treat the report as a reviewer's notes. A person decides what to change.
