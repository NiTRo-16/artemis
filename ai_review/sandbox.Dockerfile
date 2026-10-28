# The sandbox that proof scripts run in: the project's Python packages, no browser, and (from review.py)
# no network, a read-only file system and a memory limit. Build it from the project root:
#   docker build -f ai_review/sandbox.Dockerfile -t artemis-review-sandbox .
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
