"""Domain events published by the Reliability module.

An SLO breach is published so alerting/eligibility react (spec §12.3 critical alerts). The
provider-failover path stays synchronous (no event) — the caller acts on the selection
immediately and records skips in its own decision trace.
"""
