"""Modular-monolith domain modules (spec §7.4).

Each subpackage is a bounded domain that owns its models and exposes a ``services.py``
interface. Cross-module access goes through those interfaces and explicit domain events.
"""
