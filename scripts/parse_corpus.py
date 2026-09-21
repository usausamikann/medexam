from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ----------------------------
# 正規表現
# ----------------------------

QUESTION_RE = re.compile(r"^(\d+)\s+(.+)$")
CHOICE_RE = re.compile(r"^([a-e])\s+(.+)$")

PAIR_CASE_RE = re.compile(
    r"^次の文を読み、(\d+)、(\d+)の問いに答えよ。$"
)

RANGE_CASE_RE = re.compile(
    r"^次の文を読み、(\d+)[~～](\d+)の問いに答えよ。$"
)

FILE_RE = re.compile(r"^(\d+)_([A-F])\.txt$")

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

# ----------------------------
# データ構造
# ----------------------------

@dataclass
class Choice:
    label: str
    text: str


@dataclass
class Question:
    exam: int
    section: str
    number: int
    stem_lines: list[str] = field(default_factory=list)
    choices: list[Choice] = field(default_factory=list)
    case_id: str | None = None
    source: str = ""

    @property
    def question_id(self) -> str:
        return f"{self.exam}-{self.section}-{self.number:03d}"

    @property
    def question_type(self) -> str:
        if self.question_id in NUMERIC_QUESTION_IDS:
            return "numeric"
        return "multiple_choice"

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "exam": self.exam,
            "section": self.section,
            "number": self.number,
            "question_type": self.question_type,
            "case_id": self.case_id,
            "stem": "\n".join(self.stem_lines).strip(),
            "choices": [
                {
                    "label": choice.label,
                    "text": choice.text,
                }
                for choice in self.choices
            ],
            "source": {
                "corpus": self.source,
            },
        }


@dataclass
class Case:
    exam: int
    section: str
    first_question: int
    last_question: int
    text_lines: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def case_id(self) -> str:
        return (
            f"{self.exam}-{self.section}-"
            f"{self.first_question:03d}-{self.last_question:03d}"
        )

    @property
    def question_ids(self) -> list[str]:
        return [
            f"{self.exam}-{self.section}-{n:03d}"
            for n in range(self.first_question, self.last_question + 1)
        ]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "exam": self.exam,
            "section": self.section,
            "question_ids": self.question_ids,
            "text": "\n".join(self.text_lines).strip(),
            "source": {
                "corpus": self.source,
            },
        }


@dataclass
class ReviewItem:
    source: str
    question_id: str
    warning: str


# ----------------------------
# 補助関数
# ----------------------------

def parse_filename(path: Path) -> tuple[int, str]:
    m = FILE_RE.match(path.name)
    if not m:
        raise ValueError(
            f"ファイル名を解釈できない: {path.name}"
        )

    exam = int(m.group(1))
    section = m.group(2)

    return exam, section


def normalize_line(line: str) -> str:
    """
    corpusの内容を積極的に改変しない。
    行末だけ除去する。
    """
    return line.rstrip("\r\n")


def parse_case_marker(line: str) -> tuple[int, int] | None:
    """
    例:
      次の文を読み、40、41の問いに答えよ。
      次の文を読み、60~62の問いに答えよ。
    """

    m = PAIR_CASE_RE.match(line)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = RANGE_CASE_RE.match(line)
    if m:
        return int(m.group(1)), int(m.group(2))

    return None


# ----------------------------
# 問題ブロック処理
# ----------------------------

def parse_question_block(
    exam: int,
    section: str,
    number: int,
    lines: list[str],
    case_id: str | None,
    source: str,
) -> Question:
    """
    問題番号以降〜次の問題番号直前までを、
    stem と choices に分ける。
    """

    question = Question(
        exam=exam,
        section=section,
        number=number,
        case_id=case_id,
        source=source,
    )

    current_choice: Choice | None = None
    choices_started = False

    for line in lines:
        if not line.strip():
            continue

        m = CHOICE_RE.match(line)

        if m:
            choices_started = True

            current_choice = Choice(
                label=m.group(1),
                text=m.group(2).strip(),
            )

            question.choices.append(current_choice)
            continue

        # 選択肢開始後の非 a-e 行は、
        # 直前の選択肢の折り返しとみなす
        if choices_started and current_choice is not None:
            current_choice.text += "\n" + line.strip()

        else:
            question.stem_lines.append(line.strip())

    return question


# ----------------------------
# 1ファイルのパース
# ----------------------------

def parse_file(
    path: Path,
    project_root: Path,
) -> tuple[list[Question], list[Case], list[ReviewItem]]:

    exam, section = parse_filename(path)

    source = str(path.relative_to(project_root))

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=None,
    ) as f:
        lines = [normalize_line(line) for line in f]

    questions: list[Question] = []
    cases: list[Case] = []
    reviews: list[ReviewItem] = []

    current_question_number: int | None = None
    current_question_lines: list[str] = []

    current_case: Case | None = None

    # 共通症例文を集めている最中か
    collecting_case_text = False

    # 次に来るはずの問題番号
    expected_question = 1

    def case_for_question(number: int) -> str | None:
        if current_case is None:
            return None

        if (
            current_case.first_question
            <= number
            <= current_case.last_question
        ):
            return current_case.case_id

        return None

    def flush_question() -> None:
        nonlocal current_question_number
        nonlocal current_question_lines

        if current_question_number is None:
            return

        q = parse_question_block(
            exam=exam,
            section=section,
            number=current_question_number,
            lines=current_question_lines,
            case_id=case_for_question(current_question_number),
            source=source,
        )

        questions.append(q)

        current_question_number = None
        current_question_lines = []

    def flush_case() -> None:
        nonlocal current_case

        if current_case is None:
            return

        cases.append(current_case)
        current_case = None

    for line in lines:

        stripped = line.strip()

        # ----------------------------
        # 共通症例マーカー
        # ----------------------------

        marker = parse_case_marker(stripped)

        if marker is not None:
            flush_question()
            flush_case()

            first_q, last_q = marker

            current_case = Case(
                exam=exam,
                section=section,
                first_question=first_q,
                last_question=last_q,
                source=source,
            )

            collecting_case_text = True

            continue

        # ----------------------------
        # 問題番号候補
        # ----------------------------

        qmatch = QUESTION_RE.match(stripped)

        if qmatch:
            candidate_number = int(qmatch.group(1))

            # 最重要:
            # 「行頭が数字」だけでは問題番号扱いしない。
            # 次に来るはずの番号と一致するときだけ採用する。
            if candidate_number == expected_question:

                flush_question()

                # 症例文収集中なら、
                # 最初の設問が始まった時点で症例文終了
                if (
                    collecting_case_text
                    and current_case is not None
                    and candidate_number
                    == current_case.first_question
                ):
                    collecting_case_text = False

                current_question_number = candidate_number
                current_question_lines = [
                    qmatch.group(2).strip()
                ]

                expected_question += 1

                continue

        # ----------------------------
        # 共通症例本文
        # ----------------------------

        if collecting_case_text and current_case is not None:

            if stripped:
                current_case.text_lines.append(stripped)

            continue

        # ----------------------------
        # 通常の問題本文
        # ----------------------------

        if current_question_number is not None:
            current_question_lines.append(line)


    flush_question()
    flush_case()

    # ----------------------------
    # 検査
    # ----------------------------

    if questions:
        numbers = [q.number for q in questions]

        expected_numbers = list(
            range(1, max(numbers) + 1)
        )

        if numbers != expected_numbers:
            missing = sorted(
                set(expected_numbers) - set(numbers)
            )

            reviews.append(
                ReviewItem(
                    source=source,
                    question_id="FILE",
                    warning=(
                        "問題番号が連番でない。"
                        f" missing={missing}"
                    ),
                )
            )

    else:
        reviews.append(
            ReviewItem(
                source=source,
                question_id="FILE",
                warning="問題を1問も検出できなかった",
            )
        )

    # 個々の問題を検査
    for q in questions:

        # stemなし
        if not q.stem_lines:
            reviews.append(
                ReviewItem(
                    source=source,
                    question_id=q.question_id,
                    warning="stemが空",
                )
            )

        if q.question_type == "multiple_choice" and len(q.choices) != 5:
            reviews.append(
                ReviewItem(
                    source=source,
                    question_id=q.question_id,
                    warning=f"選択肢数={len(q.choices)}",
                )
            )

        if q.question_type == "numeric" and len(q.choices) != 0:
            reviews.append(
                ReviewItem(
                    source=source,
                    question_id=q.question_id,
                    warning=f"numericなのに選択肢数={len(q.choices)}",
                )
            )

        labels = [c.label for c in q.choices]

        if labels and labels != sorted(labels):
            reviews.append(
                ReviewItem(
                    source=source,
                    question_id=q.question_id,
                    warning=(
                        f"選択肢順序が不自然: {labels}"
                    ),
                )
            )

        if len(labels) != len(set(labels)):
            reviews.append(
                ReviewItem(
                    source=source,
                    question_id=q.question_id,
                    warning=(
                        f"選択肢ラベル重複: {labels}"
                    ),
                )
            )

    # 共通症例を検査
    question_ids = {
        q.question_id
        for q in questions
    }

    for case in cases:

        if not case.text_lines:
            reviews.append(
                ReviewItem(
                    source=source,
                    question_id=case.case_id,
                    warning="共通症例本文が空",
                )
            )

        for qid in case.question_ids:
            if qid not in question_ids:
                reviews.append(
                    ReviewItem(
                        source=source,
                        question_id=qid,
                        warning=(
                            f"共通症例 {case.case_id} に対応する"
                            "問題が存在しない"
                        ),
                    )
                )

    return questions, cases, reviews


# ----------------------------
# 出力
# ----------------------------

def write_jsonl(
    path: Path,
    items: list[dict],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:

        for item in items:
            f.write(
                json.dumps(
                    item,
                    ensure_ascii=False,
                )
            )
            f.write("\n")


def write_review_tsv(
    path: Path,
    reviews: list[ReviewItem],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:

        f.write(
            "source\tquestion_id\twarning\n"
        )

        for r in reviews:

            warning = (
                r.warning
                .replace("\t", " ")
                .replace("\n", " ")
            )

            f.write(
                f"{r.source}\t"
                f"{r.question_id}\t"
                f"{warning}\n"
            )


# ----------------------------
# main
# ----------------------------

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "医師国家試験 corpus を "
            "JSONL に変換する"
        )
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="変換する corpus txt",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="出力先",
    )

    args = parser.parse_args()

    project_root = Path.cwd().resolve()

    all_questions: list[Question] = []
    all_cases: list[Case] = []
    all_reviews: list[ReviewItem] = []

    for raw_path in args.files:

        path = raw_path.resolve()

        try:
            questions, cases, reviews = parse_file(
                path,
                project_root,
            )

        except Exception as e:
            print(
                f"[ERROR] {path}: {e}",
                file=sys.stderr,
            )
            return 1

        all_questions.extend(questions)
        all_cases.extend(cases)
        all_reviews.extend(reviews)

        print(
            f"[OK] {path.name}: "
            f"questions={len(questions)}, "
            f"cases={len(cases)}, "
            f"warnings={len(reviews)}"
        )

    output_dir = args.output_dir

    write_jsonl(
        output_dir / "questions.jsonl",
        [q.to_dict() for q in all_questions],
    )

    write_jsonl(
        output_dir / "cases.jsonl",
        [c.to_dict() for c in all_cases],
    )

    write_review_tsv(
        output_dir / "parse_review.tsv",
        all_reviews,
    )

    print()
    print(
        f"questions: {len(all_questions)}"
    )
    print(
        f"cases:     {len(all_cases)}"
    )
    print(
        f"warnings:  {len(all_reviews)}"
    )

    print()
    print(
        f"output: {output_dir}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())