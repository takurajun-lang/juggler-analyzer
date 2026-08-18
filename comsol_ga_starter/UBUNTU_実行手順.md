# 実験室 Ubuntu PC での実行手順（Ubuntu初心者向け）

**目的：FEM を無駄に回さずに、Python–COMSOL の閉ループが本当につながっているかを段階的に確認する。**

いきなり世代を回さないこと。段階 7 までは合計 10 回の FEM 評価で済む。

この文書は「Ubuntu の端末（ターミナル）をほとんど触ったことがない」ことを前提に書いている。
すでに端末操作に慣れている場合は、段階 0-a は読み飛ばしてよい。

---

## 段階 0-a. 端末（ターミナル）の基礎（初めての人向け）

### 端末とは何か

普段マウスでアイコンをクリックする代わりに、文字でコマンドを打ってPCを操作する画面のこと。
このガイドの `$` から始まる行は、すべて端末に打ち込むコマンドである（`$` 自体は入力しない）。

### 端末の開き方

- `Ctrl + Alt + T` を押す。
- または画面左下（または「アクティビティ」）から「端末」「Terminal」を検索して開く。

### コピー＆ペーストの注意

端末では `Ctrl+C` は「実行中の処理を中断する」という別の意味を持つため使えない。
代わりに次を使う。

- コピー: `Ctrl + Shift + C`
- 貼り付け: `Ctrl + Shift + V`

（右クリックメニューの「貼り付け」でもよい）

### 最低限のコマンド

| コマンド | 意味 |
|---|---|
| `pwd` | 今いる場所（フォルダ）を表示する |
| `ls` | 今いる場所の中身を一覧表示する |
| `ls -la` | 隠しファイルも含めて詳しく一覧表示する |
| `cd フォルダ名` | そのフォルダに移動する |
| `cd ..` | 一つ上のフォルダに戻る |
| `cd ~` | ホームフォルダ（自分の作業起点）に戻る |
| `cat ファイル名` | ファイルの中身をそのまま表示する |
| `mkdir 名前` | フォルダを新しく作る |

コマンドがうまく動かず「command not found」と出た場合、そのコマンド（プログラム）が
インストールされていない。多くは次でインストールできる（実行にはパスワードを聞かれる）。

```bash
sudo apt update
sudo apt install <パッケージ名>    # 例: sudo apt install unzip
```

`sudo` は「管理者権限で実行する」の意味である。パスワード入力中は画面に何も表示されないが、
それで正常（打てているので、そのまま Enter でよい）。

---

## 段階 0. フォルダを置く

```bash
cd ~/work
unzip comsol_ga_starter.zip     # または scp / USB でコピー
cd comsol_ga_starter
ls
```

補足：

- `~/work` フォルダが無い場合は先に `mkdir -p ~/work` を実行してから `cd ~/work` する。
- `unzip: command not found` と出た場合は `sudo apt install unzip` を実行してからやり直す。
- `ls` を実行して `ga_comsol.py` や `README_ja.md` が見えていれば、この段階は成功である。

---

## 段階 1. Python 側だけを確認する（COMSOL 不要）

```bash
python3 --version          # 3.9 以降であること
python3 ga_comsol.py config.mock.json
```

`command not found` と出たら `python` ではなく必ず `python3` と打っているか確認する
（Ubuntu では `python3` が正式なコマンド名である）。

このコマンドは COMSOL を一切使わず、GA（遺伝的アルゴリズム）の動作だけを、
数式でできた「偽の評価関数」で確認するものである。COMSOL の代わりに数式が
一瞬で答えを返すので、数秒で終わる。

### 画面に出る内容の読み方

```text
[世代 0] 最良 97.4302  平均 24.6266  失敗 0  最良個体 ew=11.5669, eg=3.9259, el=47.3535
```

- `世代` : 何世代目か（0 は最初のランダムな10個体）。
- `最良` : その世代でいちばん良かった適応度（数字が大きいほど良い）。
- `平均` : その世代の平均適応度。
- `失敗` : 評価に失敗した個体数（mock では通常 0）。
- `最良個体` : そのときの一番良い電極寸法。

世代が進むほど「最良」「平均」が大きくなっていけば、GA は正しく動いている。

### 期待される最終結果

- 最終的に `ew ≒ 12`, `eg ≒ 4`, `el ≒ 45` 付近に寄る（模擬関数の既知最適点であり、
  実際の電極設計値ではない）。
- `runs/run_<日時>/` に `ga.log`, `evaluations.csv`, `history.csv`, `best.json` ができる。

ここで失敗する場合は Python 側の問題であり、COMSOL は関係ない。

### 結果ファイルを見る（端末が苦手な人向け）

CSVファイルは端末で `cat runs/run_.../evaluations.csv` と打っても見られるが、
表として見たい場合はファイルマネージャで `runs` フォルダを開き、CSVファイルを
ダブルクリックして LibreOffice Calc（Ubuntu 標準の表計算ソフト）で開いてもよい。

### 比較用の別方式も動く

```bash
python3 ga_comsol.py config.mock.json --method blx_ga
python3 ga_comsol.py config.mock.json --method uniform_ga
```

---

## 段階 2. COMSOL が CLI から起動できるか確認する

```bash
which comsol
comsol -version
```

`which comsol` は「`comsol` というコマンドがどこにあるか」を調べるコマンドである。
何かパス（例 `/usr/local/comsol64/multiphysics/bin/comsol`）が表示されれば、
そのまま `comsol` という名前で使える。

`which comsol` が何も返さない場合は、インストール先の絶対パスを探す。

```bash
ls -d /usr/local/comsol*/multiphysics/bin/comsol
```

（`ls -d` はフォルダ自体の存在を確認するオプション。バージョン番号違いなどで
候補が複数出ることがある）

見つかったパスを、後で設定の `comsol.executable` に**絶対パスで**書く
（`which` で見つからなかった場合はコマンド名 `comsol` だけでは動かない）。

ライセンスの確認も先にしておく。

```bash
comsol batch -help | head -40
```

`|` （パイプ）は「前のコマンドの出力を次のコマンドに渡す」という意味で、
`head -40` は「最初の40行だけ表示する」の意味である。ヘルプが表示されず
ライセンスエラーが出る場合は、この段階で研究室のCOMSOL担当者かIT担当に確認する。

---

## 段階 3. COMSOL GUI で `ga_electrode_base.mph` を用意する

ここから先は Ubuntu の使い方ではなく、COMSOL モデル自体の準備であり、
研究内容の判断（境界条件・材料物性・メッシュなど）が必要になる。
このガイドではモデル固有の式やタグを決め打ちしないので、以下は方針のみ示す。
詳細は `README_ja.md` の「6. COMSOL 側で必要な準備」も参照。

1. 元モデルを**複製**して `ga_electrode_base.mph` として保存する（元は絶対に触らない）。
2. `Global Definitions > Parameters` に `ew`, `eg`, `el` を追加する。
3. 電極 Geometry だけをパラメータ式に置き換える。

   | 電極 | x位置 | y位置 | 幅 | 高さ |
   |---|---:|---:|---:|---:|
   | 左 | `-eg/2-ew` | `-el/2` | `ew` | `el` |
   | 右 | `eg/2` | `-el/2` | `ew` | `el` |

4. Terminal / Ground / 材料割り当てを**名前付き Selection** に置き換える。
   境界番号の直接指定のままだと、寸法が変わった瞬間に別の境界を指してしまう。
5. `Results > Derived Values`（または Evaluation Group）で `Smin` を定義する。
6. `Export to File` の出力先を、**相対パスの `fitness.csv`** にする。
7. Study の Job Configurations に `Evaluate Derived Values` と `Export to File` を追加する。
   - `Show More Options` → `Solver and Job Configurations` を有効化
   - `dummy=1` の1点 Parametric Sweep を追加
   - Geometry パラメータのため `Use parametric solver` は **Off**
   - `Show Default Solver` を実行
8. GUI 上で 1 回計算し、`fitness.csv` が出ること、その値を控えておく。

---

## 段階 4. CLI で 1 条件だけ手動実行する（ここが最大の関門）

GA を通さず、基準寸法 1 点だけを直接叩く。

```bash
mkdir -p /tmp/comsol_test && cd /tmp/comsol_test

comsol batch \
  -inputfile ~/work/ga_electrode_base.mph \
  -pname ew,eg,el \
  -plist '10[um],5[um],30[um]' \
  -study std1 \
  -outputdir "$PWD" \
  -np 1 \
  -nosave

ls -l fitness.csv
cat fitness.csv
```

補足：`\` は「コマンドが長いので次の行へ続く」という意味の記号であり、そのまま
コピペしてよい。`"$PWD"` は「今いるフォルダの絶対パス」に自動的に置き換わる。

確認すること:

- 終了コードが 0 である（`echo $?` で確認。直前のコマンドの終了コードを表示する）。
- `fitness.csv` が **`-outputdir` で指定したフォルダに**出ている。
  MPH 側のパスが絶対パスだと別の場所に出るので、その場合は相対パスに直す。
- 値が GUI で計算したときと**一致する**。

一致しない場合、GA を回しても意味がない。ここで止めて原因を潰す。

---

## 段階 5. 設定ファイルを実環境に合わせる

```bash
cd ~/work/comsol_ga_starter
cp config.comsol.ubuntu.example.json config.comsol.ubuntu.json
nano config.comsol.ubuntu.json
```

`nano` はターミナルの中で使える簡単な文字エディタである。初めて使う場合の操作:

| キー操作 | 動作 |
|---|---|
| 矢印キー | カーソル移動 |
| そのままタイプ | 文字を書き換える／追加する |
| `Ctrl + O` → `Enter` | 保存する（画面下の `^O Write Out` に対応） |
| `Ctrl + X` | 終了する（保存前なら「保存するか」聞かれる） |

直す箇所:

| キー | 内容 |
|---|---|
| `comsol.executable` | `comsol`、または段階 2 で見つけた絶対パス |
| `comsol.inputfile` | `ga_electrode_base.mph` の絶対パス |
| `comsol.study` | 実際の Study タグ（既定 `std1`） |
| `comsol.fitness_parser` | 段階 4 で見た `fitness.csv` の列構造に合わせる |
| `variables[].min/max` | 製造制約・細胞径・メッシュ品質を踏まえた実際の範囲 |

`fitness.csv` が周波数走査で複数行になり、`Smin` が 3 列目（0 始まりで 2）なら:

```json
"fitness_parser": { "mode": "column_max", "column": 2 }
```

最終行の最終列に 1 つだけスカラーが出るなら、既定の `last_numeric` のままでよい。

組み立てられるコマンドは実行せずに確認できる。

```bash
python3 ga_comsol.py config.comsol.ubuntu.json --dry-run
```

段階 4 で手打ちしたコマンドと同じ形になっているか見比べる。

---

## 段階 6. `generations: 0` で回す（FEM 10 回）

設定の `ga.generations` が `0` であることを確認して実行する。

```bash
python3 ga_comsol.py config.comsol.ubuntu.json
```

これはランダム 10 個体を評価するだけで、交叉も突然変異もしない。
目的は最適化ではなく、**10 通りの寸法すべてで FEM が通るか**を見ることである。

この実行は実際に COMSOL を10回起動するため、段階4で1回実行したときの
所要時間の目安から、終わるまでの時間を見積もっておくとよい
（ターミナルはコマンドが終わるまで次のコマンドを受け付けない）。

---

## 段階 7. 10 個体分の出力を全部見る

```bash
R=$(ls -dt runs/run_* | head -1)
cat $R/evaluations.csv          # status 列が全部 OK か
cat $R/ga.log
ls $R/jobs/                     # eval_00001 ... eval_00010
cat $R/jobs/eval_00001/fitness.csv
cat $R/jobs/eval_00001/stderr.log
```

`$(...)` は「中のコマンドの実行結果を文字として使う」という意味である。
ここでは「一番新しい `runs/run_*` フォルダの名前」を `R` という変数に入れている。

チェック項目:

- `status` が `FAILED` の個体はどの寸法か。メッシュ失敗なら変数範囲が広すぎる。
- `raw_fitness` が全個体で同じ値になっていないか。
  同じなら Geometry がパラメータで動いていない（`-pname` が効いていない）疑いが濃い。
- `seconds` 列で 1 個体あたりの所要時間を測る。これが以降の計画の基礎になる。
- `top` や `free -g` でメモリを見ておく（`top` は `q` キーで終了する）。

**1 個体の所要時間 × 34 が、次の段階のおおよその所要時間である。**

---

## 段階 8. 世代を少しずつ増やす

```bash
python3 ga_comsol.py config.comsol.ubuntu.json --generations 1   # 追加 8 回
python3 ga_comsol.py config.comsol.ubuntu.json --generations 3   # 合計 34 回
```

個体数10・エリート2・追加3世代なら、重複がなければ

```text
10 + (10 - 2) × 3 = 34 回
```

の FEM 計算になる。

`history.csv` の `best_raw_fitness` が世代とともに改善しているかを確認する。
改善しない場合は、変数範囲・`sbx_eta`・突然変異率を見直す。

---

## 段階 9. 並列化の判断

最初は `comsol.np` を `1` にした逐次実行にする。
段階 7 で実測した時間・メモリ・**ライセンス数**をもとに、はじめて並列化を検討する。

同時に走らせる COMSOL の本数はライセンスに直結するので、増やす前に必ず確認すること。

---

## よくある失敗

### Ubuntu・端末まわり（初心者がよくつまずく点）

| 症状 | 原因の候補 |
|---|---|
| `command not found: python` | `python` ではなく `python3` と打つ |
| `command not found: unzip` | `sudo apt install unzip` を実行してからやり直す |
| コピペした `\` 付きコマンドが変な動きをする | 貼り付け後に余分な改行や全角スペースが混ざっていないか確認する |
| `sudo` でパスワードを打っても何も表示されない | 正常な仕様。見えないまま打ち切って Enter でよい |
| 日本語が文字化けする | `locale` で `ja_JP.UTF-8` が入っているか確認し、無ければ `sudo apt install language-pack-ja` |
| `Permission denied` | 自分のフォルダ（`~/work` 配下など）で作業しているか確認する。他人の領域には書き込めない |
| `nano` の保存の仕方がわからない | `Ctrl+O` → `Enter`（保存）→ `Ctrl+X`（終了） |

### GA・COMSOL連携まわり

| 症状 | 原因の候補 |
|---|---|
| `comsol が PATH 上に見つかりません` | `comsol.executable` を絶対パスにする |
| `fitness.csv が出力されていません` | MPH 側の Export 先が絶対パス。相対パスに直す |
| 全個体の適応度が同一 | Geometry がパラメータ式になっていない／`-pname` の綴り違い |
| 一部の寸法だけ `FAILED` | メッシュ生成失敗。変数の下限を上げる |
| Terminal/Ground がおかしい | 境界番号の直接指定。名前付き Selection に置き換える |
| `数値データ行が見つかりません` | `fitness_parser.delimiter` がタブ区切りなどとずれている |

---

## この手順でわからないことがあったら

- Python・GA側の一般的な使い方は `README_ja.md` を参照する。
- COMSOLモデル固有の設定（式・境界番号・Selection名など）は、このリポジトリのコードでは
  一切決め打ちしていない。研究室で使っているモデルに合わせて、担当者と相談して埋めること。
