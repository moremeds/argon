# Optical `company_type` routing probe

**As of:** 2026-08-27 · **DB:** `postgresql://argon_app@127.0.0.1/option_wizard_local` · **Taxonomy version:** `argon-research-v1` · **Chain:** `Optical-Communication` (17 members)

**Reproduce:**

```bash
uv run python scripts/research/optical_company_type_probe.py
```

Brief context (Task 11, spec §5-vii): the plan's account says "16 Optical-Communication members". This DB carries **17**, not 16 — another instance of a plan brief being wrong about a data count. The routing mechanism it describes (a single `watchlist.sector` tag shadowing the correct `SECTOR_TO_TYPE` optical entry) IS what this probe finds.

| ticker | layer | watchlist.sector | company_type | method | misrouted |
|---|---|---|---|---|---|
| AAOI | Upstream-Components | DC-Connect | power_infra | ebitda_to_ev | YES |
| AMZN | Customer-Cloud | M7 | platform_scale | fcf_yield | no |
| ANET | Systems-Networking | DC-Connect | power_infra | ebitda_to_ev | YES |
| AVGO | Semi-DSP-Switch | Semi-Logic | chips_cyclical | sales_to_ev | no |
| CIEN | Systems-Networking | (none) | unclassified | sales_to_ev | no |
| COHR | Upstream-Components | DC-Connect | power_infra | ebitda_to_ev | YES |
| CRDO | Semi-DSP-Switch | DC-Connect | power_infra | ebitda_to_ev | YES |
| FN | Module-Transceiver | DC-Connect | power_infra | ebitda_to_ev | YES |
| GOOGL | Customer-Cloud | M7 | platform_scale | fcf_yield | no |
| JNPR | Systems-Networking | (none) | unclassified | sales_to_ev | no |
| LITE | Upstream-Components | DC-Connect | power_infra | ebitda_to_ev | YES |
| META | Customer-Cloud | M7 | platform_scale | fcf_yield | no |
| MRVL | Semi-DSP-Switch | DC-Connect | power_infra | ebitda_to_ev | YES |
| MSFT | Customer-Cloud | M7 | platform_scale | fcf_yield | no |
| NTAP | Systems-Networking | (none) | unclassified | sales_to_ev | no |
| ORCL | Customer-Cloud | NeoCloud | high_risk_growth | sales_to_ev | no |
| POET | Upstream-Components | Networking/Optical | chips_cyclical | sales_to_ev | no |

**Misrouted (7 of 17):** AAOI, ANET, COHR, CRDO, FN, LITE, MRVL

All seven carry `watchlist.sector = 'DC-Connect'` — a real sector tag for other names, which happens to shadow the `"Networking/Optical": "chips_cyclical"` entry these names should have matched instead. None of the seven is a power/electrical-infrastructure business (AAOI = Applied Optoelectronics, ANET = Arista Networks, COHR = Coherent, CRDO = Credo, FN = Fabrinet, LITE = Lumentum, MRVL = Marvell).

Not misrouted, for the record: the four M7 names and ORCL are hyperscale/cloud customers correctly routed to `platform_scale` / `high_risk_growth` via their own sector tags; AVGO already carries `Semi-Logic` (matches the `"Semi"` prefix -> `chips_cyclical`); POET already carries the correct `Networking/Optical` tag directly. CIEN, JNPR and NTAP carry no `watchlist` row at all (`no sector on file` -> `unclassified`, the documented non-bug default) — that is an absence of data, not a wrong single-tag routing, and is out of this fix's scope.
