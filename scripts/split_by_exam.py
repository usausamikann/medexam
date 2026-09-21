from pathlib import Path
import json
from collections import Counter

# 入力
QUESTIONS_FILE = Path("output/questions_with_answers.jsonl")
CASES_FILE = Path("output/cases.jsonl")

# 出力先
OUTPUT_DIR = Path("output/by_exam")

EXAMS = range(116, 121)

EXPECTED_SECTIONS = {
    "A": 75,
    "B": 50,
    "C": 75,
    "D": 75,
    "E": 50,
    "F": 75,
}

EXPECTED_QUESTIONS_PER_EXAM = 400
EXPECTED_CASES_PER_EXAM = 20


def split_jsonl_by_exam(
    input_file: Path,
    output_name_format: str,
) -> dict[int, int]:
    """
    JSONLをexamごとに分割する。
    元のJSON文字列は書き換えず、そのまま出力する。
    """
    output_lines = {exam: [] for exam in EXAMS}

    with input_file.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"{input_file}:{line_no}: JSONの解析に失敗しました: {e}"
                ) from e

            exam = obj.get("exam")

            if exam in output_lines:
                # JSONを再生成せず、元の1行をそのまま保存
                output_lines[exam].append(line.rstrip("\n"))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts = {}

    for exam, lines in output_lines.items():
        output_file = OUTPUT_DIR / output_name_format.format(exam=exam)

        with output_file.open("w", encoding="utf-8", newline="\n") as f:
            for line in lines:
                f.write(line + "\n")

        counts[exam] = len(lines)

    return counts


def validate_questions():
    """分割後の問題ファイルを検証する。"""

    for exam in EXAMS:
        path = OUTPUT_DIR / f"questions_with_answers_{exam}.jsonl"

        records = []

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))

        # 件数
        assert len(records) == EXPECTED_QUESTIONS_PER_EXAM, (
            f"{exam}: 問題数が{len(records)}件です "
            f"(期待値 {EXPECTED_QUESTIONS_PER_EXAM})"
        )

        # 他年度混入チェック
        assert all(r["exam"] == exam for r in records), (
            f"{exam}: 他年度の問題が混入しています"
        )

        # question_id重複チェック
        question_ids = [r["question_id"] for r in records]
        assert len(question_ids) == len(set(question_ids)), (
            f"{exam}: question_idが重複しています"
        )

        # セクション数
        sections = Counter(r["section"] for r in records)

        assert sections == Counter(EXPECTED_SECTIONS), (
            f"{exam}: セクション別件数が不正です: {dict(sections)}"
        )

        print(
            f"{exam}: questions OK "
            f"({len(records)} questions, {dict(sections)})"
        )


def validate_cases():
    """分割後の共通症例ファイルを検証する。"""

    for exam in EXAMS:
        path = OUTPUT_DIR / f"cases_{exam}.jsonl"

        records = []

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))

        assert len(records) == EXPECTED_CASES_PER_EXAM, (
            f"{exam}: 共通症例数が{len(records)}件です "
            f"(期待値 {EXPECTED_CASES_PER_EXAM})"
        )

        assert all(r["exam"] == exam for r in records), (
            f"{exam}: 他年度の共通症例が混入しています"
        )

        case_ids = [r["case_id"] for r in records]
        assert len(case_ids) == len(set(case_ids)), (
            f"{exam}: case_idが重複しています"
        )

        print(f"{exam}: cases OK ({len(records)} cases)")


def main():
    question_counts = split_jsonl_by_exam(
        QUESTIONS_FILE,
        "questions_with_answers_{exam}.jsonl",
    )

    case_counts = split_jsonl_by_exam(
        CASES_FILE,
        "cases_{exam}.jsonl",
    )

    print("=== split ===")

    for exam in EXAMS:
        print(
            f"{exam}: "
            f"{question_counts[exam]} questions, "
            f"{case_counts[exam]} cases"
        )

    print("\n=== validation ===")

    validate_questions()
    validate_cases()

    print("\nすべて正常に分割できました。")


if __name__ == "__main__":
    main()