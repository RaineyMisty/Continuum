"""Runnable before and after modernization; its result is an explicit contract."""
import json
import legacy_orders as orders


def main():
    orders.reset()
    orders.add_user('demo', 'Ada', 'vip')
    order = orders.create_order('demo', [{'sku': 'book', 'qty': 2, 'price': '60.00'}], 'express', 'SAVE10')
    orders.pay_order(order, 'payment-demo')
    report = orders.sales_report()
    assert report == {'payments': 1, 'refunds': 0, 'net_revenue': '110.00'}
    print(json.dumps({'order': order, 'report': report}, sort_keys=True))


if __name__ == '__main__':
    main()
