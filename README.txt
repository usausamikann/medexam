暫定的なread me：

fixed_dataにscripts内のscript群をよしなに作用させて（バイブコーディング）、医師国試過去5年分をSQLite形式でいじれる.dbファイルにしました。
できたファイル（暫定）：[medexam_1.db](https://drive.google.com/file/d/1dHQtLHPT6CUB2NnV04YMZKPNybnlq7i5/view?usp=sharing)
できたファイルのread me（これもLLMが記述してくれました）：
medexam_1.db README
更新日：2026-09-24

============================================================
1. このDBについて
============================================================

medexam_1.db は、医師国家試験116〜120回の過去問を
SQLite形式で格納した学習用データベース。

問題本文・選択肢・正答・共通症例・医学分野ラベルを収録している。

元データは fixed_data/ 内のJSONLから生成した。


============================================================
2. 収録範囲
============================================================

対象：
- 第116回医師国家試験
- 第117回医師国家試験
- 第118回医師国家試験
- 第119回医師国家試験
- 第120回医師国家試験

収録件数：
- 問題：2000問
- 共通症例：100件
- 選択肢：9915件
- 正答レコード：1995件
- 分野ラベル：3282件

問題形式：
- multiple_choice：1983問
- numeric：17問

正答状態：
- ok：1991問
- excluded：9問
- missing：0問


============================================================
3. テーブル構成
============================================================

このDBには以下の5テーブルがある。

------------------------------------------------------------
3-1. questions
------------------------------------------------------------

問題本体を格納する中心テーブル。

主なカラム：
- question_id
  問題ID。例：116-A-001
  PRIMARY KEY

- exam
  国試回数。116〜120

- section
  A〜F

- number
  各section内の問題番号

- question_type
  multiple_choice または numeric

- case_id
  共通症例問題の場合、そのcase_id
  単独問題ではNULL

- stem
  問題文

- answer_kind
  choice または numeric

- answer_status
  ok / excluded / missing

- source_corpus
  元corpusファイルのパス


------------------------------------------------------------
3-2. choices
------------------------------------------------------------

選択肢を格納する。

主なカラム：
- question_id
- choice_label
  a〜e
- choice_text

PRIMARY KEY：
  (question_id, choice_label)

numeric問題にはchoicesレコードは存在しない。


------------------------------------------------------------
3-3. answers
------------------------------------------------------------

正答を格納する。

主なカラム：
- question_id
- answer_value

PRIMARY KEY：
  (question_id, answer_value)

複数正答問題では、1問に対して複数行存在する。

数値入力問題もanswer_valueはTEXTとして保存している。


------------------------------------------------------------
3-4. common_cases
------------------------------------------------------------

共通症例本文を格納する。

主なカラム：
- case_id
  PRIMARY KEY

- exam
- section
- text
  共通症例本文

- source_corpus

questions.case_id から参照される。


------------------------------------------------------------
3-5. question_labels
------------------------------------------------------------

医学分野ラベルを格納する。

主なカラム：
- question_id
- label
- is_primary

PRIMARY KEY：
  (question_id, label)

is_primary：
- 1 = primary label
- 0 = 副ラベル

各問題には1〜3個のラベルがあり、
primary labelは各問題につき1個。

ラベル総数：
- 1ラベル問題：932問
- 2ラベル問題：854問
- 3ラベル問題：214問


============================================================
4. 医学分野ラベル
============================================================

使用ラベル：

A   消化管
B   肝胆膵
C   循環器
D   内分泌・代謝
E   腎
F   免疫・膠原病
G   血液
H   感染症
I   呼吸器
J   神経
KL  救急・中毒
M   麻酔科・人工呼吸器
N   老年医学
O   小児科
P   乳腺
PQ  産婦人科
R   眼科
S   耳鼻咽喉科
T   整形外科
U   精神科
V   皮膚科
W   泌尿器
X   放射線
Y   公衆衛生


============================================================
5. SQLite CLIで開く
============================================================

medexamリポジトリ直下から：

  sqlite3 database/medexam_1.db

DBと同じフォルダへ移動してから開く場合：

  cd database
  sqlite3 medexam_1.db


============================================================
6. 最初に使うと便利なSQLiteコマンド
============================================================

テーブル一覧：

  .tables

questionsテーブルの定義：

  .schema questions

列名を表示：

  .headers on

表形式で表示：

  .mode column

SQLiteを終了：

  .quit


============================================================
7. SQL例
============================================================

問題数：

  SELECT COUNT(*) FROM questions;

先頭5問：

  SELECT *
  FROM questions
  LIMIT 5;

数値入力問題：

  SELECT question_id, stem
  FROM questions
  WHERE question_type = 'numeric';

120回の問題：

  SELECT question_id, stem
  FROM questions
  WHERE exam = 120;

primary labelが循環器（C）の問題：

  SELECT q.question_id, q.stem
  FROM questions AS q
  JOIN question_labels AS l
    ON q.question_id = l.question_id
  WHERE l.label = 'C'
    AND l.is_primary = 1;

循環器ラベルを含む120回の問題：

  SELECT q.question_id, q.stem
  FROM questions AS q
  JOIN question_labels AS l
    ON q.question_id = l.question_id
  WHERE q.exam = 120
    AND l.label = 'C';

ラベルごとの問題数：

  SELECT label, COUNT(*) AS n
  FROM question_labels
  GROUP BY label
  ORDER BY n DESC;

採点除外問題：

  SELECT question_id, stem
  FROM questions
  WHERE answer_status = 'excluded';


============================================================
8. テーブル間の関係
============================================================

概略：

  common_cases
       |
       | case_id
       v
  questions
     |   |   |
     |   |   +---- question_labels
     |   |
     |   +-------- answers
     |
     +------------ choices

questions が中心テーブル。

question_id を使って
choices / answers / question_labels とJOINする。

共通症例問題では
questions.case_id と common_cases.case_id をJOINする。


============================================================
9. データ生成元
============================================================

medexam_1.db は以下の確定データから生成した。

- fixed_data/cases.jsonl
- fixed_data/question_labels.jsonl
- fixed_data/questions_with_answers.jsonl

生成スクリプト：
- scripts/build_db.py

入力データ検証：
- scripts/validate_out.py


============================================================
10. 検証結果
============================================================

validate_out.py：

questions:          2000
labels:             2000
multiple_choice:    1983
numeric:            17
answers ok:         1991
answers excluded:   9
answers missing:    0
labels (1 field):   932
labels (2 fields):  854
labels (3 fields):  214

ERRORS: 0
RESULT: OK


build_db.py：

common_cases:       100
questions:          2000
choices:            9915
answers:            1995
question_labels:    3282
primary_labels:     2000
numeric_questions:  17
excluded_questions: 9
missing_answers:    0

RESULT: OK


============================================================
11. 注意事項
============================================================

- medexam_1.db はSQLiteのバイナリファイル。
  CSVやテキストファイルではない。

- DB本体はGit管理対象外。
  確定JSONLとbuild_db.pyから再生成可能。

- answer_status='excluded' の9問は採点除外問題。
  正答欠落とは区別している。

- numeric問題17問にはchoicesレコードが存在しない。

- question_labels.label は副ラベルを含む。
  primary分野だけを取得したい場合は
  is_primary = 1 を条件に加える。

- common_cases側にはquestion_ids配列を保持していない。
  questions.case_idを使えば、その症例に属する問題を取得できる。


以上。
