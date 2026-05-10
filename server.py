"""
FinOps Optimizer MCP Server
Rightsizing, savings recommendations, and cost remediation for AIOps Studio.
Integrates with Supabase tables: finops_anomalies, finops_ai_insights,
finops_savings, finops_recommendations, finops_remediation_log
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ─────────────────────────── Constants ───────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

CLOUD_PROVIDERS = ["azure", "aws", "gcp", "openshift", "all"]
SEVERITY_LEVELS = ["critical", "high", "medium", "low"]
REMEDIATION_STATUSES = ["pending", "in_progress", "completed", "failed", "skipped"]

# ─────────────────────────── Lifespan ───────────────────────────

@asynccontextmanager
async def app_lifespan():
    """Initialize shared HTTP client for all Supabase calls."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "Missing env vars: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set."
        )
    async with httpx.AsyncClient(
        base_url=SUPABASE_URL,
        headers=HEADERS,
        timeout=30.0,
    ) as client:
        yield {"client": client}


mcp = FastMCP("finops_optimizer_mcp", lifespan=app_lifespan)

# ─────────────────────────── Shared Helpers ───────────────────────────

def _get_client(ctx: Context) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_state["client"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _handle_supabase_error(resp: httpx.Response, operation: str) -> str:
    """Actionable error messages from Supabase HTTP errors."""
    if resp.status_code == 401:
        return f"Error [{operation}]: Unauthorized. Check SUPABASE_SERVICE_KEY."
    if resp.status_code == 403:
        return f"Error [{operation}]: Forbidden. Row-Level Security may be blocking access."
    if resp.status_code == 404:
        return f"Error [{operation}]: Table not found. Verify Supabase schema is initialized."
    if resp.status_code == 422:
        body = resp.text
        return f"Error [{operation}]: Validation failed — {body}"
    if resp.status_code >= 500:
        return f"Error [{operation}]: Supabase server error ({resp.status_code}). Retry later."
    return f"Error [{operation}]: HTTP {resp.status_code} — {resp.text[:300]}"


async def _supabase_select(
    client: httpx.AsyncClient,
    table: str,
    select: str = "*",
    filters: Optional[Dict[str, str]] = None,
    order: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Generic Supabase SELECT with filters, ordering, pagination."""
    params: Dict[str, Any] = {
        "select": select,
        "limit": limit,
        "offset": offset,
    }
    if filters:
        params.update(filters)
    if order:
        params["order"] = order

    resp = await client.get(f"/rest/v1/{table}", params=params)
    resp.raise_for_status()
    return resp.json()


async def _supabase_insert(
    client: httpx.AsyncClient,
    table: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Generic Supabase INSERT."""
    resp = await client.post(f"/rest/v1/{table}", json=data)
    resp.raise_for_status()
    result = resp.json()
    return result[0] if isinstance(result, list) else result


async def _supabase_patch(
    client: httpx.AsyncClient,
    table: str,
    row_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Generic Supabase PATCH by id."""
    resp = await client.patch(
        f"/rest/v1/{table}",
        params={"id": f"eq.{row_id}"},
        json=data,
    )
    resp.raise_for_status()
    result = resp.json()
    return result[0] if isinstance(result, list) and result else {}


def _format_currency(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _severity_emoji(severity: str) -> str:
    return {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
        severity.lower(), "⚪"
    )


# ─────────────────────────── Input Models ───────────────────────────

class CloudProvider(str, Enum):
    azure = "azure"
    aws = "aws"
    gcp = "gcp"
    openshift = "openshift"
    all = "all"


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class RemediationStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class ResponseFormat(str, Enum):
    markdown = "markdown"
    json = "json"


class PaginationMixin(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    limit: int = Field(default=20, ge=1, le=100, description="Max results (1-100)")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    response_format: ResponseFormat = Field(
        default=ResponseFormat.markdown,
        description="'markdown' for human-readable, 'json' for programmatic use",
    )


class GetAnomaliesInput(PaginationMixin):
    """Input for fetching cost anomalies."""
    provider: CloudProvider = Field(
        default=CloudProvider.all,
        description="Filter by cloud provider: azure | aws | gcp | openshift | all",
    )
    severity: Optional[Severity] = Field(
        default=None,
        description="Filter by severity: critical | high | medium | low",
    )
    resource_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Filter by specific resource ID (e.g., 'vm-prod-001')",
    )


class GetSavingsInput(PaginationMixin):
    """Input for fetching savings recommendations."""
    provider: CloudProvider = Field(default=CloudProvider.all)
    min_savings_usd: Optional[float] = Field(
        default=None,
        ge=0,
        description="Minimum monthly savings threshold in USD (e.g., 100.0)",
    )
    category: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Category filter: rightsizing | idle_resources | reserved_instances | storage",
    )


class GetInsightsInput(PaginationMixin):
    """Input for fetching AI-generated cost insights."""
    provider: CloudProvider = Field(default=CloudProvider.all)
    insight_type: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Type filter: anomaly_explanation | optimization | forecast | trend",
    )


class RightsizingInput(BaseModel):
    """Input for rightsizing analysis of a specific resource."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    resource_id: str = Field(
        ..., min_length=1, max_length=255,
        description="Resource ID to analyze (e.g., 'vm-prod-001', 'aks-node-pool-2')",
    )
    provider: CloudProvider = Field(..., description="Cloud provider of the resource")
    current_sku: Optional[str] = Field(
        default=None, max_length=100,
        description="Current SKU/instance type (e.g., 'Standard_D4s_v3', 'm5.xlarge')",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.markdown)

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("resource_id cannot be empty or whitespace")
        return v.strip()


class ApplyRemediationInput(BaseModel):
    """Input for logging and applying a remediation action."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    recommendation_id: str = Field(
        ..., min_length=1, max_length=255,
        description="ID from finops_recommendations table",
    )
    action_type: str = Field(
        ..., min_length=1, max_length=100,
        description="Action: rightsize | stop_idle | switch_ri | delete_unattached | resize_storage",
    )
    resource_id: str = Field(
        ..., min_length=1, max_length=255,
        description="Target resource ID",
    )
    provider: CloudProvider = Field(..., description="Cloud provider")
    executed_by: str = Field(
        default="finops_mcp",
        max_length=100,
        description="Actor: finops_mcp | n8n_workflow | human_ops",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional notes about the remediation decision",
    )
    estimated_savings_usd: Optional[float] = Field(
        default=None, ge=0,
        description="Expected monthly savings from this action (USD)",
    )

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, v: str) -> str:
        allowed = {"rightsize", "stop_idle", "switch_ri", "delete_unattached", "resize_storage"}
        if v not in allowed:
            raise ValueError(f"action_type must be one of: {', '.join(sorted(allowed))}")
        return v


class UpdateRemediationStatusInput(BaseModel):
    """Input for updating an existing remediation log entry."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    remediation_id: str = Field(
        ..., min_length=1, max_length=255,
        description="ID from finops_remediation_log table",
    )
    status: RemediationStatus = Field(
        ..., description="New status: pending | in_progress | completed | failed | skipped",
    )
    actual_savings_usd: Optional[float] = Field(
        default=None, ge=0,
        description="Actual savings realized after remediation (USD)",
    )
    notes: Optional[str] = Field(
        default=None, max_length=1000,
        description="Completion notes or failure reason",
    )


class GetRemediationHistoryInput(PaginationMixin):
    """Input for querying remediation history."""
    provider: Optional[CloudProvider] = Field(default=None)
    status: Optional[RemediationStatus] = Field(default=None)
    resource_id: Optional[str] = Field(
        default=None, max_length=255,
        description="Filter by resource ID",
    )


# ─────────────────────────── Tools ───────────────────────────

@mcp.tool(
    name="finops_get_cost_anomalies",
    annotations={
        "title": "Get Cost Anomalies",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def finops_get_cost_anomalies(params: GetAnomaliesInput, ctx: Context) -> str:
    """Fetch cost anomalies from finops_anomalies table with filtering and pagination.

    Returns detected cost spikes, unusual resource consumption patterns, and budget
    breaches across Azure, AWS, GCP, and OpenShift environments.

    Args:
        params (GetAnomaliesInput): Validated input containing:
            - provider (CloudProvider): Filter by cloud provider (default: all)
            - severity (Optional[Severity]): Filter by severity level
            - resource_id (Optional[str]): Filter by specific resource
            - limit (int): Max results 1-100 (default: 20)
            - offset (int): Pagination offset (default: 0)
            - response_format (ResponseFormat): markdown or json

    Returns:
        str: Anomaly list with severity, provider, resource, cost delta, and timestamp.
    """
    client = _get_client(ctx)
    filters: Dict[str, str] = {}

    if params.provider != CloudProvider.all:
        filters["provider"] = f"eq.{params.provider.value}"
    if params.severity:
        filters["severity"] = f"eq.{params.severity.value}"
    if params.resource_id:
        filters["resource_id"] = f"eq.{params.resource_id}"

    try:
        rows = await _supabase_select(
            client,
            table="finops_anomalies",
            select="id,provider,resource_id,resource_name,severity,anomaly_type,cost_delta_usd,baseline_cost_usd,detected_at,description",
            filters=filters,
            order="detected_at.desc",
            limit=params.limit,
            offset=params.offset,
        )
    except httpx.HTTPStatusError as e:
        return _handle_supabase_error(e.response, "get_cost_anomalies")
    except httpx.TimeoutException:
        return "Error [get_cost_anomalies]: Request timed out. Supabase may be overloaded."

    if params.response_format == ResponseFormat.json:
        return json.dumps({"anomalies": rows, "count": len(rows), "offset": params.offset}, indent=2)

    if not rows:
        return "✅ No cost anomalies found matching your filters."

    lines = [f"## 🚨 Cost Anomalies ({len(rows)} results)\n"]
    for r in rows:
        emoji = _severity_emoji(r.get("severity", ""))
        lines.append(
            f"### {emoji} {r.get('resource_name', r.get('resource_id', 'Unknown'))} "
            f"[{r.get('provider', '').upper()}]\n"
            f"- **ID**: `{r.get('id')}`\n"
            f"- **Severity**: {r.get('severity', 'N/A').upper()}\n"
            f"- **Type**: {r.get('anomaly_type', 'N/A')}\n"
            f"- **Cost Delta**: {_format_currency(r.get('cost_delta_usd'))} "
            f"(Baseline: {_format_currency(r.get('baseline_cost_usd'))})\n"
            f"- **Detected**: {r.get('detected_at', 'N/A')}\n"
            f"- **Details**: {r.get('description', 'N/A')}\n"
        )
    return "\n".join(lines)


@mcp.tool(
    name="finops_get_savings_recommendations",
    annotations={
        "title": "Get Savings Recommendations",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def finops_get_savings_recommendations(params: GetSavingsInput, ctx: Context) -> str:
    """Fetch Azure Advisor recommendations from azure_finops_recommendations_test_test table.

    Returns cost optimization recommendations pulled from Azure Advisor including
    Reserved Instance suggestions, Savings Plans, and rightsizing for VMs/PostgreSQL.

    Args:
        params (GetSavingsInput): Validated input containing:
            - provider (CloudProvider): Cloud provider filter (default: all)
            - min_savings_usd (Optional[float]): Minimum monthly savings threshold
            - category (Optional[str]): Category filter e.g. 'Cost'
            - limit (int): Max results (default: 20)
            - offset (int): Pagination offset
            - response_format (ResponseFormat): markdown or json

    Returns:
        str: Recommendations with savings, impact, SKU, region, subscription info.
    """
    client = _get_client(ctx)
    filters: Dict[str, str] = {}

    if params.category:
        filters["category"] = f"eq.{params.category}"
    if params.min_savings_usd is not None:
        filters["monthly_savings_usd"] = f"gte.{params.min_savings_usd}"
    # status=open only — ignore already actioned recs
    filters["status"] = "eq.open"

    try:
        recs = await _supabase_select(
            client,
            table="azure_finops_recommendations_test",
            select="id,recommendation_id,subscription_id,category,solution,impact,sku,resource_id,resource_type,region,quantity,term,lookback_days,monthly_savings_usd,annual_savings_usd,currency,vm_size,status,detected_at,last_updated_at",
            filters=filters,
            order="monthly_savings_usd.desc",
            limit=params.limit,
            offset=params.offset,
        )
    except httpx.HTTPStatusError as e:
        return _handle_supabase_error(e.response, "get_savings_recommendations")
    except httpx.TimeoutException:
        return "Error [get_savings_recommendations]: Request timed out."

    if params.response_format == ResponseFormat.json:
        total_monthly = sum(r.get("monthly_savings_usd") or 0 for r in recs)
        total_annual = sum(r.get("annual_savings_usd") or 0 for r in recs)
        return json.dumps(
            {
                "recommendations": recs,
                "count": len(recs),
                "total_monthly_savings_usd": total_monthly,
                "total_annual_savings_usd": total_annual,
            },
            indent=2,
        )

    if not recs:
        return "✅ No open Azure Advisor recommendations found matching your filters."

    total_monthly = sum(r.get("monthly_savings_usd") or 0 for r in recs)
    total_annual = sum(r.get("annual_savings_usd") or 0 for r in recs)

    lines = [
        f"## 💰 Azure Advisor Recommendations ({len(recs)} results)\n",
        f"- **Total Monthly Savings**: {_format_currency(total_monthly)}",
        f"- **Total Annual Savings**: {_format_currency(total_annual)}\n",
    ]
    for r in recs:
        impact = r.get("impact", "")
        impact_emoji = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(impact, "⚪")
        currency = r.get("currency", "USD")
        lines.append(
            f"### {impact_emoji} {r.get('solution', 'Recommendation')}\n"
            f"- **Rec ID**: `{r.get('recommendation_id', r.get('id'))}`\n"
            f"- **Resource Type**: {r.get('resource_type', 'N/A')} | **Region**: {r.get('region', 'N/A')}\n"
            f"- **SKU**: `{r.get('sku', 'N/A')}` | **VM Size**: `{r.get('vm_size', 'N/A')}`\n"
            f"- **Subscription**: `{r.get('subscription_id', 'N/A')}`\n"
            f"- **Impact**: {impact} | **Term**: {r.get('term', 'N/A')} | **Qty**: {r.get('quantity', 'N/A')}\n"
            f"- **Monthly Savings**: {_format_currency(r.get('monthly_savings_usd'))} {currency} "
            f"| **Annual**: {_format_currency(r.get('annual_savings_usd'))} {currency}\n"
            f"- **Lookback**: {r.get('lookback_days', 'N/A')} days | **Status**: {r.get('status', 'N/A')}\n"
            f"- **Detected**: {r.get('detected_at', 'N/A')}\n"
        )
    return "\n".join(lines)


@mcp.tool(
    name="finops_get_ai_insights",
    annotations={
        "title": "Get AI Cost Insights",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def finops_get_ai_insights(params: GetInsightsInput, ctx: Context) -> str:
    """Retrieve Claude-generated AI insights from finops_ai_insights table.

    Returns AI-enriched analysis including anomaly explanations, optimization strategies,
    cost forecasts, and trend analysis generated by the n8n FinOps workflows.

    Args:
        params (GetInsightsInput): Validated input containing:
            - provider (CloudProvider): Cloud provider filter
            - insight_type (Optional[str]): Type filter
            - limit/offset: Pagination
            - response_format: markdown or json

    Returns:
        str: AI insights with confidence scores, recommendations, and metadata.
    """
    client = _get_client(ctx)
    filters: Dict[str, str] = {}

    if params.provider != CloudProvider.all:
        filters["provider"] = f"eq.{params.provider.value}"
    if params.insight_type:
        filters["insight_type"] = f"eq.{params.insight_type}"

    try:
        insights = await _supabase_select(
            client,
            table="finops_ai_insights",
            select="id,provider,insight_type,title,summary,detailed_analysis,confidence_score,affected_resources,potential_savings_usd,generated_at",
            filters=filters,
            order="generated_at.desc",
            limit=params.limit,
            offset=params.offset,
        )
    except httpx.HTTPStatusError as e:
        return _handle_supabase_error(e.response, "get_ai_insights")
    except httpx.TimeoutException:
        return "Error [get_ai_insights]: Request timed out."

    if params.response_format == ResponseFormat.json:
        return json.dumps({"insights": insights, "count": len(insights)}, indent=2)

    if not insights:
        return "ℹ️ No AI insights found. Run n8n FinOps analysis workflows to generate insights."

    lines = [f"## 🤖 AI Cost Insights ({len(insights)} results)\n"]
    for ins in insights:
        conf = ins.get("confidence_score")
        conf_str = f"{conf:.0%}" if conf is not None else "N/A"
        lines.append(
            f"### 💡 {ins.get('title', 'Insight')} [{ins.get('provider', '').upper()}]\n"
            f"- **ID**: `{ins.get('id')}`\n"
            f"- **Type**: {ins.get('insight_type', 'N/A')}\n"
            f"- **Confidence**: {conf_str}\n"
            f"- **Potential Savings**: {_format_currency(ins.get('potential_savings_usd'))}/month\n"
            f"- **Summary**: {ins.get('summary', 'N/A')}\n"
            f"- **Analysis**: {ins.get('detailed_analysis', 'N/A')}\n"
            f"- **Generated**: {ins.get('generated_at', 'N/A')}\n"
        )
    return "\n".join(lines)


@mcp.tool(
    name="finops_rightsizing_analysis",
    annotations={
        "title": "Rightsizing Analysis for Resource",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def finops_rightsizing_analysis(params: RightsizingInput, ctx: Context) -> str:
    """Perform rightsizing analysis for a specific cloud resource.

    Queries finops_recommendations and finops_anomalies for the given resource,
    then returns a consolidated rightsizing report with current vs recommended
    configuration and expected savings.

    Args:
        params (RightsizingInput): Validated input containing:
            - resource_id (str): Target resource identifier
            - provider (CloudProvider): Cloud provider
            - current_sku (Optional[str]): Current SKU/instance type
            - response_format (ResponseFormat): Output format

    Returns:
        str: Rightsizing report with current config, recommended config, savings estimate,
             utilization data, and related anomalies for the resource.
    """
    client = _get_client(ctx)
    resource_filter = {"resource_id": f"eq.{params.resource_id}"}
    if params.provider != CloudProvider.all:
        resource_filter["provider"] = f"eq.{params.provider.value}"

    try:
        recs, anomalies = await _parallel_fetch(
            client,
            [
                ("azure_finops_recommendations_test", "id,recommendation_id,solution,impact,sku,vm_size,resource_type,region,monthly_savings_usd,annual_savings_usd,currency,term,status,detected_at", resource_filter),
                ("finops_anomalies", "id,severity,anomaly_type,cost_delta_usd,detected_at,description", resource_filter),
            ],
        )
    except httpx.HTTPStatusError as e:
        return _handle_supabase_error(e.response, "rightsizing_analysis")
    except httpx.TimeoutException:
        return "Error [rightsizing_analysis]: Request timed out."

    if params.response_format == ResponseFormat.json:
        return json.dumps(
            {
                "resource_id": params.resource_id,
                "provider": params.provider.value,
                "current_sku": params.current_sku,
                "recommendations": recs,
                "anomalies": anomalies,
            },
            indent=2,
        )

    total_monthly = sum(r.get("monthly_savings_usd") or 0 for r in recs)
    lines = [
        f"## 🔍 Rightsizing Analysis: `{params.resource_id}`\n",
        f"- **Provider**: {params.provider.value.upper()}",
        f"- **Current SKU**: {params.current_sku or 'Not specified'}",
        f"- **Total Monthly Savings**: {_format_currency(total_monthly)}\n",
    ]

    if recs:
        lines.append(f"### 📋 Azure Advisor Recommendations ({len(recs)})\n")
        for r in recs:
            impact = r.get("impact", "")
            impact_emoji = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(impact, "⚪")
            lines.append(
                f"{impact_emoji} **{r.get('solution', 'Optimization')}**\n"
                f"- SKU: `{r.get('sku', 'N/A')}` | VM Size: `{r.get('vm_size', 'N/A')}`\n"
                f"- Monthly: {_format_currency(r.get('monthly_savings_usd'))} | Annual: {_format_currency(r.get('annual_savings_usd'))}\n"
                f"- Term: {r.get('term', 'N/A')} | Region: {r.get('region', 'N/A')}\n"
                f"- Rec ID: `{r.get('recommendation_id', r.get('id'))}` _(use for apply_remediation)_\n"
            )
    else:
        lines.append("✅ No Azure Advisor recommendations for this resource.\n")

    if anomalies:
        lines.append(f"### ⚠️ Related Anomalies ({len(anomalies)})\n")
        for a in anomalies:
            emoji = _severity_emoji(a.get("severity", ""))
            lines.append(
                f"{emoji} {a.get('anomaly_type', 'N/A')} — "
                f"Delta: {_format_currency(a.get('cost_delta_usd'))} "
                f"(Detected: {a.get('detected_at', 'N/A')})\n"
            )

    return "\n".join(lines)


@mcp.tool(
    name="finops_apply_remediation",
    annotations={
        "title": "Apply FinOps Remediation",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def finops_apply_remediation(params: ApplyRemediationInput, ctx: Context) -> str:
    """Log and initiate a FinOps remediation action in finops_remediation_log.

    Creates a remediation record for rightsizing, idle resource shutdown, Reserved Instance
    switch, or storage cleanup. This logs the intent and sets status to 'pending' for
    downstream n8n workflows to execute the actual cloud API calls.

    Args:
        params (ApplyRemediationInput): Validated input containing:
            - recommendation_id (str): Source recommendation ID from finops_recommendations
            - action_type (str): rightsize | stop_idle | switch_ri | delete_unattached | resize_storage
            - resource_id (str): Target resource to remediate
            - provider (CloudProvider): Cloud provider
            - executed_by (str): Actor initiating remediation (default: finops_mcp)
            - notes (Optional[str]): Decision rationale
            - estimated_savings_usd (Optional[float]): Expected monthly savings

    Returns:
        str: Confirmation with remediation log ID for status tracking.
    """
    client = _get_client(ctx)

    record = {
        "recommendation_id": params.recommendation_id,
        "action_type": params.action_type,
        "resource_id": params.resource_id,
        "provider": params.provider.value,
        "executed_by": params.executed_by,
        "status": "pending",
        "notes": params.notes,
        "estimated_savings_usd": params.estimated_savings_usd,
        "initiated_at": _now_iso(),
    }

    try:
        await ctx.log_info("Logging remediation", {"resource": params.resource_id, "action": params.action_type})
        result = await _supabase_insert(client, "finops_remediation_log", record)
    except httpx.HTTPStatusError as e:
        return _handle_supabase_error(e.response, "apply_remediation")
    except httpx.TimeoutException:
        return "Error [apply_remediation]: Request timed out. Remediation NOT logged."

    rem_id = result.get("id", "unknown")
    return (
        f"## ✅ Remediation Logged\n\n"
        f"- **Remediation ID**: `{rem_id}` _(use for status updates)_\n"
        f"- **Resource**: `{params.resource_id}` [{params.provider.value.upper()}]\n"
        f"- **Action**: `{params.action_type}`\n"
        f"- **Status**: `pending` — awaiting n8n workflow execution\n"
        f"- **Estimated Savings**: {_format_currency(params.estimated_savings_usd)}/month\n"
        f"- **Executed By**: {params.executed_by}\n"
        f"- **Notes**: {params.notes or 'None'}\n\n"
        f"Next step: Use `finops_update_remediation_status` with ID `{rem_id}` to track progress."
    )


@mcp.tool(
    name="finops_update_remediation_status",
    annotations={
        "title": "Update Remediation Status",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def finops_update_remediation_status(params: UpdateRemediationStatusInput, ctx: Context) -> str:
    """Update the status of an existing remediation log entry.

    Used by n8n workflows or human operators to mark remediations as completed,
    failed, or in_progress, and record actual savings realized.

    Args:
        params (UpdateRemediationStatusInput): Validated input containing:
            - remediation_id (str): ID from finops_remediation_log
            - status (RemediationStatus): New status value
            - actual_savings_usd (Optional[float]): Realized savings after completion
            - notes (Optional[str]): Completion notes or failure reason

    Returns:
        str: Confirmation of status update with savings comparison.
    """
    client = _get_client(ctx)

    update_data: Dict[str, Any] = {
        "status": params.status.value,
        "updated_at": _now_iso(),
    }
    if params.actual_savings_usd is not None:
        update_data["actual_savings_usd"] = params.actual_savings_usd
    if params.notes:
        update_data["notes"] = params.notes
    if params.status == RemediationStatus.completed:
        update_data["completed_at"] = _now_iso()

    try:
        await _supabase_patch(client, "finops_remediation_log", params.remediation_id, update_data)
    except httpx.HTTPStatusError as e:
        return _handle_supabase_error(e.response, "update_remediation_status")
    except httpx.TimeoutException:
        return "Error [update_remediation_status]: Request timed out."

    status_emoji = {
        "completed": "✅", "failed": "❌", "in_progress": "🔄",
        "pending": "⏳", "skipped": "⏭️",
    }.get(params.status.value, "⚪")

    return (
        f"## {status_emoji} Remediation Status Updated\n\n"
        f"- **ID**: `{params.remediation_id}`\n"
        f"- **New Status**: `{params.status.value}`\n"
        f"- **Actual Savings**: {_format_currency(params.actual_savings_usd)}/month\n"
        f"- **Notes**: {params.notes or 'None'}\n"
        f"- **Updated At**: {update_data['updated_at']}\n"
    )


@mcp.tool(
    name="finops_get_remediation_history",
    annotations={
        "title": "Get Remediation History",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def finops_get_remediation_history(params: GetRemediationHistoryInput, ctx: Context) -> str:
    """Retrieve remediation history from finops_remediation_log with filtering.

    Returns past and ongoing remediation actions with status, savings realized,
    and timeline for audit and reporting purposes.

    Args:
        params (GetRemediationHistoryInput): Validated input containing:
            - provider (Optional[CloudProvider]): Filter by provider
            - status (Optional[RemediationStatus]): Filter by status
            - resource_id (Optional[str]): Filter by resource
            - limit/offset: Pagination
            - response_format: markdown or json

    Returns:
        str: Remediation history with totals for estimated vs actual savings.
    """
    client = _get_client(ctx)
    filters: Dict[str, str] = {}

    if params.provider and params.provider != CloudProvider.all:
        filters["provider"] = f"eq.{params.provider.value}"
    if params.status:
        filters["status"] = f"eq.{params.status.value}"
    if params.resource_id:
        filters["resource_id"] = f"eq.{params.resource_id}"

    try:
        rows = await _supabase_select(
            client,
            table="finops_remediation_log",
            select="id,provider,resource_id,action_type,status,executed_by,estimated_savings_usd,actual_savings_usd,initiated_at,completed_at,notes",
            filters=filters,
            order="initiated_at.desc",
            limit=params.limit,
            offset=params.offset,
        )
    except httpx.HTTPStatusError as e:
        return _handle_supabase_error(e.response, "get_remediation_history")
    except httpx.TimeoutException:
        return "Error [get_remediation_history]: Request timed out."

    if params.response_format == ResponseFormat.json:
        total_estimated = sum(r.get("estimated_savings_usd", 0) or 0 for r in rows)
        total_actual = sum(r.get("actual_savings_usd", 0) or 0 for r in rows)
        return json.dumps(
            {
                "remediations": rows,
                "count": len(rows),
                "total_estimated_savings_usd": total_estimated,
                "total_actual_savings_usd": total_actual,
            },
            indent=2,
        )

    if not rows:
        return "ℹ️ No remediation history found matching your filters."

    total_estimated = sum(r.get("estimated_savings_usd", 0) or 0 for r in rows)
    total_actual = sum(r.get("actual_savings_usd", 0) or 0 for r in rows)

    lines = [
        f"## 📜 Remediation History ({len(rows)} records)\n",
        f"- **Total Estimated Savings**: {_format_currency(total_estimated)}/month",
        f"- **Total Actual Savings**: {_format_currency(total_actual)}/month\n",
    ]

    status_emoji_map = {
        "completed": "✅", "failed": "❌", "in_progress": "🔄",
        "pending": "⏳", "skipped": "⏭️",
    }

    for r in rows:
        s_emoji = status_emoji_map.get(r.get("status", ""), "⚪")
        lines.append(
            f"### {s_emoji} `{r.get('id')}` — {r.get('action_type', 'N/A')} [{r.get('provider', '').upper()}]\n"
            f"- **Resource**: `{r.get('resource_id')}`\n"
            f"- **Status**: {r.get('status')}\n"
            f"- **By**: {r.get('executed_by', 'N/A')}\n"
            f"- **Savings**: Est. {_format_currency(r.get('estimated_savings_usd'))} → "
            f"Actual {_format_currency(r.get('actual_savings_usd'))}\n"
            f"- **Initiated**: {r.get('initiated_at', 'N/A')} | "
            f"**Completed**: {r.get('completed_at', 'N/A')}\n"
            f"- **Notes**: {r.get('notes', 'None')}\n"
        )

    return "\n".join(lines)


# ─────────────────────────── Parallel Fetch Helper ───────────────────────────

async def _parallel_fetch(
    client: httpx.AsyncClient,
    queries: List[tuple],  # (table, select, filters)
) -> List[List[Dict[str, Any]]]:
    """Run multiple Supabase SELECT calls concurrently."""
    import asyncio

    async def _fetch(table, select, filters):
        return await _supabase_select(
            client, table=table, select=select, filters=filters, limit=50
        )

    results = await asyncio.gather(*[_fetch(*q) for q in queries])
    return list(results)


# ─────────────────────────── Entry Point ───────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    mcp.run(transport="streamable-http", host=host, port=port)
