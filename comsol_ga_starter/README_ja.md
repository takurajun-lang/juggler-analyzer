# 単一細胞EIS電極の GA–COMSOL 自動設計（スターターキット）

COMSOL の FEM 解析を評価器として、Python 側の遺伝的アルゴリズム（GA）で
電極形状を自動探索するための最小構成である。

現段階の対象は、対向する**長方形電極の 3 変数（`ew`, `eg`, `el`）の寸法最適化**であり、
代理モデル・並列化・NSGA-II は含めていない。まず「代理モデルなしで閉ループを
確実に動かすこと」を目的としている。

---

## 1. ファイル構成

| ファイル | 内容 |
|---|---|
| `ga_comsol.py` | GA本体。標準ライブラリのみ。模擬評価と COMSOL Batch 実行に対応 |
| `config.mock.json` | COMSOL なしで GA 動作を確認する設定 |
| `config.comsol.ubuntu.example.json` | Ubuntu 用設定例（`executable: comsol`、`launcher_args: ["batch"]`） |
| `config.comsol.example.json` | Windows 用設定例（`comsolbatch.exe` を直接呼ぶ） |
| `UBUNTU_実行手順.md` | 実験室 Ubuntu PC での段階的な実行手順 |

外部ライブラリのインストールは不要である。Python 3.9 以降で動く。

```bash
python3 ga_comsol.py config.mock.json
```

---

## 2. 閉ループの構成

```text
Python GA
  → 個体 (ew, eg, el) を生成
  → COMSOL Batch を起動（-pname / -plist でパラメータだけを上書き）
  → Geometry再構築・メッシュ・FEM周波数走査
  → fitness.csv を出力
  → Python が適応度を読み、選択・交叉・突然変異
  → 次世代
```

Python が上書きするのは COMSOL の Global Parameters（`ew,eg,el`）だけである。
したがって細胞・溶液・材料物性・印加条件・周波数走査は、MPH ファイル内の
固定設定がそのまま保たれる。

Ubuntu での実際の呼び出しは次の形になる（`--dry-run` で確認できる）。

```bash
comsol batch \
  -inputfile ga_electrode_base.mph \
  -pname ew,eg,el \
  -plist '10[um],5[um],30[um]' \
  -study std1 \
  -outputdir <個体ごとのジョブフォルダ> \
  -np 1 \
  -nosave
```

参考:
- COMSOL Linux CLI: <https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_running.38.32.html>
- COMSOL Knowledge Base 1250: <https://www.comsol.com/support/knowledgebase/1250>

### Java / Jinja2 案との関係

MPH を Java として保存し、Jinja2 で数値を書き換えて CLI を回す方法も有効であり、
電極本数や Polygon 頂点数など**モデル構造自体**を個体ごとに変える場合には必要になる。
ただし今回の初期対象は連続 3 パラメータだけなので、毎個体 Java を生成・再コンパイル
する必要はない。固定 MPH に `-pname/-plist` で数値を渡す方式のほうが単純で、
失敗原因を切り分けやすい。矢印形状や自由 Polygon へ拡張し、Global Parameters だけでは
表現できなくなった時点で、固定 Java ラッパーまたは Jinja2 テンプレートを追加する。

---

## 3. 設計変数と対称条件

左右の電極は、電極間中央を通る直線 `x=0` に関する線対称（鏡映対称）とする。
左電極上の点 `(x, y)` に対する右電極の点は `(-x, y)` である。

| 変数 | 意味 | 初期の例示範囲 |
|---|---|---:|
| `ew` | 電極幅 | 3–20 µm |
| `eg` | 電極間隔 | 2–15 µm |
| `el` | 電極長さ | 15–60 µm |

座標原点を電極間中央に置き、Rectangle の基準点を左下とする場合:

| 電極 | x位置 | y位置 | x方向サイズ | y方向サイズ |
|---|---:|---:|---:|---:|
| 左 | `-eg/2-ew` | `-el/2` | `ew` | `el` |
| 右 | `eg/2` | `-el/2` | `ew` | `el` |

**上記の範囲はコードの動作確認用の初期値である。**
実際には製造制約、細胞径、計算領域、メッシュ品質を見て決め直す必要がある。

---

## 4. 適応度

初期実装は単一目的であり、`Smin`（位置ずれを考慮した最小ピーク感度）の最大化とする。

$$\max_{\mathbf{x}} g(\mathbf{x}), \qquad g = S_{\min}$$

細胞が存在するのに信号が小さく検出できない事態を最も避けたいため、`Smin` を最重要指標とする。
COMSOL が `fitness.csv` にスカラーを 1 つ書き出し、Python がそれを適応度として受け取る。

後段の拡張は 2 方向ある。

1. 重み付き単一目的 `g = a·Smax + b·Smin − c·Rshift − d·Svar`
   ただし単位・スケールを正規化しないと重みの意味が崩れるため、初期段階での採用は推奨しない。
2. 多目的最適化（`Smin` 最大化 / `Svar` 最小化 / `Rshift` 最小化）を NSGA-II で扱う。

**実 FEM の結果が出るまで、重みや GA ハイパーパラメータの最適値を断定しないこと。**

---

## 5. GA の設計

| 要素 | 現在の設定 | 理由 |
|---|---|---|
| 初期集団 | ランダム10個体 | 最小限の FEM 回数で接続確認するため |
| 選択 | バイナリトーナメント | 2個体を比較し良い方を親にする。適応度の絶対値・符号に依存しにくい |
| 交叉 | SBX | 連続値なので親の近傍に連続値の子を作りやすい |
| 突然変異 | 多項式突然変異 | 連続値探索で局所停滞を避ける |
| エリート保存 | 2個体 | その世代の良い設計を失わないため |

現在の値は `sbx_eta=15`、`polynomial_mutation_eta=20`。これらは出発値であり確定値ではない。

SBX を最初に選んだ理由は、設計変数が連続値であり、FEM が高コストなので良い親の周辺を
効率的に細かく探索したいためである。また将来の実数値 NSGA-II にも同じ SBX を使える。

同じコードで次の比較案も使える。

```bash
python3 ga_comsol.py config.mock.json --method blx_ga      # BLX-α交叉 + ガウス突然変異
python3 ga_comsol.py config.mock.json --method uniform_ga  # 一様交叉 + ガウス突然変異
```

### 評価回数の見積り

個体数 `N`、エリート `E`、追加世代 `G` のとき、重複がなければ

$$N + (N - E) \times G$$

個体数10・エリート2・3世代なら `10 + 8×3 = 34` 回の FEM 計算となる。

---

## 6. COMSOL 側で必要な準備

1. 元のモデルを直接編集せず、`ga_electrode_base.mph` として複製する。
2. `Global Definitions > Parameters` に `ew`, `eg`, `el` を追加する。
3. **電極 Geometry だけ**を上記パラメータ式に置き換える。
4. 細胞、溶液、材料、印加、周波数走査、ソルバーは固定する。
5. Terminal、Ground、材料割り当ては、境界番号の直接指定を避け**名前付き Selection** を使う。
   Geometry 変更で境界番号が変わるためである。
6. `Results > Derived Values` または Evaluation Group で適応度を定義する。
7. 計算後に**相対パス** `fitness.csv` へ結果を書き出すよう設定する。
   （相対パスにしておくと `-outputdir` で指定した個体ごとのフォルダに出る）

Ubuntu 上では、新規の Application Builder Method に依存しない構成を推奨する。
Study の `Job Configurations` に、計算後の `Evaluate Derived Values` と
必要なら `Export to File` を追加し、`-study std1` で実行する。

Job Configuration を CLI から実行しやすくする手順:

- `Show More Options` で `Solver and Job Configurations` を有効化する。
- `dummy=1` の1点 Parametric Sweep を追加する。
- Geometry パラメータを扱うため `Use parametric solver` を **Off** にする。
- `Show Default Solver` を実行する。
- Job Configurations 下に `Evaluate Derived Values`、必要なら `Export to File` を追加する。

---

## 7. 設定ファイルの読み方

```jsonc
{
  "mode": "comsol",              // mock | comsol
  "objective": "maximize",       // Smin なので maximize
  "variables": [
    { "name": "ew", "min": 3.0, "max": 20.0, "unit": "um" }
  ],
  "comsol": {
    "executable": "comsol",      // which comsol が通らなければ絶対パス
    "launcher_args": ["batch"],  // Windows の comsolbatch.exe では []
    "inputfile": "/path/ga_electrode_base.mph",
    "study": "std1",
    "extra_args": ["-nosave"],
    "np": 1,
    "timeout_sec": 7200,
    "fitness_file": "fitness.csv",
    "fitness_parser": { "mode": "last_numeric", "column": -1 }
  },
  "ga":  { "method": "sbx_ga", "population_size": 10, "generations": 0, "elite": 2 },
  "run": { "output_root": "runs", "failure_fitness": -1e30 }
}
```

`variables[].unit` を書くと `-plist` に `12.34[um]` の形で単位付きで渡される。
単位を空文字にすると数値だけが渡る。

### `fitness_parser.mode`

| mode | 取り出す値 |
|---|---|
| `last_numeric` | 数値を含む**最後の行**の指定列（既定は最終列） |
| `column_last` | 同上（意図を明示したい場合） |
| `column_max` | 指定列の最大値 |
| `column_min` | 指定列の最小値 |

`column` は 0 始まりで、`-1` は最終列を指す。
`%` および `#` で始まる COMSOL のヘッダ行は自動的に読み飛ばす。

---

## 8. 出力の構成

1回の実行ごとに `runs/run_<日時>/` が作られる。

```text
runs/run_20260818_060504/
├── config_used.json     使用した設定のコピー
├── ga.log               実行ログ
├── evaluations.csv      全評価の一覧（パラメータ・適応度・状態・所要秒数）
├── history.csv          世代ごとの最良値・平均値・失敗数・最良個体
├── best.json            最終的な最良設計
└── jobs/
    ├── eval_00001/
    │   ├── command.txt   実行した COMSOL コマンド行
    │   ├── job.log       この個体の処理ログ
    │   ├── stdout.log    COMSOL の標準出力
    │   ├── stderr.log    COMSOL の標準エラー
    │   └── fitness.csv   COMSOL が書き出した結果
    └── eval_00002/ ...
```

- 同じパラメータの重複評価は**キャッシュ**され、COMSOL は再起動しない。
- COMSOL が失敗した個体には既定で `-1e30`（最大化時）を与え、**GA 全体は止めない**。
  失敗は `evaluations.csv` の `status=FAILED` と `note` 列、および該当ジョブの
  `stderr.log` で追跡できる。

---

## 9. コマンドラインオプション

```bash
python3 ga_comsol.py <config.json> [options]

  --generations N   設定の世代数を上書き
  --population N    設定の個体数を上書き
  --method M        sbx_ga | blx_ga | uniform_ga
  --seed N          乱数シードを上書き
  --dry-run         mode=comsol のとき、実行せずにコマンド行だけ表示
```

---

## 10. 未決定事項（研究上の判断が要るもの）

- 実際の製造可能範囲を踏まえた `ew, eg, el` の上下限。
- `Smin` を算出する細胞位置セットと、その位置ごとの FEM 計算の構成。
- `fitness.csv` に保存する具体的な COMSOL 式・列構造。
- `Smax`、`Svar`、`Rshift` をいつ追加するか。
- 単一目的のまま進めるか、正規化した重み付き適応度へ進むか、NSGA-II へ進むか。
- 長方形電極の結果を基準として、矢印形状や Polygon 自由形状へいつ拡張するか。
- 代理モデル（Gaussian Process / Kriging、ニューラルネットワーク等）の導入時期。
