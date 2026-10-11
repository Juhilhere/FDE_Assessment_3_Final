# FDE Assessment 3 - AI Procurement Request Copilot

This project implements the procurement copilot vertical slice using the synthetic starter data and policy snapshot dated 2026-09-30.

## Run

```powershell
python -m pip install -r requirements.txt
python verify_setup.py
python run_local.py
```

The launcher starts the mock vendor-risk API on port 8001 and Streamlit on port 8501. Select a request and `single` or `staged` to inspect the structured recommendation, evidence, approvals, missing information, risk flags, and next step.

## Design

The visible tools are request, identity/budget, software overlap, purchase history, vendor registry, vendor-risk API, and policy tools. Budget thresholds, missing fields, stale reviews, overlap, security/privacy/legal gates, and approvals are deterministic. Requester text is untrusted data; prompt injection is surfaced and never changes policy. Vendor-risk failures fail closed. The copilot never purchases, approves, changes budgets, or accepts legal terms.

Architecture A is one policy orchestrator. Architecture B is two explicit stages (evidence collection and policy adjudication) with the same deterministic checks. Both return `ProcurementDecision`.

## Evaluation

```powershell
python evals/run_public_evals.py --architecture single
python evals/run_public_evals.py --architecture staged
```

All six public cases pass the minimum evaluator checks for both architectures in local testing. Telemetry reports tool names, calls, and zero LLM calls because policy-critical decisions are deterministic and reproducible.

## Ship decision

Ship the single-agent baseline for this MVP: it matches staged on the public cases while keeping one orchestration path and lower operational complexity. Staged remains a future seam for a separately validated interpretation step.

## Limitations

The mock API and data are synthetic. Production validation still needs authenticated vendor APIs, policy versioning, audit retention, privacy/legal processing, identity controls, adversarial text, and a larger hidden-case suite.
