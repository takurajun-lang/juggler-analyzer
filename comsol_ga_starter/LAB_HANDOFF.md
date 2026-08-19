# 実験室 Ubuntu PC への手引き

## 概要

このドキュメントは、クラウド Ubuntu での初期検証を完了した GA-COMSOL ループを、実験室 PC（COMSOL インストール済み）で実運用するための手引きです。

---

## Phase 1: セットアップ確認（実験室 PC）

### 1.1 環境確認

```bash
# このリポジトリを clone
git clone https://github.com/takurajun-lang/juggler-analyzer.git
cd juggler-analyzer/comsol_ga_starter

# COMSOL が PATH に含まれているか確認
which comsol
# または
comsol -version
```

期待される出力例:
```
COMSOL 6.4.0.293 (Build: ..., ...)
```

### 1.2 設定ファイルの準備

```bash
# テンプレートから実運用用設定を作成
cp config.comsol.ubuntu.example.json config.comsol.ubuntu.json

# エディタで以下を編集（実環境に合わせる）:
#   - comsol.inputfile: ga_electrode_base.mph の絶対パス
#   - comsol.executable: 必要に応じて絶対パスに変更（which comsol で確認）
nano config.comsol.ubuntu.json
```

### 1.3 セットアップ検証スクリプトの実行

```bash
python3 validate_comsol_setup.py
```

期待される出力:
```
✓ PASS: COMSOL Executable
✓ PASS: Model File
✓ PASS: Fitness CSV Format
✓ PASS: Parametric Sweep Structure
✓ PASS: GA Integration

Total: 5/5 checks passed
```

---

## Phase 2: COMSOL モデルの設定

### 2.1 18-点 Parametric Sweep の確認

COMSOL GUI を起動:
```bash
comsol &
```

**File > Open**: `ga_electrode_base.mph` を開く

**Geometry** タブ:
- Parameters（ew, eg, el, cell_on, cellx）が定義されているか確認
- 電極の形状がパラメータに応じて変化するか確認

**Physics** タブ:
- Current Conservation （2つ）
- Material properties が cell_on でブレンドされているか確認
- Boundary Conditions（Terminal/Ground）が Box Selections 経由で指定されているか確認

**Study** タブ:
- Stationary Frequency Domain Study（std1）が定義されているか確認
- Parametric Sweep ステップが以下で構成されているか確認:
  ```
  cell_on: 0, 1           (2 values)
  cellx: 9-point sweep    (range: -(eg/2+ew/2) to +(eg/2+ew/2))
  Frequency: 10^2 ~ 10^9 Hz (36 points logarithmic)
  ```

**検証**: Study > Compute > Compute を実行（小規模テスト用）
- 最初の 1-2 個体計算が完了し、エラーが出ないことを確認

### 2.2 Global Evaluation と Export の追加

**手順**: `COMSOL_SMIN_SETUP.md` を参照して以下を追加します:

1. **Definitions > Derived Values > Global Evaluation** を追加
   - 名前: `Smin`
   - Expression: `COMSOL_SMIN_SETUP.md` の「Step 1」に記載の式を入力

2. **Study > Compute > Export** ステップを追加（なければ作成）
   - Quantity to Export: `Smin`
   - File name: `fitness.csv`
   - Format: CSV

3. **File > Save** で変更を保存

### 2.3 動作確認（GUI ）

**Study > Compute > Compute All** を実行:

出力例:
```
Parametric sweep: step 1 of 18
Parametric sweep: step 2 of 18
...
Parametric sweep: step 18 of 18
```

完了後、ジョブディレクトリに `fitness.csv` が生成されていることを確認:
```bash
ls -la [COMSOL GUI の作成ディレクトリ]/fitness.csv
cat [COMSOL GUI の作成ディレクトリ]/fitness.csv
```

期待される形式:
```
1.23456789
```

---

## Phase 3: GA ループの実行

### 3.1 テスト実行（単体評価）

```bash
# 設定ファイルの最終確認
cat config.comsol.ubuntu.json | grep -A5 "inputfile\|fitness_file"

# 1 個体のみ実行（COMSOL 経由で fitness.csv が生成されるか確認）
python3 ga_comsol.py config.comsol.ubuntu.json -generate 1
```

期待される動作:
1. `runs/run_<timestamp>/` ディレクトリが作成
2. `jobs/eval_00001/` サブディレクトリが作成
3. COMSOL が実行
4. `fitness.csv` が生成され、GA が読み込み
5. 評価値が出力される

出力例:
```
generation 0 / 0
  [eval_00001] raw_fitness = 1.234, internal_fitness = 1.234, seconds = 312.5
  best_raw_fitness = 1.234, mean_raw_fitness = 1.234
```

### 3.2 本格実行（GA ループ）

```bash
# GA パラメータの確認
cat config.comsol.ubuntu.json | jq '.ga'

# 例: population_size=10, generations=3
python3 ga_comsol.py config.comsol.ubuntu.json
```

実行中の進捗確認:
```bash
# 別ターミナルで実行ディレクトリを監視
ls -la runs/run_*/jobs/
tail -f runs/run_*/logfile.csv
```

期待される実行時間:
- 1 個体: ~5-10 分（COMSOL 計算と Parametric Sweep による）
- 10 個体: ~50-100 分
- 3 世代: ~150-300 分

### 3.3 結果の確認

GA ループ完了後:
```bash
# 最新の実行ディレクトリ
cd runs/run_<timestamp>/

# ログファイルの確認
cat logfile.csv | head -20

# 最終結果の確認
tail -5 logfile.csv
```

出力例（logfile.csv）:
```
generation,best_raw_fitness,mean_raw_fitness,seconds,note
0,1.234,1.100,312.5,
1,1.456,1.200,425.0,
2,1.678,1.300,380.0,
```

---

## Phase 4: パラメータ調整（オプション）

GA が十分に収束していない場合、以下を調整:

### 4.1 設計変数の範囲

**config.comsol.ubuntu.json** の `variables` セクション:

```json
{
  "name": "ew",
  "min": 3.0,    // 電極幅の下限
  "max": 20.0,   // 電極幅の上限
  "unit": "um"
}
```

**制約**:
- `ew`: 3-20 µm（メッシュ解像度、流路幅40µm）
- `eg`: 2-15 µm（流路幅、電極間隔最小化のため下限を緩める場合は 1 µm）
- `el`: 15-38 µm（流路高さ40µm の制約）

### 4.2 GA パラメータの調整

```json
{
  "population_size": 20,     // デフォルト 10。大きいほど多様性向上
  "generations": 5,          // デフォルト 3。多いほど収束時間増加
  "elite": 2,                // デフォルト 2。上位何個体を次世代に保持
  "crossover_rate": 0.9,     // デフォルト 0.9
  "mutation_rate": null,     // null なら自動計算（1/変数数）
  "sbx_eta": 15.0,          // SBX 交叉の集中度。大きいほど親に近い
  "polynomial_mutation_eta": 20.0  // 突然変異の集中度
}
```

### 4.3 実行例

```bash
# より多くの世代を試す
nano config.comsol.ubuntu.json
# "generations": 5 に変更

python3 ga_comsol.py config.comsol.ubuntu.json
```

---

## トラブルシューティング

### 症状 1: COMSOL コマンドが見つからない

```
FileNotFoundError: COMSOL実行ファイル 'comsol' が PATH 上に見つかりません
```

**解決**:
```bash
# COMSOL のインストールパスを確認
find /usr/local -name comsol -type f 2>/dev/null
# または
find /opt -name comsol -type f 2>/dev/null

# config.comsol.ubuntu.json で executable を絶対パスに変更
nano config.comsol.ubuntu.json
# "executable": "/usr/local/comsol64/multiphysics/bin/comsol"
```

### 症状 2: fitness.csv が生成されない

```
FileNotFoundError: fitness ファイルが見つかりません: .../fitness.csv
```

**解決**:
1. COMSOL GUI でモデルを開く
2. **Study > Compute** に「Export」ステップがあるか確認
3. Export の「File name」が `fitness.csv`（相対パス）になっているか確認
4. COMSOL GUI で手動実行して fitness.csv が生成されるか確認

### 症状 3: fitness.csv は生成されるが値がおかしい

```
ValueError: 列 -1 に数値がありません
```

**解決**:
1. 出力された fitness.csv の内容を確認
   ```bash
   cat runs/run_*/jobs/eval_*/fitness.csv
   ```
2. 期待値: 単一の数値（例: `1.23456789`）
3. 異なる場合は、Global Evaluation の式（`COMSOL_SMIN_SETUP.md`）を見直す

### 症状 4: COMSOL が timeout する

```
COMSOL Batch timeout (7200 sec)
```

**解決**:
- Parametric Sweep のサイズが大きすぎないか確認
- 一度の Compute が実際に何分かかるか測定
- config.comsol.ubuntu.json の `comsol.timeout_sec` を増やす
  ```json
  "timeout_sec": 14400  // 2時間から4時間に延長
  ```

### 症状 5: GA の収束が遅い

**解決**:
1. 設計変数の範囲を狭める（事前知識がある場合）
2. `population_size` を増やす（例: 10 → 20）
3. `generations` を増やす（例: 3 → 5）
4. `sbx_eta` を小さくする（例: 15.0 → 10.0）— より大きな変化を許可

---

## 実運用チェックリスト

- [ ] COMSOL CLI が PATH で実行可能
- [ ] `config.comsol.ubuntu.json` が実環境パスに設定されている
- [ ] `ga_electrode_base.mph` に Global Evaluation（Smin）が定義されている
- [ ] `ga_electrode_base.mph` に Export（fitness.csv）ステップが定義されている
- [ ] COMSOL GUI で手動実行して fitness.csv が生成される
- [ ] `validate_comsol_setup.py` がすべてのチェックに合格している
- [ ] 単体評価テスト（`-generate 1`）で fitness.csv が読み込める
- [ ] GA ループで目的値が改善傾向を示している

---

## 参考資料

- **UBUNTU_実行手順.md**: 基本的な端末操作とセットアップ手順
- **COMSOL_SMIN_SETUP.md**: Global Evaluation 式の詳細と Export 設定
- **ga_comsol.py**: GA スクリプト（`-h` オプションでヘルプ表示）

```bash
python3 ga_comsol.py -h
```

---

## 質問・バグ報告

問題が生じた場合は、以下を記録して報告:
1. エラーメッセージ全文
2. `config.comsol.ubuntu.json` の内容（パスのみ編集）
3. 失敗した実行コマンド
4. `runs/run_*/jobs/eval_*/` の以下のログ:
   - `command.txt`
   - `stdout.log`
   - `stderr.log`
   - `fitness.csv`（存在する場合）

---

**作成日**: 2026-08-19
**バージョン**: 1.0
