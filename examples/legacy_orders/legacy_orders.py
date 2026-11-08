"""Old order processing code, kept intentionally procedural and stateful.

This is a runnable demo project, not a realistic production financial system.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

USERS = {}
ORDERS = {}
LEDGER = []
EVENTS = []
SEQUENCE = [1000]
FEES = {"standard": Decimal("5.00"), "express": Decimal("12.00")}


def reset():
    USERS.clear()
    ORDERS.clear()
    LEDGER.clear()
    EVENTS.clear()
    SEQUENCE[0] = 1000


def add_user(user_id, name, tier="regular"):
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("bad user id")
    if user_id in USERS:
        raise ValueError("duplicate user")
    if tier not in ("regular", "vip"):
        raise ValueError("bad tier")
    USERS[user_id] = {"id": user_id, "name": name, "tier": tier, "active": True}
    EVENTS.append(("user_created", user_id))
    return dict(USERS[user_id])


def set_user_active(user_id, active):
    if user_id not in USERS:
        raise KeyError(user_id)
    USERS[user_id]["active"] = bool(active)
    EVENTS.append(("user_active", user_id, bool(active)))
    return bool(active)


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _price(lines):
    result = Decimal("0.00")
    for line in lines:
        if "sku" not in line or not line["sku"]:
            raise ValueError("missing sku")
        if int(line.get("qty", 0)) < 1:
            raise ValueError("bad qty")
        if _money(line.get("price", 0)) < 0:
            raise ValueError("bad price")
        result += _money(line["price"]) * int(line["qty"])
    return result.quantize(Decimal("0.01"))


def price_quote(user_id, lines, shipping="standard", coupon=None):
    user = USERS[user_id]
    if not user["active"]:
        raise ValueError("inactive user")
    if shipping not in FEES:
        raise ValueError("bad shipping")
    subtotal = _price(lines)
    discount = Decimal("0")
    if user["tier"] == "vip":
        discount += (subtotal * Decimal("0.10"))
    if coupon == "SAVE5":
        discount += Decimal("5.00")
    if coupon == "SAVE10" and subtotal >= Decimal("100.00"):
        discount += Decimal("10.00")
    if discount > subtotal:
        discount = subtotal
    total = (subtotal - discount + FEES[shipping]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"subtotal": str(subtotal), "discount": str(_money(discount)),
            "shipping": str(FEES[shipping]), "total": str(total)}


def create_order(user_id, lines, shipping="standard", coupon=None):
    if user_id not in USERS:
        raise KeyError(user_id)
    if not lines:
        raise ValueError("empty order")
    quote = price_quote(user_id, lines, shipping, coupon)
    SEQUENCE[0] += 1
    order_id = "O-" + str(SEQUENCE[0])
    ORDERS[order_id] = {"id": order_id, "user_id": user_id, "lines": list(lines),
                        "quote": quote, "status": "PENDING", "payment_id": None,
                        "shipping": shipping, "coupon": coupon, "created": "2014-03-20"}
    EVENTS.append(("order_created", order_id))
    return order_id


def get_order(order_id):
    if order_id not in ORDERS:
        raise KeyError(order_id)
    data = dict(ORDERS[order_id])
    data["lines"] = list(data["lines"])
    data["quote"] = dict(data["quote"])
    return data


def pay_order(order_id, payment_id, status="SETTLED"):
    if order_id not in ORDERS:
        raise KeyError(order_id)
    order = ORDERS[order_id]
    if order["status"] == "PAID":
        if order["payment_id"] == payment_id:
            return get_order(order_id)
        raise ValueError("payment already recorded")
    if order["status"] != "PENDING":
        raise ValueError("order not pending")
    if status != "SETTLED":
        order["status"] = "PAYMENT_FAILED"
        EVENTS.append(("payment_failed", order_id, status))
        return get_order(order_id)
    if not payment_id:
        raise ValueError("missing payment id")
    for entry in LEDGER:
        if entry["payment_id"] == payment_id:
            raise ValueError("duplicate payment id")
    order["payment_id"] = payment_id
    order["status"] = "PAID"
    LEDGER.append({"order_id": order_id, "payment_id": payment_id,
                   "amount": order["quote"]["total"], "type": "PAYMENT"})
    EVENTS.append(("payment_recorded", order_id))
    return get_order(order_id)


def refund_order(order_id, reason="customer_request"):
    if order_id not in ORDERS:
        raise KeyError(order_id)
    order = ORDERS[order_id]
    if order["status"] == "REFUNDED":
        return get_order(order_id)
    if order["status"] != "PAID":
        raise ValueError("only paid orders can be refunded")
    order["status"] = "REFUNDED"
    LEDGER.append({"order_id": order_id, "payment_id": order["payment_id"],
                   "amount": "-" + order["quote"]["total"], "type": "REFUND",
                   "reason": reason})
    EVENTS.append(("order_refunded", order_id))
    return get_order(order_id)


def ledger_for_order(order_id):
    return [dict(r) for r in LEDGER if r["order_id"] == order_id]


def sales_report():
    paid_count = 0
    refunded_count = 0
    total_paid = Decimal("0")
    total_refunded = Decimal("0")
    for entry in LEDGER:
        if entry["type"] == "PAYMENT":
            paid_count += 1
            total_paid += _money(entry["amount"])
        if entry["type"] == "REFUND":
            refunded_count += 1
            total_refunded += _money(entry["amount"])
    return {"payments": paid_count, "refunds": refunded_count,
            "net_revenue": str(_money(total_paid + total_refunded))}


def export_csv():
    rows = ["order_id,user_id,status,total,payment_id"]
    for order_id in sorted(ORDERS):
        order = ORDERS[order_id]
        rows.append(",".join([order_id, order["user_id"], order["status"],
                              order["quote"]["total"], order["payment_id"] or ""]))
    return "\n".join(rows) + "\n"


def event_count(event_type):
    return sum(1 for event in EVENTS if event[0] == event_type)
