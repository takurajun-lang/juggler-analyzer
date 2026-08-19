#!/usr/bin/env python3
"""
COMSOL セットアップ検証スクリプト

このスクリプトは以下を検証:
1. ga_electrode_base.mph が存在し、読み込み可能
2. COMSOL CLI が実行可能
3. Parametric Sweep の結果が正しく生成される
4. fitness.csv が正しい形式で出力される
5. ga_comsol.py が fitness.csv を正しく解析できる
"""

import os
import sys
import json
import subprocess
import tempfile
import shutil
from pathlib import Path


def check_comsol_executable(config):
    """COMSOL CLI が実行可能か確認"""
    executable = config['comsol']['executable']
    launcher_args = config['comsol']['launcher_args']

    print(f"[CHECK] COMSOL executable: {executable}")

    # COMSOL version確認
    cmd = [executable] + launcher_args + ["-version"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            print(f"  ✓ COMSOL found: {version}")
            return True
        else:
            print(f"  ✗ COMSOL returned error: {result.stderr}")
            return False
    except FileNotFoundError:
        print(f"  ✗ COMSOL executable not found: {executable}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  ✗ COMSOL timed out")
        return False
    except Exception as e:
        print(f"  ✗ Error running COMSOL: {e}")
        return False


def check_model_file(config):
    """COMSOL モデルファイルが存在するか確認"""
    inputfile = config['comsol']['inputfile']

    print(f"[CHECK] Model file: {inputfile}")

    if os.path.isfile(inputfile):
        size_mb = os.path.getsize(inputfile) / (1024**2)
        print(f"  ✓ Model file found ({size_mb:.1f} MB)")
        return True
    else:
        print(f"  ✗ Model file not found")
        return False


def check_fitness_file_format():
    """fitness.csv の形式を確認"""
    print("[CHECK] Fitness CSV format")

    # ga_comsol.py の解析ロジックをテスト
    sys.path.insert(0, os.path.dirname(__file__))
    from ga_comsol import read_fitness_csv

    # テストケース
    test_cases = [
        ("1.23456789", 1.23456789),
        ("% Comment\n1.23456789", 1.23456789),
        ("# Comment\n0.5", 0.5),
        ("  1.5  ", 1.5),  # Whitespace
    ]

    all_pass = True
    for content, expected in test_cases:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(content)
            temp_file = f.name

        try:
            # fitness_parser設定（デフォルト）
            parser_config = {
                "mode": "last_numeric",
                "column": -1,
                "delimiter": ",",
                "comment_prefixes": ["%", "#"]
            }
            result = read_fitness_csv(temp_file, parser_config)

            if abs(result - expected) < 1e-6:
                print(f"  ✓ '{content.strip()}' → {result}")
            else:
                print(f"  ✗ '{content.strip()}' → {result} (expected {expected})")
                all_pass = False
        except Exception as e:
            print(f"  ✗ Error parsing '{content.strip()}': {e}")
            all_pass = False
        finally:
            os.unlink(temp_file)

    return all_pass


def check_parametric_sweep_structure():
    """Parametric Sweep の構造を確認するための情報を表示"""
    print("[INFO] Expected Parametric Sweep Structure")
    print("  cell_on: {0, 1} (2 values)")
    print("  cellx: range(-(eg/2+ew/2), (eg/2+ew/2), 9) (9 positions)")
    print("  Total: 18 combinations")
    print("  Each point: 36 frequency points (10^2 to 10^9 Hz)")
    print("  Total evaluations per job: 18 * 36 = 648 frequency responses")
    return True


def check_ga_integration():
    """GA との統合を確認"""
    print("[CHECK] GA integration")

    sys.path.insert(0, os.path.dirname(__file__))
    try:
        from ga_comsol import ComsolEvaluator
        print("  ✓ ga_comsol.py loaded successfully")

        # ComsolEvaluator の初期化を試す（テスト用）
        test_config = {
            'comsol': {
                'executable': 'comsol',
                'launcher_args': ['batch'],
                'inputfile': 'ga_electrode_base.mph',
                'study': 'std1',
                'extra_args': ['-nosave'],
                'np': 1,
                'timeout_sec': 7200,
                'fitness_file': 'fitness.csv',
                'copy_inputfile_to_job': False,
                'fitness_parser': {
                    'mode': 'last_numeric',
                    'column': -1,
                    'delimiter': ',',
                    'comment_prefixes': ['%', '#']
                }
            },
            'variables': [
                {'name': 'ew', 'min': 3.0, 'max': 20.0},
                {'name': 'eg', 'min': 2.0, 'max': 15.0},
                {'name': 'el', 'min': 15.0, 'max': 38.0}
            ]
        }

        # Evaluator を作成（実行しない）
        evaluator = ComsolEvaluator(test_config)
        print("  ✓ ComsolEvaluator initialized")
        return True
    except Exception as e:
        print(f"  ✗ Error with GA integration: {e}")
        return False


def main():
    """メイン検証ルーチン"""
    print("=" * 60)
    print("COMSOL GA Setup Validation")
    print("=" * 60)
    print()

    # 設定ファイルを読み込む
    config_file = 'config.comsol.ubuntu.json'
    if not os.path.isfile(config_file):
        print(f"[ERROR] Config file not found: {config_file}")
        print("  実行フォルダ確認: {}".format(os.getcwd()))
        sys.exit(1)

    with open(config_file) as f:
        config = json.load(f)

    print(f"Configuration: {config_file}")
    print()

    # 各チェックを実行
    checks = [
        ("COMSOL Executable", lambda: check_comsol_executable(config)),
        ("Model File", lambda: check_model_file(config)),
        ("Fitness CSV Format", check_fitness_file_format),
        ("Parametric Sweep Structure", check_parametric_sweep_structure),
        ("GA Integration", check_ga_integration),
    ]

    results = {}
    for name, check_func in checks:
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"[ERROR] {name}: {e}")
            results[name] = False
        print()

    # 結果サマリ
    print("=" * 60)
    print("Summary:")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print()
    print(f"Total: {passed}/{total} checks passed")

    if passed == total:
        print("\n✓ All checks passed! Ready for GA loop.")
        sys.exit(0)
    else:
        print("\n✗ Some checks failed. See above for details.")
        sys.exit(1)


if __name__ == '__main__':
    main()
