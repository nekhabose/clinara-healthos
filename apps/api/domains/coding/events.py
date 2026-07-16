"""Domain events published by the Billing & Coding Intelligence module (plan Phase 9).

Publish via ``core.outbox.publish_event`` inside the same DB transaction as the write.
Emitted here (see ``services``):

  * ``CodingSuggestionsGenerated`` — deterministic analysis produced N pending suggestions.
  * ``CodingSuggestionConfirmed``  — a clinician confirmed a suggestion (actor + evidence).
  * ``CodingSuggestionRejected``   — a clinician rejected a suggestion (feeds override rate).
  * ``CodingSuggestionExported``   — a confirmed suggestion was released to coding/claim.
"""
