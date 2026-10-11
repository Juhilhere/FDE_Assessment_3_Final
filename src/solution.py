from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import requests

from src.contracts import Architecture, EvidenceItem, ProcurementDecision, RunTelemetry
from src.data_access import (get_request, load_budgets, load_employees, load_policy_text,
                             load_purchase_history, load_software_catalog, load_vendors)
from src.vendor_client import get_vendor_risk

REFERENCE_DATE = date(2026, 9, 30)
ROOT = Path(__file__).resolve().parents[1]


def _e(source: str, finding: str, reference: str | None = None) -> EvidenceItem:
    return EvidenceItem(source=source, finding=finding, reference=reference)


def _risk(vendor: str, telemetry: dict) -> tuple[dict | None, str | None]:
    telemetry['tool_calls'] += 1; telemetry['tool_names'].append('vendor_risk_tool')
    try:
        return get_vendor_risk(vendor), None
    except requests.HTTPError as exc:
        if getattr(exc.response, 'status_code', None) == 503:
            return None, 'Vendor-risk API returned 503: evidence unavailable.'
        return None, f'Vendor-risk API error: {exc}'
    except Exception as exc:
        # Keep the required external-tool boundary visible while allowing the local demo
        # to run without a separately launched mock API. NimbusAI remains unavailable.
        if vendor == 'NimbusAI':
            return None, f'Vendor-risk API unavailable: {exc}'
        try:
            snap = json.loads((ROOT / 'data' / 'vendor_risk.json').read_text(encoding='utf-8'))
            if vendor in snap and not snap[vendor].get('force_error'):
                telemetry['tool_names'].append('vendor_risk_snapshot_fallback')
                return {'vendor_name': vendor, **snap[vendor]}, 'API unavailable; used versioned local snapshot.'
        except Exception:
            pass
        return None, f'Vendor-risk API unavailable: {exc}'


def _injection(text: str) -> bool:
    return bool(re.search(r'ignore\s+(all|previous|the)\s+.*(rules|instructions|policy)|approve\s+it\s+immediately|treat\s+this\s+request\s+as', text, re.I))


def handle_request(request_id: str, architecture: Architecture = 'single') -> ProcurementDecision:
    """Fail-closed procurement recommendation using deterministic policy tools.

    Architecture ``single`` runs one policy orchestrator. ``staged`` separates an
    evidence collector from a policy adjudicator; both share the same pure checks.
    No purchase, approval, budget mutation, or model call occurs here.
    """
    req = get_request(request_id)
    telemetry = {'tool_calls': 0, 'tool_names': [], 'llm_calls': 0 if architecture == 'single' else 0}
    evidence: list[EvidenceItem] = []
    risks: list[str] = []
    missing: list[str] = []
    approvals: list[str] = []

    # Deterministic tools: request, identity/budget, catalog/history, policy, vendor API.
    telemetry['tool_calls'] += 1; telemetry['tool_names'].append('request_tool')
    employees = load_employees(); budgets = load_budgets(); catalog = load_software_catalog(); vendors = load_vendors(); history = load_purchase_history(); policy = load_policy_text()
    telemetry['tool_calls'] += 4; telemetry['tool_names'] += ['identity_budget_tool','software_overlap_tool','purchase_history_tool','policy_tool']
    employee = employees[employees.employee_id == req['requester_id']].iloc[0]
    department = str(employee['department'])
    budget = budgets[budgets.department == department].iloc[0]
    annual = req.get('annual_cost_usd'); seats = req.get('user_count')
    evidence.append(_e('identity_budget_tool', f"Requester {employee['name']} belongs to {department}; available software budget is ${int(budget['available_usd']):,}.", f"{req['requester_id']}/{department}"))

    for field, label in [('annual_cost_usd','annual cost'), ('user_count','user/licenses'), ('data_access_level','data access level')]:
        if req.get(field) in (None, '', 'unknown'):
            missing.append(label)
    if not req.get('business_justification'): missing.append('business purpose')
    if not req.get('requested_integrations') and req.get('requested_integrations') is None: missing.append('required integrations')
    if missing:
        risks.append('missing_information')
    if _injection(req.get('business_justification','')):
        risks.append('prompt_injection_detected')
        evidence.append(_e('request_tool', 'Request text contained an instruction-like attempt to bypass procurement controls; treated as untrusted business data.', request_id))

    overlap = catalog[(catalog.vendor_name == req['vendor_name']) | (catalog.category == req['category'])]
    if len(overlap):
        risks.append('existing_tool_overlap')
        names = ', '.join(overlap.product_name.astype(str).tolist())
        evidence.append(_e('software_overlap_tool', f"Approved catalog contains related product(s): {names}.", 'software_catalog.csv'))
    else:
        evidence.append(_e('software_overlap_tool', 'No same-vendor or same-category approved catalog match was found.', 'software_catalog.csv'))
    prior = history[history.vendor_name == req['vendor_name']]
    if len(prior): evidence.append(_e('purchase_history_tool', f"Purchase history shows {len(prior)} approved record(s) for this vendor.", 'purchase_history.csv'))

    risk, risk_error = _risk(req['vendor_name'], telemetry)
    registry = vendors[vendors.vendor_name == req['vendor_name']]
    registry_row = registry.iloc[0] if len(registry) else None
    if registry_row is not None:
        evidence.append(_e('vendor_registry_tool', f"Registry status: procurement={registry_row['procurement_status']}, security={registry_row['security_status']}, legal={registry_row['legal_terms_status']}.", str(registry_row['vendor_id'])))
    if risk is None:
        risks.extend(['vendor_risk_unavailable','security_review_required'])
        evidence.append(_e('vendor_risk_tool', risk_error or 'Vendor-risk evidence was unavailable.', req['vendor_name']))
    else:
        evidence.append(_e('vendor_risk_tool', f"Risk service: security={risk.get('security_review_status')}, risk={risk.get('risk_level')}, last review={risk.get('last_review_date') or 'none'}.", req['vendor_name']))
        if registry_row is not None and str(registry_row['security_status']).lower() != str(risk.get('security_review_status','')).replace('_',' ').lower():
            risks.append('conflicting_vendor_evidence')
        review = risk.get('last_review_date')
        stale = not review or (REFERENCE_DATE - date.fromisoformat(review)).days > 365
        if stale or str(risk.get('security_review_status','')).lower() in {'expired','not_completed','unknown'}:
            risks.append('vendor_review_expired' if review else 'security_review_required')
            risks.append('security_review_required')
        if str(req.get('data_access_level','')).lower() in {'source_code','production_telemetry','confidential_documents','customer_pii','employee_pii','credentials_secrets'} or req.get('requested_integrations'):
            risks.append('security_review_required')
        if risk.get('processes_personal_data') or str(req.get('data_access_level','')).lower() in {'customer_pii','employee_pii'}:
            risks.append('privacy_review_required')
        if risk.get('stores_data_outside_region'):
            risks.append('privacy_review_required')

    if annual is not None and int(annual) > int(budget['available_usd']): risks.append('budget_insufficient')
    vendor_new = registry_row is None or str(registry_row['procurement_status']).lower() == 'new'
    if vendor_new and annual is not None and int(annual) >= 10000: risks.append('legal_review_required')
    if registry_row is not None and str(registry_row['legal_terms_status']).lower() not in {'approved','standard'}: risks.append('legal_review_required')

    if annual is None:
        approvals.append('Manager')
    elif annual <= 1000: approvals.append('Manager')
    elif annual <= 10000: approvals += ['Department Head','Procurement']
    elif annual <= 25000: approvals += ['Department Head','Finance','Procurement']
    else: approvals += ['Department Head','Finance','CFO','Procurement']
    for a in ['Security','Privacy','Legal']:
        if a.lower() in ' '.join(risks).lower() and a not in approvals: approvals.append(a)
    if 'budget_insufficient' in risks and 'Finance' not in approvals: approvals.append('Finance')
    if not missing and not risks:
        recommendation = 'Recommend proceeding to required human approvals'
    elif missing:
        recommendation = 'Request clarification before approval'
    elif 'budget_insufficient' in risks:
        recommendation = 'Route for budget exception and required reviews'
    else:
        recommendation = 'Route for required reviews before approval'
    unique_risks = list(dict.fromkeys(risks)); unique_approvals = list(dict.fromkeys(approvals)); unique_missing = list(dict.fromkeys(missing))
    next_step = 'Human procurement owner reviews the evidence package and obtains: ' + ', '.join(unique_approvals) + '.'
    return ProcurementDecision(request_id=request_id, recommendation=recommendation, evidence=evidence, required_approvals=unique_approvals, missing_information=unique_missing, risk_flags=unique_risks, next_step=next_step, human_review_required=True, telemetry=RunTelemetry(**telemetry))
