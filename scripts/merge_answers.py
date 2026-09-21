from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


QUESTIONS_PATH = Path("output/questions.jsonl")
ANSWER_DIR = Path("raw/corpus/answer")

OUTPUT_PATH = Path("output/questions_with_answers.jsonl")
REVIEW_PATH = Path("output/answer_review.tsv")

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

@dataclass
class AnswerRecord:
    question_id: str
    answers: list[str]
    source: str


def make_question_id(
    exam: str,
    section: str,
    number: str,
) -> str:
    return f"{int(exam)}-{section.upper()}-{int(number):03d}"


def load_questions(path: Path) -> list[dict]:
    questions = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        for line in f:
            if not line.strip():
                continue

            questions.append(json.loads(line))

    return questions


def load_answers(answer_dir: Path) -> dict[str, AnswerRecord]:
    answers: dict[str, AnswerRecord] = {}

    for path in sorted(answer_dir.glob("*.tsv")):
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            reader = csv.DictReader(
                f,
                delimiter="\t",
            )

            for row in reader:
                question_id = make_question_id(
                    row["exam"],
                    row["section"],
                    row["number"],
                )

                accepted_answers = []

                for column in (
                    "answer_1",
                    "answer_2",
                    "answer_3",
                    "answer_4",
                ):
                    value = (row.get(column) or "").strip()

                    if value:
                        accepted_answers.append(value)

                if question_id in answers:
                    raise ValueError(
                        f"正答データが重複している: {question_id}"
                    )

                answers[question_id] = AnswerRecord(
                    question_id=question_id,
                    answers=accepted_answers,
                    source=str(path),
                )

    return answers


def main() -> None:
    questions = load_questions(QUESTIONS_PATH)
    answers = load_answers(ANSWER_DIR)

    question_ids = {
        q["question_id"]
        for q in questions
    }

    reviews: list[tuple[str, str]] = []

    merged = []

    for q in questions:
        question_id = q["question_id"]

        answer_record = answers.get(question_id)

        if answer_record is None:
            reviews.append(
                (
                    question_id,
                    "正答TSVに対応する行がない",
                )
            )

            accepted_answers = []
            answer_status = "missing"

        elif not answer_record.answers:
            if question_id in EXCLUDED_QUESTION_IDS:
                accepted_answers = []
                answer_status = "excluded"
            else:
                reviews.append(
                    (
                        question_id,
                        "正答欄が空",
                    )
                )
                accepted_answers = []
                answer_status = "missing"

        else:
            accepted_answers = answer_record.answers
            answer_status = "ok"

        question_type = q["question_type"]

        if question_type == "multiple_choice":
            answer_kind = "choice"

        elif question_type == "numeric":
            answer_kind = "numeric"

        else:
            answer_kind = "unknown"

        q["answer_kind"] = answer_kind
        q["accepted_answers"] = accepted_answers
        q["answer_status"] = answer_status

        merged.append(q)

    # TSV側にだけ存在する謎の問題がないか確認
    for question_id in answers:
        if question_id not in question_ids:
            reviews.append(
                (
                    question_id,
                    "正答TSVに存在するがquestions.jsonlに存在しない",
                )
            )

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:
        for q in merged:
            f.write(
                json.dumps(
                    q,
                    ensure_ascii=False,
                )
            )
            f.write("\n")

    with REVIEW_PATH.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:
        f.write("question_id\twarning\n")

        for question_id, warning in reviews:
            f.write(
                f"{question_id}\t{warning}\n"
            )

    ok_count = sum(
        q["answer_status"] == "ok"
        for q in merged
    )

    missing_count = sum(
        q["answer_status"] == "missing"
        for q in merged
    )

    choice_count = sum(
        q["answer_kind"] == "choice"
        for q in merged
    )

    numeric_count = sum(
        q["answer_kind"] == "numeric"
        for q in merged
    )

    print(f"questions:       {len(merged)}")
    print(f"answers ok:      {ok_count}")
    print(f"answers missing: {missing_count}")
    print(f"choice:          {choice_count}")
    print(f"numeric:         {numeric_count}")
    print(f"warnings:        {len(reviews)}")
    print()
    print(f"output: {OUTPUT_PATH}")
    print(f"review: {REVIEW_PATH}")


if __name__ == "__main__":
    main()