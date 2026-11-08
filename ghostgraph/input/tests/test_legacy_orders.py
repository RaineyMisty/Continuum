import pytest
import legacy_orders as l


@pytest.fixture(autouse=True)
def reset_state():
    l.reset()


def test_quote_vip_coupon_and_shipping():
    l.add_user("u1", "Ada", "vip")
    q = l.price_quote("u1", [{"sku": "a", "qty": 2, "price": "60.00"}], "express", "SAVE10")
    assert q == {"subtotal": "120.00", "discount": "22.00", "shipping": "12.00", "total": "110.00"}


def test_full_order_and_report():
    l.add_user("u1", "Ada")
    oid = l.create_order("u1", [{"sku": "x", "qty": 1, "price": "20.25"}])
    assert oid == "O-1001"
    assert l.get_order(oid)["status"] == "PENDING"
    assert l.pay_order(oid, "p1")["status"] == "PAID"
    assert l.pay_order(oid, "p1")["status"] == "PAID"
    assert l.sales_report() == {"payments": 1, "refunds": 0, "net_revenue": "25.25"}
    assert l.ledger_for_order(oid)[0]["type"] == "PAYMENT"


def test_refund_idempotency():
    l.add_user("u1", "Ada")
    oid = l.create_order("u1", [{"sku": "x", "qty": 1, "price": 1}])
    l.pay_order(oid, "p1")
    assert l.refund_order(oid)["status"] == "REFUNDED"
    assert l.refund_order(oid)["status"] == "REFUNDED"
    assert l.sales_report() == {"payments": 1, "refunds": 1, "net_revenue": "0.00"}


def test_duplicate_payment_rejected():
    l.add_user("u1", "Ada")
    o1 = l.create_order("u1", [{"sku": "a", "qty": 1, "price": 5}])
    o2 = l.create_order("u1", [{"sku": "b", "qty": 1, "price": 5}])
    l.pay_order(o1, "p1")
    with pytest.raises(ValueError):
        l.pay_order(o2, "p1")


def test_failed_payment_is_not_ledgered():
    l.add_user("u1", "Ada")
    oid = l.create_order("u1", [{"sku": "a", "qty": 1, "price": 5}])
    assert l.pay_order(oid, "p1", "paid")["status"] == "PAYMENT_FAILED"
    assert not l.ledger_for_order(oid)


def test_legacy_edge_cases():
    l.add_user("u1", "Ada")
    with pytest.raises(ValueError):
        l.create_order("u1", [])
    with pytest.raises(ValueError):
        l.price_quote("u1", [{"sku": "a", "qty": 0, "price": 1}])
    l.set_user_active("u1", False)
    with pytest.raises(ValueError):
        l.price_quote("u1", [{"sku": "a", "qty": 1, "price": 1}])


def test_export_api_shape():
    l.add_user("u1", "Ada")
    oid = l.create_order("u1", [{"sku": "a", "qty": 1, "price": 2}])
    csv = l.export_csv()
    assert csv.startswith("order_id,user_id,status,total,payment_id\n")
    assert oid in csv
