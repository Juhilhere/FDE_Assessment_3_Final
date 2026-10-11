# FDE Assessment 3 - AI Procurement Request Copilot

This is my submission for FDE Assessment 3. I built a small internal tool that reads a software purchase request, checks the available business evidence, applies the procurement policy, and gives the procurement team a recommended next step. The data in this repository is the synthetic data supplied with the assessment. I use the policy reference date of 30 September 2026 for date checks.

## Running the project

From this folder, run:

```powershell
python -m pip install -r requirements.txt
python verify_setup.py
python run_local.py
```

`run_local.py` starts the mock vendor-risk API on port 8001 and the Streamlit app on port 8501. In the app, choose a request and run it using either `single` or `staged` mode. The result shows the evidence used, required approvals, missing information, risk flags, and the next step.

## How I designed it

The implementation uses these tools: request lookup, requester and budget lookup, software overlap lookup, purchase history lookup, vendor registry lookup, vendor-risk API lookup, and procurement policy lookup. The important policy decisions are deterministic: budget thresholds, missing fields, duplicate or overlapping software, stale vendor reviews, and Security, Privacy, Legal, Finance, and Procurement requirements.

Request descriptions are treated as business data. If a description tries to tell the system to ignore the policy or approve a purchase, I flag it as a prompt-injection attempt and continue using the real policy. If the vendor-risk service is unavailable, the result says that the evidence could not be verified and keeps the request with a human reviewer. The program does not approve purchases, change budgets, or accept vendor terms.

The `single` version has one orchestrator. The `staged` version separates evidence collection from policy adjudication, while using the same checks and output contract. Both return `ProcurementDecision` objects.

## Evaluation

I ran the same six public cases against both versions:

```powershell
python evals/run_public_evals.py --architecture single
python evals/run_public_evals.py --architecture staged
```

Both versions passed all six minimum public checks. The evaluation output records the latency, tool calls, and LLM calls for each case. This implementation uses zero LLM calls because the policy-critical decisions need to be repeatable and explainable.

## Architecture decision

I would ship the single version for this MVP. It performed the same on the public cases and has one simpler orchestration path. I kept the staged version to show the comparison requested in the brief and as a possible extension if a separately tested interpretation step is added later.

## Known limitations

The API and business data are synthetic. Before using a similar system in production, I would add authenticated vendor services, stronger access control, audit retention, policy versioning, and more tests for conflicting and adversarial inputs. Human approval would remain required.
