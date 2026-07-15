"""Platform infrastructure app.

Not one of the clinical domain modules (spec §7.4). Holds cross-cutting building
blocks every domain reuses: tenant-scoped base models, the transactional outbox,
and RLS helpers.
"""
