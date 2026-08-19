# COMSOL 設定: Smin 抽出と fitness.csv 出力

## 概要

18点のParametric Sweep（cell_on={0,1}、cellx=9位置）が完了した後、以下の手順で Smin（最小感度）を抽出し、fitness.csv として出力する必要があります。

## Step 1: Global Evaluation の追加（Smin計算式）

COMSOL GUI での操作:

1. **Definitions > Derived Values > Global Evaluation** を追加
2. **名前**: `Smin` と設定
3. **Expression**（計算式）に以下を入力:

```
min(
  withsol(
    'sol1',
    d(normF,x,x)+d(normF,y,y)+d(normF,z,z),
    cell_on,1,
    cellx,range(-(eg/2+ew/2),(eg/2+ew/2),9)
  )
  /
  withsol(
    'sol1',
    d(normF,x,x)+d(normF,y,y)+d(normF,z,z),
    cell_on,0,
    cellx,0
  )
)
```

### 計算式の説明

- **分子**: `withsol(..., cell_on,1, cellx,range(...,9))`
  - Parametric Sweep の 9 位置すべてで cell_on=1 の場合のインピーダンスを取得
  - `normF` はインピーダンスの周波数応答（COMSOL内で既に計算済み）
  - 空間微分により impedance magnitude を抽出

- **分母**: `withsol(..., cell_on,0, cellx,0)`
  - ベースライン（cell_on=0 のとき）のインピーダンス
  - cellx=0（電極中央）での値を参照

- **相対感度**: 分子 / 分母
  - cell_on=1 での感度を cell_on=0 での感度で正規化

- **min(...)**: 9 位置での相対感度の最小値 = Smin

### 代替案（より単純な定義）

もし上記の `normF` 参照が環境に合わない場合:

```
min(
  withsol('sol1', Z_mag, cell_on,1, cellx,range(-(eg/2+ew/2),(eg/2+ew/2),9))
  /
  withsol('sol1', Z_mag, cell_on,0, cellx,0)
)
```

ここで `Z_mag` は COMSOL モデル内で定義済みのインピーダンス magnitude 変数です。

## Step 2: Job Configuration の設定

COMSOL GUI での操作:

1. **Study（std1） > Compute** を展開
2. **Evaluate Derived Values** ステップを確認（なければ追加）
3. **Export** ステップを確認（なければ追加）

### Export ステップの詳細設定

1. **Study > Compute > Export** を選択（または作成）
2. **Data** タブ:
   - Quantity to Export: `Smin` を選択
   - Expression Mode: ON
   - File name: `fitness.csv`（相対パス）
   - Format: CSV

3. **Spreadsheet** タブ:
   - Include table header: OFF（ga_comsol.py が 'last_numeric' モードで期待する形式に合わせる）
   - Delimiter: Comma
   - Precision: 12（デフォルト）

## Step 3: 検証用の手動実行

COMSOL GUI で以下を実行:

```
Study > Compute > Compute All
```

出力ファイル `fitness.csv` が生成されることを確認。内容は以下のような形式:

```
1.23456789
```

または（コメント付き）:

```
% Smin value from parametric sweep
1.23456789
```

## Step 4: CLI 実行テスト

Ubuntu 端末で以下を実行（ga_comsol.py に設定ファイルを指定）:

```bash
cd /path/to/comsol_ga_starter
python3 ga_comsol.py config.comsol.ubuntu.json -generate 1 -mock-evaluate False
```

### 期待される動作

1. `runs/` 配下にジョブディレクトリが生成される
2. COMSOL batch で ga_electrode_base.mph が実行
3. 計算終了後、fitness.csv が ジョブディレクトリに出力
4. ga_comsol.py が fitness.csv から Smin を読み込む
5. GA の評価値として使用される

## Step 5: トラブルシューティング

### fitness.csv が出力されない場合

- COMSOL GUI で Export ステップが Enabled になっているか確認
- File name が相対パス（fitness.csv）になっているか確認
- Quantity が Smin に設定されているか確認

### Smin が NaN や inf になる場合

- withsol() の parameter name（cell_on, cellx）が実際の Global Parameter 名と一致しているか確認
- Parametric Sweep の設定が正しいか確認（cell_on={0,1}、cellx=9点）
- ベースライン（cell_on=0）での計算が正常に完了しているか確認

### CLI 実行でエラーが出る場合

- `comsol batch` コマンドが PATH に含まれているか確認
- config.comsol.ubuntu.json の `inputfile` パスが正しいか確認
- `runs/` ディレクトリへの書き込み権限があるか確認

## ファイル参照

- **COMSOL モデル**: `ga_electrode_base.mph`
- **GA スクリプト**: `ga_comsol.py`
- **設定ファイル**: `config.comsol.ubuntu.json`
- **ドキュメント**: `UBUNTU_実行手順.md`

---

## 次のステップ

Global Evaluation と Export ステップの設定が完了したら、以下を実施:

1. COMSOL GUI で動作確認（手動実行）
2. 設定を .mph ファイルに保存
3. ga_comsol.py で CLI テスト実施
4. 実験室 PC で GA ループを開始
