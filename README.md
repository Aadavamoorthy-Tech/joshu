# AgentRails

**Infrastructure built for autonomous agents.**

The internet was built for people: forms, buttons, logins, CAPTCHAs, and checkout pages. Autonomous agents are now first-class users of software, yet they lack verifiable identity, enforceable guardrails, safe payment rails, structured interfaces, auditable memory, and sandbox testing.

`AgentRails` provides the open-core Python foundation to make agents safe, accountable, and commercially deployable users of software.

## Core Primitives (`app.py`)

Zero mandatory external dependencies — runs on **Python 3.10+** standard library out of the box.

1. **Identity & Delegation (`IdentityAuthority`, `DelegationToken`)**
   HMAC-SHA256 signed delegation credentials proving which organization or principal an agent acts on behalf of, with scoped permissions, expiration, and revocation.
2. **Scoped Permissions (`PermissionPolicy`, `PolicyEngine`)**
   Deterministic pre-execution enforcement for allowed scopes, vendor allowlists, single-transaction ceilings, rolling daily spend caps, and human-in-the-loop approval thresholds.
3. **Spend-Capped Payments (`PaymentVault`, `SpendIntent`, `PaymentReceipt`)**
   Integer minor-unit accounting, idempotency keys to prevent duplicate charges, and cryptographically signed disbursement receipts.
4. **Agent-Native Interfaces (`InterfaceRegistry`, `AgentInterface`)**
   Typed machine-native action contracts replacing brittle DOM automation, logins, and CAPTCHAs.
5. **Scoped Memory (`AgentMemory`, `MemoryEntry`)**
   Namespace-isolated persistent state with TTL expiration so agents remember vendor terms and preferences without cross-tenant leakage.
6. **Sandbox & Audit (`AgentSandbox`, `AuditRecord`, `SandboxReport`)**
   Immutable execution log and dry-run verification harness for testing agent workflows before touching production accounts or funds.

## Quickstart

```bash
python3 app.py
```

## Example Usage

```python
from app import AgentRailsClient, SpendIntent

client = AgentRailsClient()

token = client.identity.issue_token(
    agent_id="agent_procurement_01",
    principal_id="org_acme_corp",
    scopes=("procurement.read", "procurement.purchase"),
    ttl_seconds=1800,
)

result = client.execute_purchase(
    token=token,
    intent=SpendIntent(
        merchant="linear.app",
        amount_cents=4_800,
        currency="USD",
        description="Team seat renewal",
        idempotency_key="idem_linear_2026_11",
    ),
)
print(result)
```

## Business Model (Open Core)

- **Open-Core SDK (`app.py`)**: Free, embeddable Python primitives driving bottom-up developer adoption.
- **Managed Control Plane (SaaS)**: Centralized KMS/HSM key custody, Slack/webhook human approval routing, policy versioning, and compliance audit retention.
- **Agent Payment Rails (Usage / Take-Rate)**: Programmatic virtual card and ACH settlement backed by real-time spend policies.

## License

Apache-2.0
