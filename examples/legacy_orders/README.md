# Legacy Orders (toy but real Python program)

A deliberately tangled legacy app with shared mutable state, 2014-style procedural code,
manual string flags, duplicated billing/report rules, and a public API protected by tests.
Modernization task: improve modularity without changing the externally observed results.
Run `python -m pytest -q` from this directory. No live services are required.

Run `python demo.py` for a complete order/payment scenario, with expected revenue
`110.00`. `checks.json` runs both the executable scenario and all seven regression
tests. Pass it to the runner using `--checks-file examples/legacy_orders/checks.json`.
