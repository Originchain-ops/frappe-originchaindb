"""Classify SQL for transaction accounting without rewriting user queries."""

import re

import sqlparse
from sqlparse import tokens


def transaction_kind(query):
    statements = sqlparse.parse(query)
    if not statements:
        return ""
    statement = statements[0]
    kind = statement.get_type().lower()
    if kind in {"create", "alter", "drop", "truncate", "insert", "update", "delete", "merge"}:
        return "update" if kind == "merge" else kind
    # A SELECT may contain a writable CTE. Count it as a write for DDL guards.
    if any(
        token.ttype in tokens.DML and token.normalized in {"INSERT", "UPDATE", "DELETE", "MERGE"}
        for token in statement.flatten()
    ):
        return "update"
    first = statement.token_first(skip_ws=True, skip_cm=True)
    return first.normalized.split()[0].lower() if first else ""


def partial_rollback(query):
    clean = sqlparse.format(query, strip_comments=True)
    return bool(re.match(r"\s*ROLLBACK\s+(?:(?:WORK|TRANSACTION)\s+)?TO\b", clean, flags=re.IGNORECASE))
