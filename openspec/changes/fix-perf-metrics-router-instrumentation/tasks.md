## 1. Runtime Metrics Compatibility

- [x] 1.1 Extract opt-in metrics setup and add the FastAPI included-router route-template adapter without changing existing metrics configuration.
- [x] 1.2 Keep setup idempotent per application instance and preserve bounded labels, excluded handlers, and query timing registry behavior.

## 2. Regression Coverage

- [x] 2.1 Add focused tests for enabled metrics on included and parameterized routes, including a scrape of the query phase Histogram.
- [x] 2.2 Add focused tests for disabled metrics, a custom metrics path, metrics-path exclusion, repeated setup, and the pinned runtime dependency contract.

## 3. Verification And Closeout

- [x] 3.1 Run focused tests, static compilation, OpenSpec strict validation, and diff checks.
- [x] 3.2 Update the project summary with the implementation result and explicit environment acceptance boundary.
