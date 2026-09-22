#!/usr/bin/env python3
"""
Final validator for the medexam structured dataset.

Default inputs:
  output/questions_with_answers.jsonl
  output/question_labels.jsonl

Run from the repository root:
  python3 scripts/validate_out.py

Optional:
  python3 scripts/validate_out.py \
      --questions output/questions_with_answers.jsonl \
      --labels output/question_labels.jsonl

Exit status:
  0: validation passed
  1: validation failed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXPECTED_EXAMS = range(116, 121)
EXPECTED_SECTION_COUNTS = {
    "A": 75,
    "B": 50,
    "C": 75,
    "D": 75,
    "E": 50,
    "F": 75,
}
EXPECTED_TOTAL = 2000
EXPECTED_NUMERIC = 17
EXPECTED_EXCLUDED = 9
EXPECTED_OK = 1991
EXPECTED_MISSING = 0

ALLOWED_LABELS = {
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
    "KL", "M", "N", "O", "P", "PQ", "R", "S", "T", "U",
    "V", "W", "X", "Y",
}

NUMERIC_QUESTION_IDS = {
    "116-B-050",
    "116-C-075",
    "116-F-074",
    "117-C-075",
    "117-F-071",
    "117-F-075",
    "118-A-075",
    "118-C-073",
    "118-C-075",
    "118-D-075",
    "119-A-075",
    "119-C-074",
    "119-C-075",
    "119-F-075",
    "120-A-074",
    "120-A-075",
    "120-D-075",
}

EXCLUDED_QUESTION_IDS = {
    "116-A-034",
    "116-B-043",
    "116-C-036",
    "116-D-064",
    "117-C-015",
    "117-C-060",
    "117-D-038",
    "117-D-053",
    "117-F-042",
}

QUESTION_ID_RE = re.compile(r"^(116|117|118|119|120)-([A-F])-(\d{3})$")
CASE_ID_RE = re.compile(
    r"^(116|117|118|119|120)-([A-F])-(\d{3})-(\d{3})$"
)
CHOICE_LABELS = {"a", "b", "c", "d", "e"}

QUESTION_REQUIRED_KEYS = {
    "question_id",
    "exam",
    "section",
    "number",
    "question_type",
    "case_id",
    "stem",
    "choices",
    "source",
    "answer_kind",
    "accepted_answers",
    "answer_status",
}

LABEL_REQUIRED_KEYS = {
    "question_id",
    "primary_label",
    "labels",
}


@dataclass
class LoadedRecord:
    line_no: int
    data: dict[str, Any]


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def check_equal(
        self,
        actual: Any,
        expected: Any,
        name: str,
    ) -> None:
        if actual != expected:
            self.error(f"{name}: expected {expected!r}, got {actual!r}")


def expected_question_ids() -> list[str]:
    ids: list[str] = []
    for exam in EXPECTED_EXAMS:
        for section, count in EXPECTED_SECTION_COUNTS.items():
            for number in range(1, count + 1):
                ids.append(f"{exam}-{section}-{number:03d}")
    return ids


def load_jsonl(path: Path, validator: Validator, name: str) -> list[LoadedRecord]:
    records: list[LoadedRecord] = []

    if not path.is_file():
        validator.error(f"{name}: file not found: {path}")
        return records

    try:
        with path.open("r", encoding="utf-8-sig") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()

                if not line:
                    validator.error(f"{name}: line {line_no}: blank line")
                    continue

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    validator.error(
                        f"{name}: line {line_no}: invalid JSON "
                        f"({e.msg}, column {e.colno})"
                    )
                    continue

                if not isinstance(obj, dict):
                    validator.error(
                        f"{name}: line {line_no}: record must be a JSON object"
                    )
                    continue

                records.append(LoadedRecord(line_no=line_no, data=obj))

    except OSError as e:
        validator.error(f"{name}: cannot read {path}: {e}")

    return records


def validate_question_id(
    qid: Any,
    line_no: int,
    validator: Validator,
    prefix: str,
) -> tuple[int, str, int] | None:
    if not isinstance(qid, str):
        validator.error(
            f"{prefix}: line {line_no}: question_id must be str, got {type(qid).__name__}"
        )
        return None

    m = QUESTION_ID_RE.fullmatch(qid)
    if not m:
        validator.error(
            f"{prefix}: line {line_no}: invalid question_id format: {qid!r}"
        )
        return None

    return int(m.group(1)), m.group(2), int(m.group(3))


def validate_questions(
    records: list[LoadedRecord],
    validator: Validator,
) -> dict[str, Any]:
    stats: dict[str, Any] = {}

    validator.check_equal(len(records), EXPECTED_TOTAL, "questions count")

    ids: list[str] = []
    question_types: Counter[str] = Counter()
    answer_statuses: Counter[str] = Counter()
    exam_counts: Counter[int] = Counter()
    exam_section_counts: Counter[tuple[int, str]] = Counter()

    numeric_ids: set[str] = set()
    excluded_ids: set[str] = set()

    for rec in records:
        obj = rec.data
        line_no = rec.line_no

        missing_keys = sorted(QUESTION_REQUIRED_KEYS - obj.keys())
        if missing_keys:
            validator.error(
                f"questions: line {line_no}: missing keys: {', '.join(missing_keys)}"
            )

        qid = obj.get("question_id")
        parsed = validate_question_id(qid, line_no, validator, "questions")

        if isinstance(qid, str):
            ids.append(qid)

        if parsed is not None:
            q_exam, q_section, q_number = parsed
            exam_counts[q_exam] += 1
            exam_section_counts[(q_exam, q_section)] += 1

            exam = obj.get("exam")
            section = obj.get("section")
            number = obj.get("number")

            if exam != q_exam:
                validator.error(
                    f"questions: line {line_no} {qid}: "
                    f"exam mismatch: {exam!r} != {q_exam!r}"
                )
            if section != q_section:
                validator.error(
                    f"questions: line {line_no} {qid}: "
                    f"section mismatch: {section!r} != {q_section!r}"
                )
            if number != q_number:
                validator.error(
                    f"questions: line {line_no} {qid}: "
                    f"number mismatch: {number!r} != {q_number!r}"
                )

        question_type = obj.get("question_type")
        if question_type not in {"multiple_choice", "numeric"}:
            validator.error(
                f"questions: line {line_no} {qid}: "
                f"invalid question_type: {question_type!r}"
            )
        else:
            question_types[question_type] += 1
            if question_type == "numeric" and isinstance(qid, str):
                numeric_ids.add(qid)

        case_id = obj.get("case_id")
        if case_id is not None:
            if not isinstance(case_id, str):
                validator.error(
                    f"questions: line {line_no} {qid}: "
                    f"case_id must be str or null"
                )
            else:
                m = CASE_ID_RE.fullmatch(case_id)
                if not m:
                    validator.error(
                        f"questions: line {line_no} {qid}: "
                        f"invalid case_id format: {case_id!r}"
                    )
                elif parsed is not None:
                    c_exam = int(m.group(1))
                    c_section = m.group(2)
                    c_start = int(m.group(3))
                    c_end = int(m.group(4))
                    q_exam, q_section, q_number = parsed

                    if c_exam != q_exam or c_section != q_section:
                        validator.error(
                            f"questions: line {line_no} {qid}: "
                            f"case_id belongs to another exam/section: {case_id!r}"
                        )
                    if not (c_start <= q_number <= c_end):
                        validator.error(
                            f"questions: line {line_no} {qid}: "
                            f"question number not inside case range: {case_id!r}"
                        )

        stem = obj.get("stem")
        if not isinstance(stem, str) or not stem.strip():
            validator.error(
                f"questions: line {line_no} {qid}: stem must be a non-empty string"
            )

        choices = obj.get("choices")
        if not isinstance(choices, list):
            validator.error(
                f"questions: line {line_no} {qid}: choices must be a list"
            )
        else:
            if question_type == "multiple_choice" and len(choices) == 0:
                validator.error(
                    f"questions: line {line_no} {qid}: "
                    f"multiple_choice has no choices"
                )
            if question_type == "numeric" and len(choices) != 0:
                validator.error(
                    f"questions: line {line_no} {qid}: "
                    f"numeric question must have zero choices"
                )

            seen_choice_labels: set[str] = set()
            for i, choice in enumerate(choices):
                if not isinstance(choice, dict):
                    validator.error(
                        f"questions: line {line_no} {qid}: "
                        f"choices[{i}] must be an object"
                    )
                    continue

                label = choice.get("label")
                text = choice.get("text")

                if label not in CHOICE_LABELS:
                    validator.error(
                        f"questions: line {line_no} {qid}: "
                        f"invalid choice label at choices[{i}]: {label!r}"
                    )
                elif label in seen_choice_labels:
                    validator.error(
                        f"questions: line {line_no} {qid}: "
                        f"duplicate choice label: {label!r}"
                    )
                else:
                    seen_choice_labels.add(label)

                if not isinstance(text, str) or not text.strip():
                    validator.error(
                        f"questions: line {line_no} {qid}: "
                        f"choices[{i}].text must be a non-empty string"
                    )

        source = obj.get("source")
        if not isinstance(source, dict):
            validator.error(
                f"questions: line {line_no} {qid}: source must be an object"
            )

        answer_kind = obj.get("answer_kind")
        if answer_kind not in {"choice", "numeric"}:
            validator.error(
                f"questions: line {line_no} {qid}: "
                f"invalid answer_kind: {answer_kind!r}"
            )
        elif question_type in {"multiple_choice", "numeric"}:
            expected_kind = "numeric" if question_type == "numeric" else "choice"
            if answer_kind != expected_kind:
                validator.error(
                    f"questions: line {line_no} {qid}: "
                    f"answer_kind {answer_kind!r} does not match "
                    f"question_type {question_type!r}"
                )

        accepted_answers = obj.get("accepted_answers")
        if not isinstance(accepted_answers, list):
            validator.error(
                f"questions: line {line_no} {qid}: accepted_answers must be a list"
            )
        else:
            for i, answer in enumerate(accepted_answers):
                if not isinstance(answer, str):
                    validator.error(
                        f"questions: line {line_no} {qid}: "
                        f"accepted_answers[{i}] must be str"
                    )

        answer_status = obj.get("answer_status")
        if answer_status not in {"ok", "excluded", "missing"}:
            validator.error(
                f"questions: line {line_no} {qid}: "
                f"invalid answer_status: {answer_status!r}"
            )
        else:
            answer_statuses[answer_status] += 1

            if answer_status == "ok":
                if not isinstance(accepted_answers, list) or len(accepted_answers) == 0:
                    validator.error(
                        f"questions: line {line_no} {qid}: "
                        f"answer_status='ok' but accepted_answers is empty"
                    )

            if answer_status == "excluded" and isinstance(qid, str):
                excluded_ids.add(qid)

    duplicate_ids = sorted(
        qid for qid, count in Counter(ids).items() if count > 1
    )
    for qid in duplicate_ids:
        validator.error(f"questions: duplicate question_id: {qid}")

    expected_ids = expected_question_ids()
    if ids != expected_ids:
        first_mismatch = next(
            (
                i
                for i, (actual, expected) in enumerate(
                    zip(ids, expected_ids),
                    start=1,
                )
                if actual != expected
            ),
            None,
        )
        if first_mismatch is None and len(ids) != len(expected_ids):
            first_mismatch = min(len(ids), len(expected_ids)) + 1

        validator.error(
            "questions: question_id sequence does not exactly match the "
            f"expected 116-120 A-F order"
            + (
                f" (first mismatch at record {first_mismatch})"
                if first_mismatch is not None
                else ""
            )
        )

    for exam in EXPECTED_EXAMS:
        validator.check_equal(
            exam_counts[exam],
            400,
            f"questions exam {exam} count",
        )
        for section, expected_count in EXPECTED_SECTION_COUNTS.items():
            validator.check_equal(
                exam_section_counts[(exam, section)],
                expected_count,
                f"questions {exam}-{section} count",
            )

    validator.check_equal(
        question_types["multiple_choice"],
        1983,
        "multiple_choice count",
    )
    validator.check_equal(
        question_types["numeric"],
        EXPECTED_NUMERIC,
        "numeric count",
    )
    validator.check_equal(
        answer_statuses["ok"],
        EXPECTED_OK,
        "answer_status ok count",
    )
    validator.check_equal(
        answer_statuses["excluded"],
        EXPECTED_EXCLUDED,
        "answer_status excluded count",
    )
    validator.check_equal(
        answer_statuses["missing"],
        EXPECTED_MISSING,
        "answer_status missing count",
    )

    missing_numeric = sorted(NUMERIC_QUESTION_IDS - numeric_ids)
    extra_numeric = sorted(numeric_ids - NUMERIC_QUESTION_IDS)
    if missing_numeric:
        validator.error(
            "questions: expected numeric IDs missing: "
            + ", ".join(missing_numeric)
        )
    if extra_numeric:
        validator.error(
            "questions: unexpected numeric IDs: "
            + ", ".join(extra_numeric)
        )

    missing_excluded = sorted(EXCLUDED_QUESTION_IDS - excluded_ids)
    extra_excluded = sorted(excluded_ids - EXCLUDED_QUESTION_IDS)
    if missing_excluded:
        validator.error(
            "questions: expected excluded IDs missing: "
            + ", ".join(missing_excluded)
        )
    if extra_excluded:
        validator.error(
            "questions: unexpected excluded IDs: "
            + ", ".join(extra_excluded)
        )

    stats["ids"] = ids
    stats["question_types"] = question_types
    stats["answer_statuses"] = answer_statuses
    return stats


def validate_labels(
    records: list[LoadedRecord],
    validator: Validator,
) -> dict[str, Any]:
    stats: dict[str, Any] = {}

    validator.check_equal(len(records), EXPECTED_TOTAL, "labels count")

    ids: list[str] = []
    primary_counts: Counter[str] = Counter()
    label_width_counts: Counter[int] = Counter()

    for rec in records:
        obj = rec.data
        line_no = rec.line_no

        missing_keys = sorted(LABEL_REQUIRED_KEYS - obj.keys())
        if missing_keys:
            validator.error(
                f"labels: line {line_no}: missing keys: {', '.join(missing_keys)}"
            )

        qid = obj.get("question_id")
        validate_question_id(qid, line_no, validator, "labels")
        if isinstance(qid, str):
            ids.append(qid)

        primary = obj.get("primary_label")
        if not isinstance(primary, str):
            validator.error(
                f"labels: line {line_no} {qid}: primary_label must be str"
            )
        elif primary not in ALLOWED_LABELS:
            validator.error(
                f"labels: line {line_no} {qid}: "
                f"undefined primary_label: {primary!r}"
            )
        else:
            primary_counts[primary] += 1

        labels = obj.get("labels")
        if not isinstance(labels, list):
            validator.error(
                f"labels: line {line_no} {qid}: labels must be a list"
            )
            continue

        label_width_counts[len(labels)] += 1

        if not (1 <= len(labels) <= 3):
            validator.error(
                f"labels: line {line_no} {qid}: "
                f"labels length must be 1-3, got {len(labels)}"
            )

        non_string_labels = [
            (i, label)
            for i, label in enumerate(labels)
            if not isinstance(label, str)
        ]
        for i, label in non_string_labels:
            validator.error(
                f"labels: line {line_no} {qid}: "
                f"labels[{i}] must be str, got {type(label).__name__}"
            )

        string_labels = [label for label in labels if isinstance(label, str)]

        invalid_labels = sorted(
            {label for label in string_labels if label not in ALLOWED_LABELS}
        )
        if invalid_labels:
            validator.error(
                f"labels: line {line_no} {qid}: undefined labels: "
                + ", ".join(invalid_labels)
            )

        if len(string_labels) != len(set(string_labels)):
            validator.error(
                f"labels: line {line_no} {qid}: duplicate label in labels"
            )

        if labels and primary != labels[0]:
            validator.error(
                f"labels: line {line_no} {qid}: "
                f"primary_label must equal labels[0] "
                f"({primary!r} != {labels[0]!r})"
            )

    duplicate_ids = sorted(
        qid for qid, count in Counter(ids).items() if count > 1
    )
    for qid in duplicate_ids:
        validator.error(f"labels: duplicate question_id: {qid}")

    expected_ids = expected_question_ids()
    if ids != expected_ids:
        first_mismatch = next(
            (
                i
                for i, (actual, expected) in enumerate(
                    zip(ids, expected_ids),
                    start=1,
                )
                if actual != expected
            ),
            None,
        )
        if first_mismatch is None and len(ids) != len(expected_ids):
            first_mismatch = min(len(ids), len(expected_ids)) + 1

        validator.error(
            "labels: question_id sequence does not exactly match the "
            f"expected 116-120 A-F order"
            + (
                f" (first mismatch at record {first_mismatch})"
                if first_mismatch is not None
                else ""
            )
        )

    stats["ids"] = ids
    stats["primary_counts"] = primary_counts
    stats["label_width_counts"] = label_width_counts
    return stats


def validate_cross_file(
    question_stats: dict[str, Any],
    label_stats: dict[str, Any],
    validator: Validator,
) -> None:
    question_ids = question_stats.get("ids", [])
    label_ids = label_stats.get("ids", [])

    question_set = set(question_ids)
    label_set = set(label_ids)

    only_questions = sorted(question_set - label_set)
    only_labels = sorted(label_set - question_set)

    if only_questions:
        validator.error(
            "cross-file: question IDs with no label record: "
            + ", ".join(only_questions)
        )

    if only_labels:
        validator.error(
            "cross-file: label IDs with no question record: "
            + ", ".join(only_labels)
        )

    if question_ids != label_ids:
        mismatch = next(
            (
                i
                for i, (q_id, l_id) in enumerate(
                    zip(question_ids, label_ids),
                    start=1,
                )
                if q_id != l_id
            ),
            None,
        )

        if mismatch is None and len(question_ids) != len(label_ids):
            mismatch = min(len(question_ids), len(label_ids)) + 1

        validator.error(
            "cross-file: question_id order differs between files"
            + (
                f" (first mismatch at record {mismatch})"
                if mismatch is not None
                else ""
            )
        )


def print_summary(
    questions: list[LoadedRecord],
    labels: list[LoadedRecord],
    question_stats: dict[str, Any],
    label_stats: dict[str, Any],
    validator: Validator,
) -> None:
    question_types: Counter[str] = question_stats.get(
        "question_types",
        Counter(),
    )
    answer_statuses: Counter[str] = question_stats.get(
        "answer_statuses",
        Counter(),
    )
    label_width_counts: Counter[int] = label_stats.get(
        "label_width_counts",
        Counter(),
    )

    print("=== validation summary ===")
    print(f"questions:          {len(questions)}")
    print(f"labels:             {len(labels)}")
    print(f"multiple_choice:    {question_types['multiple_choice']}")
    print(f"numeric:            {question_types['numeric']}")
    print(f"answers ok:         {answer_statuses['ok']}")
    print(f"answers excluded:   {answer_statuses['excluded']}")
    print(f"answers missing:    {answer_statuses['missing']}")
    print(f"labels (1 field):   {label_width_counts[1]}")
    print(f"labels (2 fields):  {label_width_counts[2]}")
    print(f"labels (3 fields):  {label_width_counts[3]}")
    print()

    if validator.errors:
        print("=== errors ===")
        for error in validator.errors:
            print(f"[ERROR] {error}")
        print()
        print(f"ERRORS: {len(validator.errors)}")
        print("RESULT: FAILED")
    else:
        print("ERRORS: 0")
        print("RESULT: OK")


def parse_args() -> argparse.Namespace:
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent

    parser = argparse.ArgumentParser(
        description="Validate the final medexam JSONL outputs before SQLite import."
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=project_root / "output" / "questions_with_answers.jsonl",
        help="path to questions_with_answers.jsonl",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=project_root / "output" / "question_labels.jsonl",
        help="path to question_labels.jsonl",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validator = Validator()

    questions = load_jsonl(args.questions, validator, "questions")
    labels = load_jsonl(args.labels, validator, "labels")

    question_stats = validate_questions(questions, validator)
    label_stats = validate_labels(labels, validator)
    validate_cross_file(question_stats, label_stats, validator)

    print_summary(
        questions,
        labels,
        question_stats,
        label_stats,
        validator,
    )

    return 1 if validator.errors else 0


if __name__ == "__main__":
    sys.exit(main())
