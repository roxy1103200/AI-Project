"""Validate and render Java's user-scoped payment/refund facts without model inference."""

from typing import Any

ORDER_CONTRACT = "cinema-order-v2"
ORDER_STATES = {"UNPAID", "PAID", "ISSUED", "REFUNDING", "REFUNDED", "CANCELLED"}
PAYMENT_STATES = {"NOT_STARTED", "INIT", "PAYING", "SUCCESS", "CLOSING", "CLOSED"}
REFUND_STATES = {None, "PENDING", "UNKNOWN", "REFUNDED"}
LABELS = {
    "UNPAID": "待支付",
    "PAID": "已支付，等待出票",
    "ISSUED": "已出票",
    "REFUNDING": "退款处理中，电影票暂不可使用",
    "REFUNDED": "已退款，电影票已失效",
    "CANCELLED": "已取消",
}


def valid_order_contract(order: Any) -> bool:
    """Reject incomplete or contradictory financial states; unknown is never success."""
    if not isinstance(order, dict) or order.get("contract_version") != ORDER_CONTRACT:
        return False
    required = {
        "status",
        "payment_status",
        "refund_status",
        "refund_reason_type",
        "can_refund",
        "refund_reason",
        "server_time",
    }
    if (
        not required.issubset(order)
        or type(order["can_refund"]) is not bool
        or not isinstance(order["refund_reason"], str)
    ):
        return False
    status, payment, refund, reason = (
        order.get(key) for key in ("status", "payment_status", "refund_status", "refund_reason_type")
    )
    if not isinstance(status, str) or not isinstance(payment, str):
        return False
    if any(value is not None and not isinstance(value, str) for value in (refund, reason)):
        return False
    if (
        status not in ORDER_STATES
        or payment not in PAYMENT_STATES
        or refund not in REFUND_STATES
        or reason not in {None, "CUSTOMER", "LATE_PAYMENT"}
    ):
        return False
    if order["can_refund"] and (status != "ISSUED" or payment != "SUCCESS" or refund is not None):
        return False
    if status in {"PAID", "ISSUED", "REFUNDING", "REFUNDED"} and payment != "SUCCESS":
        return False
    if (refund is None) != (reason is None):
        return False
    if reason == "CUSTOMER" and status != ("REFUNDED" if refund == "REFUNDED" else "REFUNDING"):
        return False
    if status == "UNPAID" and payment in {"SUCCESS", "CLOSED"}:
        return False
    if status == "REFUNDING" and (payment != "SUCCESS" or refund not in {"PENDING", "UNKNOWN"}):
        return False
    if status == "REFUNDED" and refund != "REFUNDED":
        return False
    if payment == "CLOSING" and status != "UNPAID":
        return False
    return not (reason == "LATE_PAYMENT" and (status != "CANCELLED" or payment != "SUCCESS" or refund is None))


def order_answer(order: dict[str, Any]) -> str:
    status = order.get("status")
    label = (
        "关单处理中，尚未确认取消" if order.get("payment_status") == "CLOSING" else LABELS.get(status, "状态暂无法确认")
    )
    lines = [
        f"订单：{order.get('order_no', '')}",
        f"影片：{order.get('movie_title', '')}",
        f"状态：{label}",
        f"开场：{order.get('start_time', '')}（北京时间）",
        f"金额：¥{order.get('total_amount', '')}",
        f"座位：{'、'.join(item.get('seat_code', '') for item in order.get('items', []))}",
        f"退票：{order.get('refund_reason', '暂时无法确认，请查看订单页面')}",
    ]
    if order.get("refund_status") == "UNKNOWN":
        lines.append("渠道退款结果仍在核对，目前无法确认到账时间。")
    if order.get("refund_deadline"):
        lines.append(f"退票截止：{order['refund_deadline']}（北京时间）")
    lines.append("如需操作，请前往我的订单。")
    return "\n".join(lines)
