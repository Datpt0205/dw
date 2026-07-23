"""Memory context: typed memory items, write-candidate policy and retention.
The system of record stays PostgreSQL; memory is never authoritative for
transactional state (blueprint §14)."""

__version__ = "0.1.0"
