#!/usr/bin/env python3
"""
Build the medexam SQLite database from fixed JSONL data.

Inputs (default):
  fixed_data/questions_with_answers.jsonl
  fixed_data/cases.jsonl
  fixed_data/question_labels.jsonl

Output (default):
  output/medexam.db

Tables:
  common_cases
  questions
  choices
  answers
  question_labels

Run:
  python3 scripts/build_db.py
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

EXPECTED_QUESTIONS = 2000
EXPECTED_COMMON_CASES = 100
ALLOWED_LABELS = (
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
    "KL", "M", "N", "O", "P", "PQ", "R", "S", "T", "U",
    "V", "W", "X", "Y",
)

LABEL_SQL = ",".join(f"'{x}'" for x in ALLOWED_LABELS)

SCHEMA_SQL = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE common_cases (
    case_id         TEXT PRIMARY KEY,
    exam            INTEGER NOT NULL CHECK (exam BETWEEN 116 AND 120),
    section         TEXT NOT NULL CHECK (section IN ('A','B','C','D','E','F')),
    text            TEXT NOT NULL,
    source_corpus   TEXT
);

CREATE TABLE questions (
    question_id     TEXT PRIMARY KEY,
    exam            INTEGER NOT NULL CHECK (exam BETWEEN 116 AND 120),
    section         TEXT NOT NULL CHECK (section IN ('A','B','C','D','E','F')),
    number          INTEGER NOT NULL CHECK (number > 0),
    question_type   TEXT NOT NULL CHECK (question_type IN ('multiple_choice', 'numeric')),
    case_id         TEXT,
    stem            TEXT NOT NULL,
    answer_kind     TEXT NOT NULL CHECK (answer_kind IN ('choice', 'numeric')),
    answer_status   TEXT NOT NULL CHECK (answer_status IN ('ok', 'excluded', 'missing')),
    source_corpus   TEXT,

    UNIQUE (exam, section, number),

    FOREIGN KEY (case_id)
        REFERENCES common_cases(case_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CHECK (
        (question_type = 'multiple_choice' AND answer_kind = 'choice')
        OR
        (question_type = 'numeric' AND answer_kind = 'numeric')
    )
);

CREATE TABLE choices (
    question_id     TEXT NOT NULL,
    choice_label    TEXT NOT NULL CHECK (choice_label IN ('a','b','c','d','e')),
    choice_text     TEXT NOT NULL,

    PRIMARY KEY (question_id, choice_label),

    FOREIGN KEY (question_id)
        REFERENCES questions(question_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE answers (
    question_id     TEXT NOT NULL,
    answer_value    TEXT NOT NULL,

    PRIMARY KEY (question_id, answer_value),

    FOREIGN KEY (question_id)
        REFERENCES questions(question_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE question_labels (
    question_id     TEXT NOT NULL,
    label           TEXT NOT NULL CHECK (label IN ({LABEL_SQL})),
    is_primary      INTEGER NOT NULL CHECK (is_primary IN (0, 1)),

    PRIMARY KEY (question_id, label),

    FOREIGN KEY (question_id)
        REFERENCES questions(question_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_question_labels_one_primary
    ON question_labels(question_id)
    WHERE is_primary = 1;

CREATE INDEX idx_questions_exam
    ON questions(exam);

CREATE INDEX idx_questions_exam_section
    ON questions(exam, section);

CREATE INDEX idx_questions_question_type
    ON questions(question_type);

CREATE INDEX idx_questions_answer_status
    ON questions(answer_status);

CREATE INDEX idx_questions_case_id
    ON questions(case_id);

CREATE INDEX idx_question_labels_label
    ON question_labels(label);
"""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                raise ValueError(f"{path}: line {line_no}: blank line")

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"{path}: line {line_no}: invalid JSON "
                    f"({e.msg}, column {e.colno})"
                ) from e

            if not isinstance(obj, dict):
                raise ValueError(
                    f"{path}: line {line_no}: record must be a JSON object"
                )

            records.append(obj)

    return records


def require_string(obj: dict[str, Any], key: str, context: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{context}: {key} must be a non-empty string")
    return value


def source_corpus(obj: dict[str, Any]) -> str | None:
    source = obj.get("source")
    if source is None:
        return None
    if not isinstance(source, dict):
        raise ValueError("source must be an object or null")

    corpus = source.get("corpus")
    if corpus is None:
        return None
    if not isinstance(corpus, str):
        raise ValueError("source.corpus must be a string or null")
    return corpus


def unique_ids(
    records: Iterable[dict[str, Any]],
    key: str,
    name: str,
) -> set[str]:
    ids: list[str] = []
    for i, obj in enumerate(records, start=1):
        value = obj.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name}: record {i}: {key} must be a non-empty string")
        ids.append(value)

    duplicates = sorted(value for value, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"{name}: duplicate {key}: " + ", ".join(duplicates[:20]))

    return set(ids)


def preflight_validate(
    questions: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    labels: list[dict[str, Any]],
) -> None:
    if len(questions) != EXPECTED_QUESTIONS:
        raise ValueError(f"questions: expected {EXPECTED_QUESTIONS}, got {len(questions)}")
    if len(cases) != EXPECTED_COMMON_CASES:
        raise ValueError(f"common cases: expected {EXPECTED_COMMON_CASES}, got {len(cases)}")
    if len(labels) != EXPECTED_QUESTIONS:
        raise ValueError(f"label records: expected {EXPECTED_QUESTIONS}, got {len(labels)}")

    question_ids = unique_ids(questions, "question_id", "questions")
    case_ids = unique_ids(cases, "case_id", "cases")
    label_question_ids = unique_ids(labels, "question_id", "labels")

    if question_ids != label_question_ids:
        only_questions = sorted(question_ids - label_question_ids)
        only_labels = sorted(label_question_ids - question_ids)
        detail: list[str] = []
        if only_questions:
            detail.append("questions without label records: " + ", ".join(only_questions[:20]))
        if only_labels:
            detail.append("label records without questions: " + ", ".join(only_labels[:20]))
        raise ValueError("question/label ID mismatch; " + "; ".join(detail))

    questions_by_case: dict[str, set[str]] = {}
    for q in questions:
        qid = require_string(q, "question_id", "question")
        case_id = q.get("case_id")
        if case_id is None:
            continue
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{qid}: case_id must be a non-empty string or null")
        if case_id not in case_ids:
            raise ValueError(f"{qid}: unknown case_id: {case_id}")
        questions_by_case.setdefault(case_id, set()).add(qid)

    for case in cases:
        case_id = require_string(case, "case_id", "case")
        question_ids = case.get("question_ids")
        if not isinstance(question_ids, list):
            raise ValueError(f"{case_id}: question_ids must be a list")
        if not all(isinstance(qid, str) and qid for qid in question_ids):
            raise ValueError(f"{case_id}: every question_ids item must be a non-empty string")
        if len(question_ids) != len(set(question_ids)):
            raise ValueError(f"{case_id}: duplicate question_id in question_ids")

        listed = set(question_ids)
        linked = questions_by_case.get(case_id, set())
        if listed != linked:
            raise ValueError(
                f"{case_id}: cases.question_ids does not match questions.case_id "
                f"(listed={sorted(listed)}, linked={sorted(linked)})"
            )

    for record in labels:
        qid = require_string(record, "question_id", "label record")
        primary = record.get("primary_label")
        label_list = record.get("labels")

        if not isinstance(primary, str) or primary not in ALLOWED_LABELS:
            raise ValueError(f"{qid}: invalid primary_label: {primary!r}")
        if not isinstance(label_list, list) or not (1 <= len(label_list) <= 3):
            raise ValueError(f"{qid}: labels must contain 1 to 3 items")
        if not all(isinstance(x, str) and x in ALLOWED_LABELS for x in label_list):
            raise ValueError(f"{qid}: labels contains an undefined label")
        if len(label_list) != len(set(label_list)):
            raise ValueError(f"{qid}: labels contains a duplicate")
        if label_list[0] != primary:
            raise ValueError(
                f"{qid}: primary_label must equal labels[0] "
                f"({primary!r} != {label_list[0]!r})"
            )


def insert_common_cases(conn: sqlite3.Connection, cases: list[dict[str, Any]]) -> None:
    rows: list[tuple[Any, ...]] = []
    for case in cases:
        case_id = require_string(case, "case_id", "case")
        text = require_string(case, "text", case_id)
        rows.append((
            case_id,
            case.get("exam"),
            case.get("section"),
            text,
            source_corpus(case),
        ))

    conn.executemany(
        """
        INSERT INTO common_cases (
            case_id, exam, section, text, source_corpus
        ) VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


def insert_questions_and_children(
    conn: sqlite3.Connection,
    questions: list[dict[str, Any]],
) -> None:
    question_rows: list[tuple[Any, ...]] = []
    choice_rows: list[tuple[Any, ...]] = []
    answer_rows: list[tuple[Any, ...]] = []

    for q in questions:
        qid = require_string(q, "question_id", "question")
        stem = require_string(q, "stem", qid)

        question_rows.append((
            qid,
            q.get("exam"),
            q.get("section"),
            q.get("number"),
            q.get("question_type"),
            q.get("case_id"),
            stem,
            q.get("answer_kind"),
            q.get("answer_status"),
            source_corpus(q),
        ))

        choices = q.get("choices")
        if not isinstance(choices, list):
            raise ValueError(f"{qid}: choices must be a list")
        for choice in choices:
            if not isinstance(choice, dict):
                raise ValueError(f"{qid}: every choice must be an object")
            label = require_string(choice, "label", f"{qid} choice")
            text = require_string(choice, "text", f"{qid} choice {label}")
            choice_rows.append((qid, label, text))

        accepted_answers = q.get("accepted_answers")
        if not isinstance(accepted_answers, list):
            raise ValueError(f"{qid}: accepted_answers must be a list")
        for answer_value in accepted_answers:
            if not isinstance(answer_value, str) or answer_value == "":
                raise ValueError(f"{qid}: accepted_answers items must be non-empty strings")
            answer_rows.append((qid, answer_value))

    conn.executemany(
        """
        INSERT INTO questions (
            question_id, exam, section, number, question_type,
            case_id, stem, answer_kind, answer_status, source_corpus
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        question_rows,
    )
    conn.executemany(
        """
        INSERT INTO choices (question_id, choice_label, choice_text)
        VALUES (?, ?, ?)
        """,
        choice_rows,
    )
    conn.executemany(
        """
        INSERT INTO answers (question_id, answer_value)
        VALUES (?, ?)
        """,
        answer_rows,
    )


def insert_labels(conn: sqlite3.Connection, labels: list[dict[str, Any]]) -> None:
    rows: list[tuple[Any, ...]] = []
    for record in labels:
        qid = require_string(record, "question_id", "label record")
        primary = require_string(record, "primary_label", qid)
        label_list = record.get("labels")
        if not isinstance(label_list, list):
            raise ValueError(f"{qid}: labels must be a list")

        for label in label_list:
            if not isinstance(label, str):
                raise ValueError(f"{qid}: label must be a string")
            rows.append((qid, label, 1 if label == primary else 0))

    conn.executemany(
        """
        INSERT INTO question_labels (question_id, label, is_primary)
        VALUES (?, ?, ?)
        """,
        rows,
    )


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise RuntimeError(f"query returned no rows: {sql}")
    return row[0]


def post_build_validate(
    conn: sqlite3.Connection,
    source_questions: int,
    source_cases: int,
    source_label_records: int,
) -> dict[str, int]:
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        raise RuntimeError(f"foreign_key_check failed: {fk_errors[:10]}")

    integrity = scalar(conn, "PRAGMA integrity_check")
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {integrity}")

    counts = {
        "common_cases": scalar(conn, "SELECT COUNT(*) FROM common_cases"),
        "questions": scalar(conn, "SELECT COUNT(*) FROM questions"),
        "choices": scalar(conn, "SELECT COUNT(*) FROM choices"),
        "answers": scalar(conn, "SELECT COUNT(*) FROM answers"),
        "question_labels": scalar(conn, "SELECT COUNT(*) FROM question_labels"),
        "primary_labels": scalar(conn, "SELECT COUNT(*) FROM question_labels WHERE is_primary = 1"),
        "numeric_questions": scalar(conn, "SELECT COUNT(*) FROM questions WHERE question_type = 'numeric'"),
        "excluded_questions": scalar(conn, "SELECT COUNT(*) FROM questions WHERE answer_status = 'excluded'"),
        "missing_answers": scalar(conn, "SELECT COUNT(*) FROM questions WHERE answer_status = 'missing'"),
    }

    if counts["questions"] != source_questions:
        raise RuntimeError(
            f"questions count mismatch: DB={counts['questions']}, source={source_questions}"
        )
    if counts["common_cases"] != source_cases:
        raise RuntimeError(
            f"common_cases count mismatch: DB={counts['common_cases']}, source={source_cases}"
        )
    if counts["primary_labels"] != source_label_records:
        raise RuntimeError(
            f"primary label count mismatch: DB={counts['primary_labels']}, "
            f"source label records={source_label_records}"
        )

    questions_without_labels = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM questions AS q
        WHERE NOT EXISTS (
            SELECT 1 FROM question_labels AS l
            WHERE l.question_id = q.question_id
        )
        """,
    )
    if questions_without_labels != 0:
        raise RuntimeError(f"{questions_without_labels} questions have no labels")

    wrong_primary_count = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM (
            SELECT q.question_id,
                   SUM(CASE WHEN l.is_primary = 1 THEN 1 ELSE 0 END) AS n_primary
            FROM questions AS q
            LEFT JOIN question_labels AS l
              ON l.question_id = q.question_id
            GROUP BY q.question_id
            HAVING n_primary <> 1
        )
        """,
    )
    if wrong_primary_count != 0:
        raise RuntimeError(
            f"{wrong_primary_count} questions do not have exactly one primary label"
        )

    multiple_choice_without_choices = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM questions AS q
        WHERE q.question_type = 'multiple_choice'
          AND NOT EXISTS (
              SELECT 1 FROM choices AS c
              WHERE c.question_id = q.question_id
          )
        """,
    )
    if multiple_choice_without_choices != 0:
        raise RuntimeError(
            f"{multiple_choice_without_choices} multiple-choice questions have no choices"
        )

    numeric_with_choices = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM questions AS q
        WHERE q.question_type = 'numeric'
          AND EXISTS (
              SELECT 1 FROM choices AS c
              WHERE c.question_id = q.question_id
          )
        """,
    )
    if numeric_with_choices != 0:
        raise RuntimeError(
            f"{numeric_with_choices} numeric questions unexpectedly have choices"
        )

    ok_without_answers = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM questions AS q
        WHERE q.answer_status = 'ok'
          AND NOT EXISTS (
              SELECT 1 FROM answers AS a
              WHERE a.question_id = q.question_id
          )
        """,
    )
    if ok_without_answers != 0:
        raise RuntimeError(
            f"{ok_without_answers} answer_status='ok' questions have no answers"
        )

    return counts


def parse_args() -> argparse.Namespace:
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent

    parser = argparse.ArgumentParser(
        description="Build output/medexam.db from fixed_data JSONL files."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=project_root / "fixed_data",
        help="directory containing the three fixed JSONL input files",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=project_root / "output" / "medexam.db",
        help="output SQLite database path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    db_path = args.db.resolve()

    questions_path = data_dir / "questions_with_answers.jsonl"
    cases_path = data_dir / "cases.jsonl"
    labels_path = data_dir / "question_labels.jsonl"

    print("=== medexam SQLite builder ===")
    print(f"questions: {questions_path}")
    print(f"cases:     {cases_path}")
    print(f"labels:    {labels_path}")
    print(f"database:  {db_path}")
    print()

    tmp_path = db_path.with_name(db_path.name + ".tmp")

    try:
        questions = load_jsonl(questions_path)
        cases = load_jsonl(cases_path)
        labels = load_jsonl(labels_path)

        preflight_validate(questions, cases, labels)

        db_path.parent.mkdir(parents=True, exist_ok=True)
        if tmp_path.exists():
            tmp_path.unlink()

        conn = sqlite3.connect(tmp_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA_SQL)

            with conn:
                insert_common_cases(conn, cases)
                insert_questions_and_children(conn, questions)
                insert_labels(conn, labels)

            counts = post_build_validate(
                conn,
                source_questions=len(questions),
                source_cases=len(cases),
                source_label_records=len(labels),
            )
        finally:
            conn.close()

        os.replace(tmp_path, db_path)

    except (OSError, ValueError, sqlite3.Error, RuntimeError) as e:
        if tmp_path.exists():
            tmp_path.unlink()
        print(f"[ERROR] {e}", file=sys.stderr)
        print("RESULT: FAILED", file=sys.stderr)
        return 1

    print("=== build summary ===")
    print(f"common_cases:       {counts['common_cases']}")
    print(f"questions:          {counts['questions']}")
    print(f"choices:            {counts['choices']}")
    print(f"answers:            {counts['answers']}")
    print(f"question_labels:    {counts['question_labels']}")
    print(f"primary_labels:     {counts['primary_labels']}")
    print(f"numeric_questions:  {counts['numeric_questions']}")
    print(f"excluded_questions: {counts['excluded_questions']}")
    print(f"missing_answers:    {counts['missing_answers']}")
    print()
    print(f"created: {db_path}")
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
