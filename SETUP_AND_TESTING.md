# Project Setup and Local Testing Guide

This document provides all the necessary steps for a developer to set up the repository for the first time and to test the script locally.

## 1. One-Time Project Setup

The inspector needs Google Cloud credentials for AI analysis. A GitHub token and
Slack webhook are optional for local testing; configure a webhook in GitHub Actions
to post the scheduled reports.

### Step 1.1: Configure Credentials

**1. Google Cloud credentials for Claude on Vertex AI**
The AI analysis uses LangChain's `ChatAnthropicVertex` integration. Authenticate
with Google Application Default Credentials locally (`gcloud auth application-default
login`) or provide the GitHub workflow with a `GCP_SA_KEY` service account JSON key
that can invoke Claude on Vertex AI. Set `ANTHROPIC_VERTEX_PROJECT_ID` and
`CLOUD_ML_REGION` for the target project and region.

The log-analysis and final-synthesis models are configured separately in
[`ai_models.json`](ai_models.json). Set `AI_MODEL_CONFIG` to use a different config
file without editing the repository default.

**2. GitHub Personal Access Token**
The inspector compares failure signatures with open issues in
`fedora-iot/iot-distro` and reports potential prior reports in Slack. An optional
token raises the GitHub API rate limit for these requests.
It uses the AI's structured analysis plus raw-log evidence, and compares only the
meaningful bug-report fields rather than reproduction-template text. The matching
decision remains locally verified against the logs.

* **How to get it:** Follow the guide to create a "classic" Personal Access Token.
* **Guide:** [Creating a personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic)
  * **Scope/Permission needed:** You only need to grant the `public_repo` scope.
  * **Note:** Copy the token immediately after generation. You will not see it again.

**3. Slack Incoming Webhook URL**
This URL is used to post the compose analysis and Quay reports to a Slack channel.
The existing team webhook can be reused where access is authorized.
Without a webhook, local runs preview the reports instead of posting them.

* **How to get it:** Follow the guide to create a new Incoming Webhook.
* **Guide:** [Sending messages using Incoming Webhooks](https://api.slack.com/messaging/webhooks)
  1. Create a minimal Slack "App".
  2. Activate "Incoming Webhooks" for the app.
  3. Add a new webhook to your desired workspace and channel. (This may require approval from your Slack workspace admin).
  4. Copy the Webhook URL (it starts with `https://hooks.slack.com/...`).

### Step 1.2: Add Secrets to GitHub

1. In your GitHub repository, go to **`Settings`**.
2. In the left sidebar, navigate to **`Security` > `Secrets and variables` > `Actions`**.
3. Ensure you are on the **`Secrets`** tab.
4. Click **`New repository secret`** for each credential you use. **The names must be an exact match**:
   * `GCP_SA_KEY`: The service account JSON key used by the workflow for Vertex AI.
   * `MY_GITHUB_TOKEN`: Optional token for authenticated GitHub API requests.
   * `SLACK_WEBHOOK_URL`: The webhook URL for scheduled Slack reports.

---

## 2. Local Testing

### Step 2.1: Create a Virtual Environment

It is a best practice to use a virtual environment to manage project-specific dependencies.
Python 3.14+ may show an upstream LangChain/Pydantic compatibility warning during AI
initialization; the inspector leaves this warning visible.

```bash
# From your project's root directory
python3 -m venv .venv
```

### Step 2.2: Activate the Virtual Environment

```bash
source .venv/bin/activate
```
Your terminal prompt should now be prefixed with (.venv).

### Step 2.3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2.4: Configure the Local Environment
Copy the template to `.env`, set `ANTHROPIC_VERTEX_PROJECT_ID` to a project with
access to the configured models, and authenticate with Google Cloud. The template
uses `us-east5`, matching the scheduled workflow. Uncomment the optional GitHub
token or Slack webhook only if you need them. Keep `.env` out of version control.

```bash
cp .env.template .env
gcloud auth application-default login
```

### Step 2.5: Run the Script
You are now ready to run the script locally.

```bash
python check_fedora_iot.py
```
