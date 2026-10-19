# Dashboard UI States & Visual Specification

This document details the visual states, accessibility considerations, and design choices of the B2B Lead Qualifier Audit Dashboard (`/dashboard`).

The interface follows a strict **audit ledger aesthetic** designed for commercial managers in office and mobile environments during daytime operations. It employs a clean light theme, the `IBM Plex Sans` typography with tabular numerals (`tabular-nums`), and explicit visual forms to differentiate decisions without relying solely on color.

---

## 1. Primary Inspection Views

### Desktop View (1280px)
Displays the operational metrics summary cards and the analytical audit table. Leads are scaled according to the theoretical maximum score (`max_possible_score`) defined by the tenant's active scoring rule set version.

![Desktop Audit Inspection](images/dashboard_desktop.png)

### Mobile View (390px)
Responsive layout adapting metric cards and audit details for mobile devices without horizontal overflow.

![Mobile Audit Inspection](images/dashboard_mobile.png)

---

## 2. Decision Breakdown & Score Scaling

The audit table evaluates three distinct business outcomes:

| Phone Number | Verdict Badge | Score / Scale | Cutoff | Audit Reasons |
|---|---|---|---|---|
| `+5511999991111` | `✓ Aprovado` | **85** / 130 pts | 50 pts | `+50 pts Cargo: CEO`<br>`+35 pts Faturamento anual: De R$ 2 mi a R$ 10 mi` |
| `+5511999992222` | `✕ Insuficiente` | **25** / 130 pts | 50 pts | `+25 pts Cargo: Gerente`<br>*(Faltam 25 pts para a nota de corte)* |
| `+5511999993333` | `⊘ Eliminado` | **0** / 130 pts | 50 pts | `Eliminatório: Cargo igual a "estudante"` *(Disqualificação imediata no 1º turno)* |

### Visual Form and Scale Mechanics:
- **Dynamic Scale**: The track maximum corresponds to `max_possible_score` computed from the active rule set (sum of maximum attainable points per distinct field).
- **Cutoff Marker**: A vertical marker is positioned at `(qualification_threshold / max_possible_score) * 100%`, providing instant visual reference.
- **Deficit Hint**: When a lead is not qualified by score, the interface explicitly informs the remaining deficit (e.g., *"Faltam 25 pts"*).
- **Knockout Highlight**: Leads disqualified by knockouts display a distinct alert container identifying the restricted criterion.

---

## 3. Operational & Error States

### State 1: Authentication Required
Displayed upon initial visit when no Operator Bearer token has been configured.

![Authentication Required](images/state_no_key.png)

### State 2: Invalid or Revoked API Key (HTTP 401)
Displayed when the API rejects the provided token. Error notices do not expose technical hosts, ports, or stack traces.

![Invalid API Key](images/state_invalid_key.png)

### State 3: Empty State (Zero Evaluated Leads)
Displayed when an authenticated tenant has no qualification records in `scoring_results`.

![Empty State](images/state_empty.png)

---

## 4. Security & Accessibility Architecture

1. **Anti-XSS Defense**: The template strictly avoids `innerHTML` across all rendering routines. DOM construction is performed exclusively via `document.createElement`, `textContent`, and typed property bindings.
2. **Accessible Attributes**: The score track includes descriptive `aria-label` tags detailing achieved score, maximum scale, and cutoff thresholds without invalid ARIA role violations.
3. **Number Legibility**: Numeric values and phone numbers utilize `font-feature-settings: "tnum" 1` and `font-variant-numeric: tabular-nums` to ensure strict vertical alignment in tables.
4. **Structured Translations**: Audit text is rendered client-side using canonical Portuguese dictionary maps for fields (`role`, `revenue_tier`, `company_size`) and enum values without resorting to regex scraping. Unknown values fall back gracefully to their original representations.
