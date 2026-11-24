"""
AgentRails (app.py) — Core Python Infrastructure for Autonomous Agents.

Software built for agents rather than people: verifiable delegated identity,
scoped permissions, spend-capped payment rails, structured interfaces,
auditable memory, and deterministic sandbox verification.

License: Apache-2.0
Python: 3.10+ (Standard Library Only — Zero Mandatory Dependencies)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


class DecisionStatus(str, Enum):
    """Deterministic outcome of an agent policy or payment evaluation."""

    ALLOWED = "allowed"
    REQUIRES_APPROVAL = "requires_approval"
    DENIED = "denied"


@dataclass(frozen=True)
class AuditRecord:
    """Immutable, tamper-evident log entry for every agent action."""

    event_id: str
    timestamp: float
    agent_id: str
    principal_id: str
    action: str
    status: DecisionStatus
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


# ---------------------------------------------------------------------------
# 1. Identity & Cryptographic Delegation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegationToken:
    """Signed credential proving which principal an agent acts on behalf of."""

    token_id: str
    agent_id: str
    principal_id: str
    scopes: Tuple[str, ...]
    issued_at: float
    expires_at: float
    audience: str
    signature: str

    def is_expired(self, now: Optional[float] = None) -> bool:
        current = time.time() if now is None else now
        return current >= self.expires_at


class IdentityAuthority:
    """Issues and verifies HMAC-SHA256 delegation credentials for agents."""

    def __init__(self, signing_secret: Optional[str] = None) -> None:
        self._secret = (signing_secret or secrets.token_hex(32)).encode("utf-8")
        self._revoked_tokens: set[str] = set()

    def _sign_payload(self, payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._secret, canonical, hashlib.sha256).hexdigest()

    def issue_token(
        self,
        *,
        agent_id: str,
        principal_id: str,
        scopes: Iterable[str],
        ttl_seconds: int = 3600,
        audience: str = "agent-runtime",
    ) -> DelegationToken:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = time.time()
        token_id = f"agt_{uuid.uuid4().hex[:16]}"
        normalized_scopes = tuple(sorted({s.strip() for s in scopes if s.strip()}))
        payload = {
            "token_id": token_id,
            "agent_id": agent_id,
            "principal_id": principal_id,
            "scopes": list(normalized_scopes),
            "issued_at": round(now, 6),
            "expires_at": round(now + ttl_seconds, 6),
            "audience": audience,
        }
        signature = self._sign_payload(payload)
        return DelegationToken(
            token_id=token_id,
            agent_id=agent_id,
            principal_id=principal_id,
            scopes=normalized_scopes,
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
            audience=audience,
            signature=signature,
        )

    def revoke(self, token_id: str) -> None:
        self._revoked_tokens.add(token_id)

    def verify(
        self,
        token: DelegationToken,
        *,
        required_scope: Optional[str] = None,
        expected_audience: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Tuple[bool, str]:
        if token.token_id in self._revoked_tokens:
            return False, "delegation token has been revoked"
        if token.is_expired(now=now):
            return False, "delegation token has expired"
        if expected_audience and token.audience != expected_audience:
            return False, f"unexpected audience: {token.audience}"
        payload = {
            "token_id": token.token_id,
            "agent_id": token.agent_id,
            "principal_id": token.principal_id,
            "scopes": list(token.scopes),
            "issued_at": token.issued_at,
            "expires_at": token.expires_at,
            "audience": token.audience,
        }
        expected_sig = self._sign_payload(payload)
        if not hmac.compare_digest(expected_sig, token.signature):
            return False, "invalid delegation signature"
        if required_scope and required_scope not in token.scopes:
            return False, f"missing required scope: {required_scope}"
        return True, "verified"


# ---------------------------------------------------------------------------
# 2. Scoped Permissions & Guardrail Policy Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionPolicy:
    """Declarative capability boundaries enforced before an agent acts."""

    allowed_scopes: Tuple[str, ...]
    allowed_merchants: Tuple[str, ...] = ()
    max_single_tx_cents: int = 25_000
    daily_spend_cap_cents: int = 100_000
    approval_threshold_cents: int = 10_000
    require_idempotency_key: bool = True


@dataclass(frozen=True)
class PolicyEvaluation:
    """Structured result returned by the PolicyEngine."""

    status: DecisionStatus
    reason: str
    rule_id: str


class PolicyEngine:
    """Evaluates agent actions deterministically against a PermissionPolicy."""

    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        *,
        scope: str,
        merchant: Optional[str] = None,
        amount_cents: int = 0,
        spent_today_cents: int = 0,
        idempotency_key: Optional[str] = None,
    ) -> PolicyEvaluation:
        if scope not in self.policy.allowed_scopes:
            return PolicyEvaluation(
                status=DecisionStatus.DENIED,
                reason=f"scope '{scope}' is not permitted by policy",
                rule_id="policy.scope_denied",
            )
        if amount_cents < 0:
            return PolicyEvaluation(
                status=DecisionStatus.DENIED,
                reason="amount_cents cannot be negative",
                rule_id="policy.invalid_amount",
            )
        if (
            self.policy.allowed_merchants
            and merchant is not None
            and merchant not in self.policy.allowed_merchants
        ):
            return PolicyEvaluation(
                status=DecisionStatus.DENIED,
                reason=f"merchant '{merchant}' is not on the allowlist",
                rule_id="policy.merchant_blocked",
            )
        if amount_cents > 0 and self.policy.require_idempotency_key and not idempotency_key:
            return PolicyEvaluation(
                status=DecisionStatus.DENIED,
                reason="idempotency_key is required for spend actions",
                rule_id="policy.missing_idempotency_key",
            )
        if amount_cents > self.policy.max_single_tx_cents:
            return PolicyEvaluation(
                status=DecisionStatus.DENIED,
                reason=(
                    f"amount {amount_cents}c exceeds single-transaction cap "
                    f"{self.policy.max_single_tx_cents}c"
                ),
                rule_id="policy.single_tx_cap",
            )
        if spent_today_cents + amount_cents > self.policy.daily_spend_cap_cents:
            return PolicyEvaluation(
                status=DecisionStatus.DENIED,
                reason=(
                    f"projected daily spend {spent_today_cents + amount_cents}c exceeds "
                    f"daily cap {self.policy.daily_spend_cap_cents}c"
                ),
                rule_id="policy.daily_cap",
            )
        if amount_cents > self.policy.approval_threshold_cents:
            return PolicyEvaluation(
                status=DecisionStatus.REQUIRES_APPROVAL,
                reason=(
                    f"amount {amount_cents}c exceeds human approval threshold "
                    f"{self.policy.approval_threshold_cents}c"
                ),
                rule_id="policy.approval_required",
            )
        return PolicyEvaluation(
            status=DecisionStatus.ALLOWED,
            reason="action satisfies all policy constraints",
            rule_id="policy.ok",
        )


# ---------------------------------------------------------------------------
# 3. Spend-Capped Payment Vault & Signed Receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpendIntent:
    """Structured purchase request submitted by an agent."""

    merchant: str
    amount_cents: int
    currency: str
    description: str
    idempotency_key: str


@dataclass(frozen=True)
class PaymentReceipt:
    """Cryptographically signed proof of an authorized agent disbursement."""

    receipt_id: str
    agent_id: str
    principal_id: str
    merchant: str
    amount_cents: int
    currency: str
    idempotency_key: str
    created_at: float
    signature: str


class PaymentVault:
    """Tracks integer minor-unit budgets and issues idempotent signed receipts."""

    def __init__(self, signing_secret: Optional[str] = None) -> None:
        self._secret = (signing_secret or secrets.token_hex(32)).encode("utf-8")
        self._spent_by_agent: Dict[str, int] = {}
        self._receipts_by_key: Dict[str, PaymentReceipt] = {}

    def spent_today_cents(self, agent_id: str) -> int:
        return self._spent_by_agent.get(agent_id, 0)

    def authorize_and_capture(
        self,
        *,
        agent_id: str,
        principal_id: str,
        intent: SpendIntent,
    ) -> PaymentReceipt:
        if intent.idempotency_key in self._receipts_by_key:
            return self._receipts_by_key[intent.idempotency_key]

        if intent.amount_cents <= 0:
            raise ValueError("intent.amount_cents must be greater than zero")

        receipt_id = f"rcpt_{uuid.uuid4().hex[:14]}"
        created_at = round(time.time(), 6)
        payload = {
            "receipt_id": receipt_id,
            "agent_id": agent_id,
            "principal_id": principal_id,
            "merchant": intent.merchant,
            "amount_cents": intent.amount_cents,
            "currency": intent.currency.upper(),
            "idempotency_key": intent.idempotency_key,
            "created_at": created_at,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._secret, canonical, hashlib.sha256).hexdigest()

        receipt = PaymentReceipt(signature=signature, **payload)
        self._receipts_by_key[intent.idempotency_key] = receipt
        self._spent_by_agent[agent_id] = self.spent_today_cents(agent_id) + intent.amount_cents
        return receipt


# ---------------------------------------------------------------------------
# 4. Agent-Native Structured Interfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentInterface:
    """Machine-native contract replacing brittle forms, logins, and CAPTCHAs."""

    name: str
    required_scope: str
    description: str
    input_schema: Dict[str, str]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]


class InterfaceRegistry:
    """Registers and invokes typed, idempotent interfaces built for agents."""

    def __init__(self) -> None:
        self._interfaces: Dict[str, AgentInterface] = {}

    def register(self, contract: AgentInterface) -> None:
        if contract.name in self._interfaces:
            raise ValueError(f"interface '{contract.name}' is already registered")
        self._interfaces[contract.name] = contract

    def list_contracts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": item.name,
                "required_scope": item.required_scope,
                "description": item.description,
                "input_schema": item.input_schema,
            }
            for item in self._interfaces.values()
        ]

    def invoke(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._interfaces:
            raise KeyError(f"unknown agent interface: {name}")
        contract = self._interfaces[name]
        missing = [k for k in contract.input_schema if k not in payload]
        if missing:
            raise ValueError(f"missing required fields for '{name}': {', '.join(missing)}")
        return contract.handler(payload)


# ---------------------------------------------------------------------------
# 5. Scoped Auditable Agent Memory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryEntry:
    """Namespace-isolated fact stored for an agent with optional TTL."""

    namespace: str
    key: str
    value: Any
    written_at: float
    expires_at: Optional[float] = None


class AgentMemory:
    """Safe, namespace-isolated key-value memory with expiration support."""

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, str], MemoryEntry] = {}

    def remember(
        self,
        *,
        namespace: str,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> MemoryEntry:
        now = time.time()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
        entry = MemoryEntry(
            namespace=namespace,
            key=key,
            value=value,
            written_at=round(now, 6),
            expires_at=round(expires_at, 6) if expires_at is not None else None,
        )
        self._store[(namespace, key)] = entry
        return entry

    def recall(self, *, namespace: str, key: str, now: Optional[float] = None) -> Optional[Any]:
        entry = self._store.get((namespace, key))
        if entry is None:
            return None
        current = time.time() if now is None else now
        if entry.expires_at is not None and current >= entry.expires_at:
            self._store.pop((namespace, key), None)
            return None
        return entry.value

    def list_namespace(self, namespace: str) -> Dict[str, Any]:
        now = time.time()
        results: Dict[str, Any] = {}
        for (ns, key), entry in list(self._store.items()):
            if ns != namespace:
                continue
            if entry.expires_at is not None and now >= entry.expires_at:
                self._store.pop((ns, key), None)
                continue
            results[key] = entry.value
        return results


# ---------------------------------------------------------------------------
# 6. Sandbox & Deterministic Verification Harness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxReport:
    """Summary of a dry-run verification suite against agent actions."""

    sandbox_id: str
    total_events: int
    allowed: int
    requires_approval: int
    denied: int
    records: Tuple[AuditRecord, ...]


class AgentSandbox:
    """Captures immutable audit logs for pre-production testing and replay."""

    def __init__(self, sandbox_id: Optional[str] = None) -> None:
        self.sandbox_id = sandbox_id or f"sbx_{uuid.uuid4().hex[:10]}"
        self._records: List[AuditRecord] = []

    def record(
        self,
        *,
        agent_id: str,
        principal_id: str,
        action: str,
        status: DecisionStatus,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditRecord:
        entry = AuditRecord(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            timestamp=round(time.time(), 6),
            agent_id=agent_id,
            principal_id=principal_id,
            action=action,
            status=status,
            reason=reason,
            metadata=metadata or {},
        )
        self._records.append(entry)
        return entry

    def report(self) -> SandboxReport:
        allowed = sum(1 for r in self._records if r.status == DecisionStatus.ALLOWED)
        approval = sum(1 for r in self._records if r.status == DecisionStatus.REQUIRES_APPROVAL)
        denied = sum(1 for r in self._records if r.status == DecisionStatus.DENIED)
        return SandboxReport(
            sandbox_id=self.sandbox_id,
            total_events=len(self._records),
            allowed=allowed,
            requires_approval=approval,
            denied=denied,
            records=tuple(self._records),
        )


# ---------------------------------------------------------------------------
# Unified SDK Facade
# ---------------------------------------------------------------------------


class AgentRailsClient:
    """Single entry point bundling agent-native infrastructure primitives."""

    def __init__(
        self,
        *,
        policy: Optional[PermissionPolicy] = None,
        signing_secret: Optional[str] = None,
        sandbox_mode: bool = True,
    ) -> None:
        self.identity = IdentityAuthority(signing_secret=signing_secret)
        self.policy_engine = PolicyEngine(
            policy
            or PermissionPolicy(
                allowed_scopes=("procurement.read", "procurement.purchase", "memory.write"),
                allowed_merchants=("aws.amazon.com", "stripe.com", "linear.app"),
            )
        )
        self.payments = PaymentVault(signing_secret=signing_secret)
        self.interfaces = InterfaceRegistry()
        self.memory = AgentMemory()
        self.sandbox_mode = sandbox_mode
        self.sandbox = AgentSandbox()

    def execute_purchase(
        self,
        *,
        token: DelegationToken,
        intent: SpendIntent,
        required_scope: str = "procurement.purchase",
    ) -> Dict[str, Any]:
        """Verify identity, enforce policy guardrails, and settle within caps."""
        ok, verify_reason = self.identity.verify(token, required_scope=required_scope)
        if not ok:
            self.sandbox.record(
                agent_id=token.agent_id,
                principal_id=token.principal_id,
                action=f"purchase:{intent.merchant}",
                status=DecisionStatus.DENIED,
                reason=verify_reason,
                metadata={"amount_cents": intent.amount_cents},
            )
            return {"status": DecisionStatus.DENIED.value, "reason": verify_reason}

        evaluation = self.policy_engine.evaluate(
            scope=required_scope,
            merchant=intent.merchant,
            amount_cents=intent.amount_cents,
            spent_today_cents=self.payments.spent_today_cents(token.agent_id),
            idempotency_key=intent.idempotency_key,
        )
        if evaluation.status != DecisionStatus.ALLOWED:
            self.sandbox.record(
                agent_id=token.agent_id,
                principal_id=token.principal_id,
                action=f"purchase:{intent.merchant}",
                status=evaluation.status,
                reason=evaluation.reason,
                metadata={"rule_id": evaluation.rule_id, "amount_cents": intent.amount_cents},
            )
            return {
                "status": evaluation.status.value,
                "reason": evaluation.reason,
                "rule_id": evaluation.rule_id,
            }

        receipt = self.payments.authorize_and_capture(
            agent_id=token.agent_id,
            principal_id=token.principal_id,
            intent=intent,
        )
        self.sandbox.record(
            agent_id=token.agent_id,
            principal_id=token.principal_id,
            action=f"purchase:{intent.merchant}",
            status=DecisionStatus.ALLOWED,
            reason="authorized and captured",
            metadata={"receipt_id": receipt.receipt_id, "amount_cents": receipt.amount_cents},
        )
        return {
            "status": DecisionStatus.ALLOWED.value,
            "receipt": asdict(receipt),
        }


def run_demo() -> Dict[str, Any]:
    """Executable smoke test demonstrating the AgentRails base architecture."""
    client = AgentRailsClient()
    summary: Dict[str, Any] = {"product": "AgentRails", "license": "Apache-2.0"}
    client.interfaces.register(
        AgentInterface(
            name="seats.provision",
            required_scope="procurement.purchase",
            description="Provision team seats without browser logins or CAPTCHAs.",
            input_schema={"vendor": "str", "seat_count": "int"},
            handler=lambda payload: {
                "provisioned": True,
                "vendor": payload["vendor"],
                "seat_count": payload["seat_count"],
            },
        )
    )
    summary["interface_result"] = client.interfaces.invoke(
        "seats.provision", {"vendor": "linear.app", "seat_count": 5}
    )
    token = client.identity.issue_token(
        agent_id="agent_procurement_01",
        principal_id="org_acme_corp",
        scopes=("procurement.read", "procurement.purchase", "memory.write"),
        ttl_seconds=1800,
    )
    summary["approved_purchase"] = client.execute_purchase(
        token=token,
        intent=SpendIntent(
            merchant="linear.app",
            amount_cents=4_800,
            currency="USD",
            description="5 seat renewal",
            idempotency_key="idem_linear_2026_11",
        ),
    )
    summary["escalated_purchase"] = client.execute_purchase(
        token=token,
        intent=SpendIntent(
            merchant="aws.amazon.com",
            amount_cents=18_500,
            currency="USD",
            description="Reserved compute block",
            idempotency_key="idem_aws_2026_11",
        ),
    )
    client.memory.remember(
        namespace="org_acme_corp",
        key="preferred_billing_cycle",
        value="annual",
        ttl_seconds=86_400,
    )
    summary["memory_recall"] = client.memory.recall(
        namespace="org_acme_corp",
        key="preferred_billing_cycle",
    )
    report = client.sandbox.report()
    summary["sandbox"] = {
        "sandbox_id": report.sandbox_id,
        "total_events": report.total_events,
        "allowed": report.allowed,
        "requires_approval": report.requires_approval,
        "denied": report.denied,
    }
    return summary


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2))
