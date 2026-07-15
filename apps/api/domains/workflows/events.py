"""Domain events published by the Workflows module.

Cross-module communication happens through explicit domain events
(spec §7.5) — never direct ORM reach-across. Publish via
`core.outbox.publish_event` inside the same DB transaction.
"""
