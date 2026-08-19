#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ga_comsol.py
単一細胞EIS電極の GA-COMSOL 自動設計 : GA本体

- 標準ライブラリのみを使用する（numpy等は不要）。
- 実数値GA。設計変数は連続値（例: ew, eg, el）。
- 評価器は次の2モードを持つ。
    mock   : COMSOLを使わない模擬評価。配線とGA挙動の確認用。
    comsol : COMSOL Batch を個体ごとに起動し fitness.csv を読む。
- 1個体の評価は runs/run_<日時>/jobs/eval_XXXXX/ に完全に分離して保存する。

使い方:
    python3 ga_comsol.py config.mock.json
    python3 ga_comsol.py config.comsol.ubuntu.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime

FAILURE_TAG = "FAILED"


# ---------------------------------------------------------------------------
# 設定の読み込みと既定値
# ---------------------------------------------------------------------------

DEFAULT_GA = {
    "method": "sbx_ga",              # sbx_ga | blx_ga | uniform_ga
    "population_size": 10,
    "generations": 3,
    "elite": 2,
    "tournament_size": 2,
    "crossover_rate": 0.9,
    "mutation_rate": None,           # None なら 1/変数数
    "sbx_eta": 15.0,
    "polynomial_mutation_eta": 20.0,
    "blx_alpha": 0.5,
    "gauss_sigma_ratio": 0.10,       # 変数レンジに対する標準偏差の比
    "seed": 12345,
}

DEFAULT_RUN = {
    "output_root": "runs",
    "failure_fitness": -1e30,        # objective=minimize のときは符号を自動反転
    "keep_job_dirs": True,
    "round_digits": 6,               # キャッシュキーの丸め桁数
}

DEFAULT_PARSER = {
    "mode": "last_numeric",          # last_numeric | column_max | column_min | column_last
    "column": -1,                    # 0始まり。-1 は最終列
    "delimiter": ",",
    "comment_prefixes": ["%", "#"],
}


def _merge(default: dict, given: dict | None) -> dict:
    out = dict(default)
    if given:
        for k, v in given.items():
            out[k] = v
    return out


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.setdefault("mode", "mock")
    cfg.setdefault("objective", "maximize")
    if cfg["objective"] not in ("maximize", "minimize"):
        raise ValueError("objective は maximize か minimize です: %r" % cfg["objective"])

    if not cfg.get("variables"):
        raise ValueError("variables が空です。設計変数を1つ以上定義してください。")
    for v in cfg["variables"]:
        for key in ("name", "min", "max"):
            if key not in v:
                raise ValueError("variables の要素に %s がありません: %r" % (key, v))
        if float(v["min"]) >= float(v["max"]):
            raise ValueError("変数 %s の min >= max です。" % v["name"])
        v.setdefault("unit", "")

    cfg["ga"] = _merge(DEFAULT_GA, cfg.get("ga"))
    cfg["run"] = _merge(DEFAULT_RUN, cfg.get("run"))

    if cfg["ga"]["method"] not in ("sbx_ga", "blx_ga", "uniform_ga"):
        raise ValueError("ga.method は sbx_ga / blx_ga / uniform_ga のいずれかです。")
    if cfg["ga"]["elite"] >= cfg["ga"]["population_size"]:
        raise ValueError("ga.elite は population_size より小さくしてください。")

    if cfg["mode"] == "comsol":
        c = cfg.get("comsol")
        if not c:
            raise ValueError("mode=comsol では comsol セクションが必要です。")
        c.setdefault("executable", "comsol")
        c.setdefault("launcher_args", ["batch"])
        c.setdefault("study", "std1")
        c.setdefault("extra_args", ["-nosave"])
        c.setdefault("np", 1)
        c.setdefault("timeout_sec", 3600)
        c.setdefault("fitness_file", "fitness.csv")
        c.setdefault("copy_inputfile_to_job", False)
        c["fitness_parser"] = _merge(DEFAULT_PARSER, c.get("fitness_parser"))
        if not c.get("inputfile"):
            raise ValueError("comsol.inputfile （.mph のパス）が必要です。")

    return cfg


# ---------------------------------------------------------------------------
# GA 演算子（すべて実数値ベクトルに対する操作）
# ---------------------------------------------------------------------------

def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def random_individual(bounds, rng: random.Random):
    return [rng.uniform(lo, hi) for lo, hi in bounds]


def tournament_select(pop, fits, k: int, rng: random.Random):
    """バイナリ（既定 k=2）トーナメント選択。
    適応度は「大きいほど良い」に正規化済みの内部値を使う。
    絶対値や符号に依存せず、比較だけで決まる。"""
    best_idx = rng.randrange(len(pop))
    for _ in range(k - 1):
        i = rng.randrange(len(pop))
        if fits[i] > fits[best_idx]:
            best_idx = i
    return list(pop[best_idx])


def sbx_crossover(p1, p2, bounds, eta: float, rng: random.Random):
    """SBX (Simulated Binary Crossover)。実数値GAの標準的な交叉。
    eta が大きいほど親の近傍に子ができる。"""
    c1, c2 = list(p1), list(p2)
    for i, (lo, hi) in enumerate(bounds):
        if rng.random() > 0.5:
            continue
        x1, x2 = p1[i], p2[i]
        if abs(x1 - x2) < 1e-14:
            continue
        if x1 > x2:
            x1, x2 = x2, x1

        u = rng.random()

        beta = 1.0 + (2.0 * (x1 - lo) / (x2 - x1))
        alpha = 2.0 - beta ** -(eta + 1.0)
        if u <= 1.0 / alpha:
            betaq = (u * alpha) ** (1.0 / (eta + 1.0))
        else:
            betaq = (1.0 / (2.0 - u * alpha)) ** (1.0 / (eta + 1.0))
        y1 = 0.5 * ((x1 + x2) - betaq * (x2 - x1))

        beta = 1.0 + (2.0 * (hi - x2) / (x2 - x1))
        alpha = 2.0 - beta ** -(eta + 1.0)
        if u <= 1.0 / alpha:
            betaq = (u * alpha) ** (1.0 / (eta + 1.0))
        else:
            betaq = (1.0 / (2.0 - u * alpha)) ** (1.0 / (eta + 1.0))
        y2 = 0.5 * ((x1 + x2) + betaq * (x2 - x1))

        y1 = clamp(y1, lo, hi)
        y2 = clamp(y2, lo, hi)
        if rng.random() < 0.5:
            y1, y2 = y2, y1
        c1[i], c2[i] = y1, y2
    return c1, c2


def blx_alpha_crossover(p1, p2, bounds, alpha: float, rng: random.Random):
    """BLX-α 交叉。親を含む区間を α 倍だけ外側へ広げてサンプリングする。"""
    c1, c2 = [], []
    for i, (lo, hi) in enumerate(bounds):
        x1, x2 = p1[i], p2[i]
        dmin, dmax = min(x1, x2), max(x1, x2)
        d = dmax - dmin
        left, right = dmin - alpha * d, dmax + alpha * d
        c1.append(clamp(rng.uniform(left, right), lo, hi))
        c2.append(clamp(rng.uniform(left, right), lo, hi))
    return c1, c2


def uniform_crossover(p1, p2, bounds, rng: random.Random):
    """一様交叉。遺伝子ごとに 50% で親を入れ替える。"""
    c1, c2 = list(p1), list(p2)
    for i in range(len(bounds)):
        if rng.random() < 0.5:
            c1[i], c2[i] = c2[i], c1[i]
    return c1, c2


def polynomial_mutation(ind, bounds, eta: float, rate: float, rng: random.Random):
    """多項式突然変異。連続値探索での局所停滞を避ける。"""
    y = list(ind)
    for i, (lo, hi) in enumerate(bounds):
        if rng.random() >= rate:
            continue
        x = y[i]
        span = hi - lo
        if span <= 0:
            continue
        d1 = (x - lo) / span
        d2 = (hi - x) / span
        u = rng.random()
        mut_pow = 1.0 / (eta + 1.0)
        if u <= 0.5:
            xy = 1.0 - d1
            val = 2.0 * u + (1.0 - 2.0 * u) * (xy ** (eta + 1.0))
            dq = val ** mut_pow - 1.0
        else:
            xy = 1.0 - d2
            val = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * (xy ** (eta + 1.0))
            dq = 1.0 - val ** mut_pow
        y[i] = clamp(x + dq * span, lo, hi)
    return y


def gaussian_mutation(ind, bounds, sigma_ratio: float, rate: float, rng: random.Random):
    """ガウス突然変異。blx_ga / uniform_ga と組み合わせて使う。"""
    y = list(ind)
    for i, (lo, hi) in enumerate(bounds):
        if rng.random() >= rate:
            continue
        y[i] = clamp(y[i] + rng.gauss(0.0, sigma_ratio * (hi - lo)), lo, hi)
    return y


def make_offspring(p1, p2, bounds, ga: dict, rng: random.Random):
    """設定された方式に従って、2親から2子を作る。"""
    method = ga["method"]
    n = len(bounds)
    mut_rate = ga["mutation_rate"] if ga["mutation_rate"] is not None else 1.0 / n

    if rng.random() < ga["crossover_rate"]:
        if method == "sbx_ga":
            c1, c2 = sbx_crossover(p1, p2, bounds, ga["sbx_eta"], rng)
        elif method == "blx_ga":
            c1, c2 = blx_alpha_crossover(p1, p2, bounds, ga["blx_alpha"], rng)
        else:
            c1, c2 = uniform_crossover(p1, p2, bounds, rng)
    else:
        c1, c2 = list(p1), list(p2)

    if method == "sbx_ga":
        c1 = polynomial_mutation(c1, bounds, ga["polynomial_mutation_eta"], mut_rate, rng)
        c2 = polynomial_mutation(c2, bounds, ga["polynomial_mutation_eta"], mut_rate, rng)
    else:
        c1 = gaussian_mutation(c1, bounds, ga["gauss_sigma_ratio"], mut_rate, rng)
        c2 = gaussian_mutation(c2, bounds, ga["gauss_sigma_ratio"], mut_rate, rng)
    return c1, c2


# ---------------------------------------------------------------------------
# fitness.csv の解釈
# ---------------------------------------------------------------------------

def _to_float(token: str):
    t = token.strip().strip('"').strip("'")
    if not t:
        return None
    t = t.replace("i", "j") if t.endswith("i") else t   # COMSOLの複素表記への保険
    try:
        return float(t)
    except ValueError:
        try:
            return float(complex(t).real)
        except (ValueError, TypeError):
            return None


def _parse_complex_token(token: str):
    """COMSOLが書き出す複素数表記（例: 1.23e-5+4.56e-6i）をPythonのcomplexに変換する。"""
    t = token.strip().strip('"').strip("'")
    if not t:
        return None
    if t and t[-1] in ("i", "I"):
        t = t[:-1] + "j"
    try:
        return complex(t)
    except ValueError:
        try:
            return complex(float(t), 0.0)
        except ValueError:
            return None


def read_eis_sweep_csv(path: str, parser: dict) -> float:
    """cell_on, cellx, freq, Z(複素数) の生データ行から Smin を計算する。

    定義:
      S(f)  = |Z_cell(f) - Z_baseline(f)| / |Z_baseline(f)|
      peak  = S(f) の周波数方向の最大値（cellxごと）
      Smin  = peak の cellx方向の最小値（cell_on=1 の行のみが対象）

    baseline（Z_baseline）は、同じ cellx・同じ freq の cell_on=0 行から求める
    （cell_on=0 でも cellx ごとにメッシュ形状が異なるため、周波数だけでなく
    cellx も揃えて比較することで、メッシュ差に起因する数値誤差を打ち消す）。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError("EISスイープファイルが見つかりません: %s" % path)

    col_cell_on = int(parser.get("col_cell_on", 0))
    col_cellx = int(parser.get("col_cellx", 1))
    col_freq = int(parser.get("col_freq", 2))
    col_z = int(parser.get("col_z", 3))
    delim = parser.get("delimiter", ",")
    prefixes = tuple(parser.get("comment_prefixes", ["%", "#"]))
    freq_round = int(parser.get("freq_round_digits", 6))
    cellx_round = int(parser.get("cellx_round_digits", 12))

    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(prefixes):
                continue
            cells = line.split(delim)
            try:
                cell_on = float(cells[col_cell_on])
                cellx = float(cells[col_cellx])
                freq = float(cells[col_freq])
            except (IndexError, ValueError):
                continue
            z = _parse_complex_token(cells[col_z]) if len(cells) > col_z else None
            if z is None:
                continue
            rows.append((cell_on, cellx, freq, z))

    if not rows:
        raise ValueError("EISスイープに数値データがありません: %s" % path)

    baseline = {}
    for cell_on, cellx, freq, z in rows:
        if round(cell_on) == 0:
            key = (round(cellx, cellx_round), round(freq, freq_round))
            baseline[key] = z

    if not baseline:
        raise ValueError("cell_on=0（ベースライン）の行が見つかりません: %s" % path)

    peak_by_cellx = {}
    for cell_on, cellx, freq, z in rows:
        if round(cell_on) != 1:
            continue
        key = (round(cellx, cellx_round), round(freq, freq_round))
        zbase = baseline.get(key)
        if zbase is None or abs(zbase) == 0:
            continue
        s = abs(z - zbase) / abs(zbase)
        cx_key = round(cellx, cellx_round)
        if cx_key not in peak_by_cellx or s > peak_by_cellx[cx_key]:
            peak_by_cellx[cx_key] = s

    if not peak_by_cellx:
        raise ValueError("cell_on=1 の行が見つかりません: %s" % path)

    return min(peak_by_cellx.values())


def read_fitness_csv(path: str, parser: dict) -> float:
    """COMSOL が書き出した CSV からスカラーの目的値を1つ取り出す。

    mode:
      last_numeric   : 数値を含む最後の行の指定列
      column_max     : 指定列の最大値
      column_min     : 指定列の最小値
      column_last    : 指定列の最後の値（last_numeric と同義だが意図を明示）
      eis_smin_sweep : cell_on, cellx, freq, Z(複素数) の生データ行から Smin を計算
    """
    if not os.path.isfile(path):
        raise FileNotFoundError("fitness ファイルが見つかりません: %s" % path)

    if parser.get("mode") == "eis_smin_sweep":
        return read_eis_sweep_csv(path, parser)

    prefixes = tuple(parser.get("comment_prefixes", ["%", "#"]))
    delim = parser.get("delimiter", ",")
    col = int(parser.get("column", -1))

    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(prefixes):
                continue
            cells = [c for c in line.split(delim)]
            vals = [_to_float(c) for c in cells]
            if any(v is not None for v in vals):
                rows.append(vals)

    if not rows:
        raise ValueError("数値データ行が見つかりません: %s" % path)

    def pick(row):
        try:
            v = row[col]
        except IndexError:
            raise ValueError("列 %d が存在しません（列数 %d）: %s" % (col, len(row), path))
        if v is None:
            raise ValueError("列 %d が数値ではありません: %s" % (col, path))
        return v

    mode = parser.get("mode", "last_numeric")
    if mode in ("last_numeric", "column_last"):
        return pick(rows[-1])
    values = []
    for r in rows:
        try:
            values.append(pick(r))
        except ValueError:
            continue
    if not values:
        raise ValueError("列 %d に数値がありません: %s" % (col, path))
    if mode == "column_max":
        return max(values)
    if mode == "column_min":
        return min(values)
    raise ValueError("未知の fitness_parser.mode: %r" % mode)


# ---------------------------------------------------------------------------
# 評価器
# ---------------------------------------------------------------------------

class MockEvaluator:
    """COMSOLなしでGAの動作を確認するための模擬評価器。

    既知の最適点 (ew, eg, el) = (12, 4, 45) 近傍で最大となる滑らかな関数に、
    小さなリップルを重ねてある。実際の Smin ではないので、
    値の絶対量に意味はない。GAが最適点へ寄るかどうかだけを見る。
    """

    OPTIMUM = {"ew": 12.0, "eg": 4.0, "el": 45.0}

    def __init__(self, cfg):
        self.names = [v["name"] for v in cfg["variables"]]
        self.bounds = [(float(v["min"]), float(v["max"])) for v in cfg["variables"]]

    def known_optimum(self):
        out = []
        for name, (lo, hi) in zip(self.names, self.bounds):
            out.append(clamp(self.OPTIMUM.get(name, 0.5 * (lo + hi)), lo, hi))
        return out

    def evaluate(self, x, job_dir, log):
        opt = self.known_optimum()
        score = 1.0
        for xi, oi, (lo, hi) in zip(x, opt, self.bounds):
            d = (xi - oi) / (hi - lo)
            score *= math.exp(-8.0 * d * d)
        ripple = 1.0 + 0.03 * math.sin(3.0 * sum(x))
        value = 100.0 * score * ripple
        log("mock評価: x=%s -> %.6f" % (["%.4f" % v for v in x], value))
        os.makedirs(job_dir, exist_ok=True)
        with open(os.path.join(job_dir, "fitness.csv"), "w", encoding="utf-8") as f:
            f.write("%% mock evaluation\n")
            f.write("%s,fitness\n" % ",".join(self.names))
            f.write("%s,%.10g\n" % (",".join("%.10g" % v for v in x), value))
        return value


class ComsolEvaluator:
    """COMSOL Batch を1個体ごとに起動する評価器。

    Python が上書きするのは Global Definitions のパラメータだけである
    （既定では ew, eg, el）。細胞・溶液・材料物性・印加条件・周波数走査は
    MPH ファイル内の固定設定がそのまま使われる。
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.c = cfg["comsol"]
        self.names = [v["name"] for v in cfg["variables"]]
        self.units = [v.get("unit", "") for v in cfg["variables"]]
        self.inputfile = os.path.abspath(os.path.expanduser(self.c["inputfile"]))
        if not os.path.isfile(self.inputfile):
            raise FileNotFoundError(
                "MPHファイルが見つかりません: %s\n"
                "config の comsol.inputfile を実環境のパスに合わせてください。" % self.inputfile
            )

    def _plist(self, x):
        parts = []
        for value, unit in zip(x, self.units):
            parts.append("%.10g[%s]" % (value, unit) if unit else "%.10g" % value)
        return ",".join(parts)

    def build_command(self, x, job_dir):
        c = self.c
        exe = c["executable"]
        resolved = shutil.which(exe)
        if resolved is None and not os.path.isabs(exe):
            raise FileNotFoundError(
                "COMSOL実行ファイル %r が PATH 上に見つかりません。\n"
                "`which comsol` を確認するか、config の comsol.executable を絶対パスにしてください。" % exe
            )
        inputfile = self.inputfile
        if c.get("copy_inputfile_to_job"):
            local = os.path.join(job_dir, os.path.basename(self.inputfile))
            shutil.copy2(self.inputfile, local)
            inputfile = local

        cmd = [exe]
        cmd += list(c.get("launcher_args", []))
        cmd += ["-inputfile", inputfile]
        cmd += ["-pname", ",".join(self.names)]
        cmd += ["-plist", self._plist(x)]
        if c.get("study"):
            cmd += ["-study", c["study"]]
        cmd += ["-outputdir", job_dir]
        cmd += ["-np", str(c.get("np", 1))]
        cmd += list(c.get("extra_args", []))
        return cmd

    def evaluate(self, x, job_dir, log):
        os.makedirs(job_dir, exist_ok=True)
        cmd = self.build_command(x, job_dir)
        log("COMSOL 実行: %s" % " ".join(cmd))
        with open(os.path.join(job_dir, "command.txt"), "w", encoding="utf-8") as f:
            f.write(" ".join(cmd) + "\n")

        t0 = time.time()
        with open(os.path.join(job_dir, "stdout.log"), "w", encoding="utf-8") as so, \
             open(os.path.join(job_dir, "stderr.log"), "w", encoding="utf-8") as se:
            proc = subprocess.run(
                cmd, cwd=job_dir, stdout=so, stderr=se,
                timeout=self.c.get("timeout_sec", 3600), check=False,
            )
        elapsed = time.time() - t0
        log("COMSOL 終了: returncode=%d, %.1f 秒" % (proc.returncode, elapsed))
        if proc.returncode != 0:
            raise RuntimeError(
                "COMSOL が returncode=%d で終了しました。stderr.log を確認してください。" % proc.returncode
            )

        fpath = os.path.join(job_dir, self.c["fitness_file"])
        if not os.path.isfile(fpath):
            alt = os.path.join(os.path.dirname(self.inputfile), self.c["fitness_file"])
            if os.path.isfile(alt):
                log("警告: fitness をジョブ外 (%s) で検出。MPH側の出力パスを相対パスにしてください。" % alt)
                shutil.move(alt, fpath)
            else:
                raise FileNotFoundError(
                    "%s が出力されていません。COMSOL側の Export to File が\n"
                    "相対パス %r になっているか確認してください。" % (fpath, self.c["fitness_file"])
                )
        value = read_fitness_csv(fpath, self.c["fitness_parser"])
        log("fitness 読み取り: %.10g" % value)
        return value


# ---------------------------------------------------------------------------
# 実行管理（run ディレクトリ、キャッシュ、ログ）
# ---------------------------------------------------------------------------

class Runner:
    def __init__(self, cfg, config_path):
        self.cfg = cfg
        self.objective = cfg["objective"]
        self.sign = 1.0 if self.objective == "maximize" else -1.0
        self.names = [v["name"] for v in cfg["variables"]]
        self.bounds = [(float(v["min"]), float(v["max"])) for v in cfg["variables"]]
        self.round_digits = int(cfg["run"]["round_digits"])

        raw_fail = float(cfg["run"]["failure_fitness"])
        self.failure_raw = raw_fail if self.objective == "maximize" else abs(raw_fail)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = cfg["run"]["output_root"]
        self.run_dir = os.path.abspath(os.path.join(root, "run_%s" % stamp))
        self.jobs_dir = os.path.join(self.run_dir, "jobs")
        os.makedirs(self.jobs_dir, exist_ok=True)
        shutil.copy2(config_path, os.path.join(self.run_dir, "config_used.json"))

        self.log_path = os.path.join(self.run_dir, "ga.log")
        self.eval_csv = os.path.join(self.run_dir, "evaluations.csv")
        with open(self.eval_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["eval_id", "generation", "status"] + self.names
                       + ["raw_fitness", "internal_fitness", "seconds", "note"])

        self.cache = {}
        self.eval_count = 0
        self.cache_hits = 0
        self.comsol_calls = 0
        self.evaluator = MockEvaluator(cfg) if cfg["mode"] == "mock" else ComsolEvaluator(cfg)

    # -- ログ -------------------------------------------------------------
    def log(self, msg):
        line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # -- 評価 -------------------------------------------------------------
    def _key(self, x):
        return tuple(round(v, self.round_digits) for v in x)

    def evaluate(self, x, generation):
        key = self._key(x)
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key]

        self.eval_count += 1
        eval_id = self.eval_count
        job_dir = os.path.join(self.jobs_dir, "eval_%05d" % eval_id)
        os.makedirs(job_dir, exist_ok=True)

        def joblog(msg):
            with open(os.path.join(job_dir, "job.log"), "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))

        joblog("generation=%d" % generation)
        joblog("parameters: %s" % dict(zip(self.names, x)))

        t0 = time.time()
        status, note = "OK", ""
        try:
            if self.cfg["mode"] == "comsol":
                self.comsol_calls += 1
            raw = self.evaluator.evaluate(x, job_dir, joblog)
            if raw is None or not math.isfinite(raw):
                raise ValueError("適応度が有限の数値ではありません: %r" % raw)
        except Exception as exc:                     # noqa: BLE001
            status, note = FAILURE_TAG, str(exc).replace("\n", " ")[:400]
            raw = self.failure_raw
            joblog("失敗: %s" % note)
            self.log("  eval_%05d 失敗（GAは継続します）: %s" % (eval_id, note))

        internal = self.sign * raw
        elapsed = time.time() - t0

        with open(self.eval_csv, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [eval_id, generation, status] + ["%.10g" % v for v in x]
                + ["%.10g" % raw, "%.10g" % internal, "%.2f" % elapsed, note]
            )

        if not self.cfg["run"].get("keep_job_dirs", True) and status == "OK":
            shutil.rmtree(job_dir, ignore_errors=True)

        result = (raw, internal, status)
        self.cache[key] = result
        return result


# ---------------------------------------------------------------------------
# GA 本体
# ---------------------------------------------------------------------------

def run_ga(cfg, config_path):
    ga = cfg["ga"]
    rng = random.Random(ga["seed"])
    runner = Runner(cfg, config_path)
    bounds = runner.bounds
    names = runner.names

    runner.log("=" * 68)
    runner.log("GA-COMSOL 電極自動設計")
    runner.log("mode=%s  method=%s  objective=%s" % (cfg["mode"], ga["method"], cfg["objective"]))
    runner.log("変数: %s" % ", ".join(
        "%s[%s] %.4g..%.4g" % (v["name"], v.get("unit", "-"), float(v["min"]), float(v["max"]))
        for v in cfg["variables"]))
    runner.log("個体数=%d  世代数=%d  エリート=%d  seed=%s"
               % (ga["population_size"], ga["generations"], ga["elite"], ga["seed"]))
    budget = ga["population_size"] + (ga["population_size"] - ga["elite"]) * ga["generations"]
    runner.log("最大FEM評価回数（重複なしの場合）: %d" % budget)
    runner.log("出力先: %s" % runner.run_dir)
    runner.log("=" * 68)

    pop = [random_individual(bounds, rng) for _ in range(ga["population_size"])]
    raws, fits, stats = [], [], []
    runner.log("[世代 0] 初期集団を評価します（%d 個体）" % len(pop))
    for ind in pop:
        raw, internal, status = runner.evaluate(ind, 0)
        raws.append(raw); fits.append(internal); stats.append(status)

    history_path = os.path.join(runner.run_dir, "history.csv")
    with open(history_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["generation", "best_raw_fitness", "mean_raw_fitness",
                                "n_failed"] + names)

    def record(gen):
        order = sorted(range(len(pop)), key=lambda i: fits[i], reverse=True)
        b = order[0]
        ok = [raws[i] for i in range(len(pop)) if stats[i] == "OK"]
        mean = sum(ok) / len(ok) if ok else float("nan")
        nfail = sum(1 for s in stats if s != "OK")
        with open(history_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([gen, "%.10g" % raws[b], "%.10g" % mean, nfail]
                                   + ["%.10g" % v for v in pop[b]])
        runner.log("[世代 %d] 最良 %.6g  平均 %.6g  失敗 %d  最良個体 %s"
                   % (gen, raws[b], mean, nfail,
                      ", ".join("%s=%.4f" % (n, v) for n, v in zip(names, pop[b]))))
        return order

    record(0)

    for gen in range(1, ga["generations"] + 1):
        order = sorted(range(len(pop)), key=lambda i: fits[i], reverse=True)
        new_pop = [list(pop[i]) for i in order[:ga["elite"]]]
        new_raws = [raws[i] for i in order[:ga["elite"]]]
        new_fits = [fits[i] for i in order[:ga["elite"]]]
        new_stats = [stats[i] for i in order[:ga["elite"]]]

        runner.log("[世代 %d] 子個体を生成・評価します" % gen)
        while len(new_pop) < ga["population_size"]:
            p1 = tournament_select(pop, fits, ga["tournament_size"], rng)
            p2 = tournament_select(pop, fits, ga["tournament_size"], rng)
            c1, c2 = make_offspring(p1, p2, bounds, ga, rng)
            for child in (c1, c2):
                if len(new_pop) >= ga["population_size"]:
                    break
                raw, internal, status = runner.evaluate(child, gen)
                new_pop.append(child); new_raws.append(raw)
                new_fits.append(internal); new_stats.append(status)

        pop, raws, fits, stats = new_pop, new_raws, new_fits, new_stats
        record(gen)

    order = sorted(range(len(pop)), key=lambda i: fits[i], reverse=True)
    b = order[0]
    best = {
        "objective": cfg["objective"],
        "method": ga["method"],
        "best_fitness": raws[b],
        "best_parameters": {n: v for n, v in zip(names, pop[b])},
        "units": {v["name"]: v.get("unit", "") for v in cfg["variables"]},
        "total_evaluations": runner.eval_count,
        "comsol_calls": runner.comsol_calls,
        "cache_hits": runner.cache_hits,
        "run_dir": runner.run_dir,
    }
    with open(os.path.join(runner.run_dir, "best.json"), "w", encoding="utf-8") as f:
        json.dump(best, f, ensure_ascii=False, indent=2)

    runner.log("-" * 68)
    runner.log("完了。最良適応度 = %.10g" % raws[b])
    for n, v in zip(names, pop[b]):
        unit = best["units"].get(n, "")
        runner.log("  %s = %.6f %s" % (n, v, unit))
    runner.log("実評価回数 = %d（うち COMSOL 起動 %d 回）"
               % (runner.eval_count, runner.comsol_calls))
    runner.log("結果: %s" % os.path.join(runner.run_dir, "best.json"))
    runner.log("-" * 68)
    return best


def main(argv=None):
    ap = argparse.ArgumentParser(description="GA-COMSOL 電極自動設計")
    ap.add_argument("config", help="設定JSONのパス（例: config.mock.json）")
    ap.add_argument("--generations", type=int, default=None, help="設定の世代数を上書きする")
    ap.add_argument("--population", type=int, default=None, help="設定の個体数を上書きする")
    ap.add_argument("--method", default=None,
                    choices=["sbx_ga", "blx_ga", "uniform_ga"], help="GA方式を上書きする")
    ap.add_argument("--seed", type=int, default=None, help="乱数シードを上書きする")
    ap.add_argument("--dry-run", action="store_true",
                    help="mode=comsol のとき、実行せずにコマンド行だけを表示する")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.generations is not None:
        cfg["ga"]["generations"] = args.generations
    if args.population is not None:
        cfg["ga"]["population_size"] = args.population
    if args.method is not None:
        cfg["ga"]["method"] = args.method
    if args.seed is not None:
        cfg["ga"]["seed"] = args.seed

    if args.dry_run:
        if cfg["mode"] != "comsol":
            print("--dry-run は mode=comsol のときだけ意味があります。")
            return 0
        ev = ComsolEvaluator(cfg)
        mid = [0.5 * (lo + hi) for lo, hi in
               [(float(v["min"]), float(v["max"])) for v in cfg["variables"]]]
        print("中央値の個体で組み立てられるコマンド:")
        print(" ".join(ev.build_command(mid, os.path.abspath("dry_run_job"))))
        return 0

    run_ga(cfg, args.config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
