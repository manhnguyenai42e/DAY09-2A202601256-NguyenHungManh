"""Order & Product Agent: LLM agent for order/item/seller entities and
product/category context. It reads raw item + product rows and must itself
dedupe IDs, format item_ids, and cap every array — none of that is done for it."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, mcp_session
from src.config import LIMITS, agent_url

ALLOWED_TOOLS = ["get_order_items", "get_products"]

SYSTEM = (
    "Bạn là Order & Product Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: xác định cấu trúc đơn hàng (item, seller) và bối cảnh sản phẩm (ngành hàng), "
    "hoàn toàn tự mình tính toán và định dạng — không có công cụ nào làm sẵn hộ bạn.\n\n"
    "Quy trình bắt buộc:\n"
    "1. Gọi get_order_items(order_id) để lấy các dòng item thô (order_item_id, product_id, "
    "seller_id, price, freight_value, shipping_limit_date).\n"
    "2. Tự dựng item_ids theo đúng định dạng \"<order_id>:<order_item_id>\" cho từng dòng "
    f"(giữ nguyên thứ tự dữ liệu gốc, tối đa {LIMITS['item_ids']}).\n"
    f"3. Tự lọc seller_id trùng lặp (giữ thứ tự xuất hiện đầu tiên, tối đa {LIMITS['seller_ids']}) "
    f"và product_id trùng lặp (tối đa {LIMITS['product_ids']}).\n"
    "4. Gọi get_products(product_ids) với danh sách product_id vừa lọc để lấy "
    "product_category_name thô cho từng sản phẩm.\n"
    f"5. Tự lọc category_name trùng lặp (giữ thứ tự xuất hiện đầu tiên, tối đa {LIMITS['category_names']}), "
    "giữ NGUYÊN VĂN tên tiếng Bồ Đào Nha trong CSV, không dịch.\n"
    "6. Gọi report_order_product với các danh sách đã tự dựng và 1-2 câu tiếng Việt nhận định "
    "về độ phức tạp của đơn (nhiều item/seller/ngành hàng thì xử lý phức tạp hơn)."
)

FINAL_TOOL = {
    "name": "report_order_product",
    "description": "Nộp kết quả cuối cùng về item/seller/product/category của đơn hàng.",
    "parameters": {
        "type": "object",
        "properties": {
            "item_ids": {"type": "array", "items": {"type": "string"}, "maxItems": LIMITS["item_ids"]},
            "seller_ids": {"type": "array", "items": {"type": "string"}, "maxItems": LIMITS["seller_ids"]},
            "product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": LIMITS["product_ids"]},
            "category_names": {"type": "array", "items": {"type": "string"}, "maxItems": LIMITS["category_names"]},
            "rationale": {"type": "string", "description": "1-2 câu tiếng Việt nhận định."},
        },
        "required": ["item_ids", "seller_ids", "product_ids", "category_names", "rationale"],
    },
}

CARD = AgentCard(
    name="order-product-agent",
    description="Resolves order/item/seller entities and product/category context.",
    url=agent_url("order_product"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]

    async with mcp_session() as session:
        args, chosen = await agent_tool_loop(
            SYSTEM, f"Điều tra khiếu nại cho đơn hàng có order_id = {order_id}.",
            ALLOWED_TOOLS, FINAL_TOOL, session,
        )

    item_ids = args.get("item_ids", [])
    evidence = [f"order:{order_id}"] + [f"item:{i}" for i in item_ids]
    missing = [] if item_ids else ["no item rows found for this order"]
    facts = {
        "affected_entities": {
            "item_ids": item_ids,
            "seller_ids": args.get("seller_ids", []),
        },
        "product_context": {
            "product_ids": args.get("product_ids", []),
            "category_names": args.get("category_names", []),
        },
        "tools_called_by_llm": chosen,
    }
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="order_product",
        question=payload.question,
        facts=facts,
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
        note=args.get("rationale", ""),
    )


app = build_agent_app(CARD, handle)
