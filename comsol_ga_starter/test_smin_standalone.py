#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_smin_standalone.py
fitness.csv (cell_on, cellx, freq, Z の生データ) から Smin を計算する単独スクリプト。
ga_comsol.py 本体に依存しない（動作確認・実データ検証用）。

使い方:
    python3 test_smin_standalone.py fitness.csv
"""

import sys
import os


def _parse_complex_token(token: str):
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


def read_eis_sweep_csv(path, delimiter="\t", comment_prefixes=("%", "#"),
                        col_cell_on=0, col_cellx=1, col_freq=2, col_z=3,
                        freq_round_digits=6, cellx_round_digits=12):
    if not os.path.isfile(path):
        raise FileNotFoundError("ファイルが見つかりません: %s" % path)

    rows = []
    n_lines = 0
    n_skipped_comment = 0
    n_skipped_parse_error = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            n_lines += 1
            line = raw.strip()
            if not line or line.startswith(tuple(comment_prefixes)):
                n_skipped_comment += 1
                continue
            cells = line.split(delimiter)
            try:
                cell_on = float(cells[col_cell_on])
                cellx = float(cells[col_cellx])
                freq = float(cells[col_freq])
            except (IndexError, ValueError):
                n_skipped_parse_error += 1
                continue
            z = _parse_complex_token(cells[col_z]) if len(cells) > col_z else None
            if z is None:
                n_skipped_parse_error += 1
                continue
            rows.append((cell_on, cellx, freq, z))

    print("読み込んだ総行数: %d" % n_lines)
    print("コメント/空行スキップ: %d" % n_skipped_comment)
    print("パースエラースキップ: %d" % n_skipped_parse_error)
    print("有効データ行: %d" % len(rows))
    print()

    if not rows:
        raise ValueError("数値データ行が見つかりません: %s" % path)

    baseline = {}
    for cell_on, cellx, freq, z in rows:
        if round(cell_on) == 0:
            key = (round(cellx, cellx_round_digits), round(freq, freq_round_digits))
            baseline[key] = z

    print("ベースライン(cell_on=0)の(位置,周波数)組み合わせ数: %d" % len(baseline))

    if not baseline:
        raise ValueError("cell_on=0（ベースライン）の行が見つかりません: %s" % path)

    peak_by_cellx = {}
    for cell_on, cellx, freq, z in rows:
        if round(cell_on) != 1:
            continue
        key = (round(cellx, cellx_round_digits), round(freq, freq_round_digits))
        zbase = baseline.get(key)
        if zbase is None or abs(zbase) == 0:
            continue
        s = abs(z - zbase) / abs(zbase)
        cx_key = round(cellx, cellx_round_digits)
        if cx_key not in peak_by_cellx or s > peak_by_cellx[cx_key]:
            peak_by_cellx[cx_key] = s

    print("cell_on=1 の位置(cellx)数: %d" % len(peak_by_cellx))
    print()
    print("位置ごとの peak sensitivity:")
    for cx in sorted(peak_by_cellx.keys()):
        print("  cellx=%.6e  peak=%.6g" % (cx, peak_by_cellx[cx]))
    print()

    if not peak_by_cellx:
        raise ValueError("cell_on=1 の行が見つかりません: %s" % path)

    smin = min(peak_by_cellx.values())
    return smin


def main():
    if len(sys.argv) < 2:
        print("使い方: python3 test_smin_standalone.py fitness.csv")
        sys.exit(1)

    path = sys.argv[1]
    try:
        smin = read_eis_sweep_csv(path)
        print("=" * 40)
        print("Smin = %.6g" % smin)
        print("=" * 40)
    except Exception as e:
        print("エラー: %s" % e)
        sys.exit(1)


if __name__ == "__main__":
    main()
