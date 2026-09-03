"""The cascade executor.

Runs each rule in order against only the records still unmatched, and enforces
1:1 pairing by requiring a candidate to be the best option for *both* sides.
This is where the 97%-of-records-never-touch-an-LLM number comes from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb

from app.config import settings
from app.engine.confidence import sql_score_expression
from app.engine.rules import MatchRule

log = logging.getLogger(__name__)

LINKS_DDL = """
CREATE OR REPLACE TABLE {table} (
  left_uid VARCHAR,
  right_uid VARCHAR,
  stage VARCHAR,
  rule VARCHAR,
  confidence DOUBLE,
  amount_delta_minor BIGINT,
  time_delta_sec BIGINT
)
"""


@dataclass
class StageStat:
    stage: str
    rule: str
    matched: int
    candidates: int


def create_links_table(con: duckdb.DuckDBPyConnection, table: str) -> None:
    con.execute(LINKS_DDL.format(table=table))


def run_cascade(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    links: str,
    rules: list[MatchRule],
    window_sec: int | None = None,
    exclude_left: str | None = None,
) -> list[StageStat]:
    """Execute every rule in order, accumulating 1:1 links.

    `exclude_left` names a table of record_uids barred from the left side.
    Used to keep flagged duplicate payments out of the settlement contest: the
    duplicate is 90 seconds closer to the settlement than the original, so
    without this it wins the tie-break and the *real* payment books as
    missing-settlement while the duplicate quietly looks reconciled.
    """
    create_links_table(con, links)
    stats: list[StageStat] = []

    for rule in rules:
        score_sql = sql_score_expression(rule.components, window_sec=window_sec)
        for offset in rule.day_offsets:
            matched = _apply_rule(con, left, right, links, rule, score_sql, offset, exclude_left)
            stats.append(StageStat(rule.stage.value, rule.name, matched, matched))
            # Day sweeps produce a lot of empty passes; only the productive
            # ones are worth a line in the run log.
            log.log(
                logging.INFO if matched else logging.DEBUG,
                "cascade %s/%s offset=%+d matched=%d",
                rule.stage.value, rule.name, offset, matched,
            )

    return stats


def _apply_rule(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    links: str,
    rule: MatchRule,
    score_sql: str,
    day_offset: int,
    exclude_left: str | None = None,
) -> int:
    join_sql = rule.join_sql.replace("{day_offset}", str(day_offset))
    exclude_sql = (
        f"AND NOT EXISTS (SELECT 1 FROM {exclude_left} x WHERE x.record_uid = l.record_uid)"
        if exclude_left else ""
    )
    sql = f"""
        INSERT INTO {links}
        WITH
        -- Narrow to still-unmatched records BEFORE joining. This is the whole
        -- performance story: without it the optimizer may evaluate the join
        -- across the full tables and only then discard claimed rows, which for
        -- a rule with no equality predicate is a cross product.
        pending_left AS (
            SELECT l.* FROM {left} l
            WHERE NOT EXISTS (SELECT 1 FROM {links} m WHERE m.left_uid = l.record_uid)
            {exclude_sql}
        ),
        pending_right AS (
            SELECT r.* FROM {right} r
            WHERE NOT EXISTS (SELECT 1 FROM {links} m WHERE m.right_uid = r.record_uid)
        ),
        candidates AS (
            SELECT
                l.record_uid AS left_uid,
                r.record_uid AS right_uid,
                (l.amount_minor - r.amount_minor) AS amount_delta_minor,
                CASE WHEN l.txn_ts IS NULL OR r.txn_ts IS NULL THEN NULL
                     ELSE date_diff('second', l.txn_ts, r.txn_ts) END AS time_delta_sec,
                ({score_sql}) AS confidence
            FROM pending_left l
            JOIN pending_right r ON {join_sql}
            WHERE ({rule.where_sql})
        ),
        ranked AS (
            SELECT *,
                row_number() OVER (
                    PARTITION BY left_uid
                    ORDER BY confidence DESC, abs(amount_delta_minor),
                             abs(coalesce(time_delta_sec, 9223372036854775807))
                ) AS rn_left,
                row_number() OVER (
                    PARTITION BY right_uid
                    ORDER BY confidence DESC, abs(amount_delta_minor),
                             abs(coalesce(time_delta_sec, 9223372036854775807))
                ) AS rn_right
            FROM candidates
        )
        SELECT left_uid, right_uid, '{rule.stage.value}', '{rule.name}',
               confidence, amount_delta_minor, time_delta_sec
        FROM ranked
        -- Mutual best match. Anything ambiguous is deliberately left for the
        -- next rule or, failing that, for a human.
        WHERE rn_left = 1 AND rn_right = 1
        """
    before = con.execute(f"SELECT count(*) FROM {links}").fetchone()[0]
    con.execute(sql)
    after = con.execute(f"SELECT count(*) FROM {links}").fetchone()[0]
    return int(after - before)


def detect_duplicates(con: duckdb.DuckDBPyConnection, table: str, out_table: str) -> int:
    """Two flavours of duplicate: the same transaction id twice, and the same
    merchant/amount/order billed twice inside a short window."""
    con.execute(f"""
    CREATE OR REPLACE TABLE {out_table} AS
    WITH exact_dupes AS (
        SELECT record_uid, txn_id AS dupe_key, 'EXACT_TXN_ID' AS dupe_reason,
               row_number() OVER (PARTITION BY txn_id ORDER BY txn_ts, record_uid) AS occurrence
        FROM {table}
        WHERE txn_id IS NOT NULL AND txn_id <> ''
    ),
    near_dupes AS (
        SELECT record_uid,
               merchant_id || '|' || order_id || '|' || amount_minor::VARCHAR AS dupe_key,
               'SAME_ORDER_AMOUNT' AS dupe_reason,
               row_number() OVER (
                   PARTITION BY merchant_id, order_id, amount_minor
                   ORDER BY txn_ts, record_uid
               ) AS occurrence
        FROM {table}
        WHERE order_id IS NOT NULL AND order_id <> ''
    )
    SELECT * FROM exact_dupes WHERE occurrence > 1
    UNION ALL
    SELECT * FROM near_dupes WHERE occurrence > 1
      AND record_uid NOT IN (SELECT record_uid FROM exact_dupes WHERE occurrence > 1)
    """)
    return int(con.execute(f"SELECT count(*) FROM {out_table}").fetchone()[0])


def generate_ai_candidates(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    links: str,
    out_table: str,
    top_k: int = 3,
    day_span: int = 2,
) -> int:
    """For records the cascade could not close, surface the top-K plausible
    partners inside the blocking key. This — not the raw table — is what the
    model gets to reason over.

    Blocked on merchant + currency + day, swept across a small day window. The
    naive version of this (merchant + a date range predicate) is quadratic in a
    large merchant's volume and was the single slowest thing in the pipeline.
    """
    offsets = ", ".join(str(o) for o in range(-day_span, day_span + 1))
    con.execute(f"""
    CREATE OR REPLACE TABLE {out_table} AS
    WITH unmatched_left AS (
        SELECT * FROM {left} l
        WHERE NOT EXISTS (SELECT 1 FROM {links} m WHERE m.left_uid = l.record_uid)
          AND l.txn_ts IS NOT NULL
    ),
    unmatched_right AS (
        SELECT * FROM {right} r
        WHERE NOT EXISTS (SELECT 1 FROM {links} m WHERE m.right_uid = r.record_uid)
          AND r.txn_ts IS NOT NULL
    ),
    -- Explode the right side across the day window so the join stays a hash
    -- equi-join rather than degrading into a range scan.
    right_expanded AS (
        SELECT r.*, (r.day_bucket + o.offset) AS probe_day
        FROM unmatched_right r
        CROSS JOIN (SELECT unnest([{offsets}]) AS offset) o
    ),
    pairs AS (
        SELECT l.record_uid AS left_uid, r.record_uid AS right_uid,
               l.amount_minor - r.amount_minor AS amount_delta_minor,
               date_diff('second', l.txn_ts, r.txn_ts) AS time_delta_sec,
               (CASE WHEN abs(l.amount_minor - r.amount_minor)
                          <= {settings.amount_bucket_minor} THEN 0.5 ELSE 0.15 END
              + CASE WHEN l.ref_digits <> '' AND l.ref_digits = r.ref_digits THEN 0.35 ELSE 0 END
              + CASE WHEN l.order_id = r.order_id THEN 0.15 ELSE 0 END
               ) AS affinity
        FROM unmatched_left l
        JOIN right_expanded r
          ON l.merchant_id = r.merchant_id
         AND l.currency = r.currency
         AND l.day_bucket = r.probe_day
    )
    SELECT * FROM (
        SELECT *, row_number() OVER (PARTITION BY left_uid ORDER BY affinity DESC) AS rk
        FROM pairs
    ) WHERE rk <= {top_k}
    """)
    return int(con.execute(f"SELECT count(*) FROM {out_table}").fetchone()[0])
