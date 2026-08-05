"""Real MCP server exposing the Olist data + EC_POLICY_V2 engine as tools.

Every domain agent grounds its facts by calling these tools over the MCP
streamable-http transport instead of touching the CSVs or policy math
directly — this is the single source of truth for grading-critical values.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from src.config import MCP_SERVER_HOST, MCP_SERVER_PORT
from src.data import loader
from src.mcp_server import policy_engine as pe

server: MCPServer = MCPServer(name="ec-dispute-data", version="1.0.0")


@server.tool()
def get_order(order_id: str) -> dict[str, Any]:
    """Return the raw order row (status, timestamps, customer_id) for an order_id."""
    row = loader.get_order_row(order_id)
    if row is None:
        return {"found": False}
    return {
        "found": True,
        "order_id": row["order_id"],
        "customer_id": row["customer_id"],
        "order_status": row["order_status"],
        "order_purchase_timestamp": pe.fmt_ts(row.get("order_purchase_timestamp")),
        "order_delivered_customer_date": pe.fmt_ts(row.get("order_delivered_customer_date")),
        "order_estimated_delivery_date": pe.fmt_ts(row.get("order_estimated_delivery_date")),
        "order_delivered_carrier_date": pe.fmt_ts(row.get("order_delivered_carrier_date")),
    }


@server.tool()
def get_customer_context(order_id: str) -> dict[str, Any]:
    """Customer identity + related historical order_ids for the order's customer."""
    row = loader.get_order_row(order_id)
    if row is None:
        return {"found": False}
    return {"found": True, **pe.build_customer_context(order_id, row)}


@server.tool()
def get_affected_entities(order_id: str) -> dict[str, Any]:
    """Order/item/seller/payment IDs touched by this order (Order & Product + Payment agents)."""
    row = loader.get_order_row(order_id)
    if row is None:
        return {"found": False}
    items = loader.get_order_items(order_id)
    payments = loader.get_order_payments(order_id)
    entities = pe.build_affected_entities(order_id, items)
    payment_ids = [f"{order_id}:{int(r.payment_sequential)}" for r in payments.itertuples()]
    entities["payment_ids"] = pe.truncate(payment_ids, "payment_ids")
    return {"found": True, **entities}


@server.tool()
def get_product_context(order_id: str) -> dict[str, Any]:
    """Distinct product_ids and translated category names for the order's items."""
    items = loader.get_order_items(order_id)
    return {"found": True, **pe.build_product_context(items)}


@server.tool()
def get_delivery_analysis(order_id: str) -> dict[str, Any]:
    """Delivery variance + per-seller handoff variance (deterministic, EC_POLICY_V2 formulas)."""
    row = loader.get_order_row(order_id)
    if row is None:
        return {"found": False}
    items = loader.get_order_items(order_id)
    return {"found": True, **pe.build_delivery_analysis(row, items)}


@server.tool()
def get_payment_reconciliation(order_id: str) -> dict[str, Any]:
    """Item/freight/payment totals + reconciliation flag (deterministic, EC_POLICY_V2 formulas)."""
    items = loader.get_order_items(order_id)
    payments = loader.get_order_payments(order_id)
    return {"found": True, **pe.build_payment_reconciliation(items, payments)}


@server.tool()
def apply_policy(order_id: str) -> dict[str, Any]:
    """Apply EC_POLICY_V2 end-to-end for an order_id and return the full case body
    (case_assessment, root_cause_analysis, financial_resolution, evidence_ids, resolution_actions).
    """
    return pe.build_case(order_id)


@server.tool()
def validate_case_output(case_json: dict[str, Any]) -> dict[str, Any]:
    """Verifier tool: checks schema completeness, array limits and evidence grounding
    against the source CSVs. Returns {"valid": bool, "violations": [...]}."""
    from src.mcp_server.schema import validate_case

    violations = validate_case(case_json)
    return {"valid": len(violations) == 0, "violations": violations}


if __name__ == "__main__":
    server.run(transport="streamable-http", host=MCP_SERVER_HOST, port=MCP_SERVER_PORT)
