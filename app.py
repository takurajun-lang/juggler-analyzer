"""
🎰 ジャグラー ホール傾向分析ツール
※ 2つの入力モード: URL自動取得 / データ貼り付け
"""
import streamlit as st
import pandas as pd
import numpy as np
from scipy.stats import binom
from bs4 import BeautifulSoup
import requests
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import warnings

# ── 日本語フォント ──
try:
    import japanize_matplotlib
except Exception:
    import matplotlib.font_manager as fm
    _jp = [f.name for f in fm.fontManager.ttflist
           if any(k in f.name.lower() for k in
                  ["gothic","meiryo","yu ","ipaex","noto sans cjk","hiragino"])]
    if _jp:
        plt.rcParams["font.family"] = _jp[0]
    plt.rcParams["axes.unicode_minus"] = False

warnings.filterwarnings("ignore")
sns.set_palette("husl")

# ═══════════════════════════════════════
# ページ設定
# ═══════════════════════════════════════
st.set_page_config(
    page_title="ジャグラー ホール傾向分析ツール",
    page_icon="🎰",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.hero{background:linear-gradient(135deg,#e74c3c 0%,#c0392b 50%,#8e44ad 100%);
 padding:1.5rem 2rem;border-radius:14px;margin-bottom:1.5rem;text-align:center;
 box-shadow:0 6px 24px rgba(231,76,60,.3)}
.hero h1{color:#fff!important;font-size:2rem!important;margin:0!important;
 text-shadow:0 2px 8px rgba(0,0,0,.3)}
.hero p{color:rgba(255,255,255,.85)!important;margin:.4rem 0 0!important}
.kpi{background:linear-gradient(135deg,#1a1d23,#2c3e50);
 border:1px solid rgba(255,255,255,.08);border-radius:12px;
 padding:1.1rem;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.2)}
.kpi .n{font-size:2rem;font-weight:800;
 background:linear-gradient(135deg,#e74c3c,#f39c12);
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.kpi .l{color:#aaa;font-size:.85rem}
.sec{border-left:4px solid #e74c3c;padding-left:12px;
 margin:2rem 0 1rem;font-size:1.25rem;font-weight:700}
@media(max-width:768px){.hero h1{font-size:1.3rem!important}.kpi .n{font-size:1.4rem}}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════
# 機種スペック (全8機種)
# ═══════════════════════════════════════
SPECS = {
    "アイムジャグラー": {
        1:[273.1,439.8],2:[269.7,399.6],3:[269.7,331.0],
        4:[259.0,315.1],5:[259.0,255.0],6:[255.0,255.0],
    },
    "ファンキージャグラー": {
        1:[268.6,439.8],2:[264.3,399.6],3:[260.1,331.0],
        4:[249.2,291.3],5:[240.9,257.0],6:[237.4,237.4],
    },
    "マイジャグラー": {
        1:[273.1,439.8],2:[269.7,399.6],3:[269.7,331.0],
        4:[259.0,315.1],5:[259.0,255.0],6:[240.9,204.8],
    },
    "ハッピージャグラー": {
        1:[273.1,439.8],2:[269.7,399.6],3:[269.7,331.0],
        4:[259.0,315.1],5:[259.0,255.0],6:[240.9,240.9],
    },
    "ゴーゴージャグラー": {
        1:[268.6,374.5],2:[267.5,354.2],3:[260.1,331.0],
        4:[249.2,291.3],5:[240.9,257.0],6:[237.4,237.4],
    },
    "ジャグラーガールズ": {
        1:[268.6,374.5],2:[267.5,354.2],3:[260.1,331.0],
        4:[249.2,291.3],5:[240.9,257.0],6:[237.4,237.4],
    },
    "ミスタージャグラー": {
        1:[268.6,374.5],2:[267.5,354.2],3:[260.1,331.0],
        4:[249.2,291.3],5:[240.9,257.0],6:[237.4,237.4],
    },
    "ウルトラミラクル": {
        1:[267.5,425.6],2:[261.1,402.1],3:[256.0,350.5],
        4:[242.7,322.8],5:[233.2,297.9],6:[216.3,277.7],
    },
}
_DEF = SPECS["マイジャグラー"]

def _probs(model, s):
    spec = _DEF
    for k in SPECS:
        if k in model: spec = SPECS[k]; break
    d = spec.get(s, spec[1])
    return 1/d[0], 1/d[1]

def _model_from_url(url):
    try:
        qs = parse_qs(urlparse(url).query)
        if "kishu" in qs: return unquote(qs["kishu"][0])
    except Exception: pass
    return "マイジャグラーV"

# ═══════════════════════════════════════
# URL入力パーサー
# ═══════════════════════════════════════
def parse_url_input(text):
    text = text.strip().strip('"').strip("'")
    out = []
    for ln in text.split("\n"):
        ln = ln.strip().strip('"').strip("'")
        if not ln or ln.startswith("#"): continue
        parts = ln.split(",", 1)
        if len(parts) == 2 and parts[1].strip():
            out.append((parts[0].strip(), parts[1].strip()))
    return out

# ═══════════════════════════════════════
# テーブルデータ貼り付けパーサー
# ═══════════════════════════════════════
def parse_pasted_data(text, date_label, model_name):
    """タブ区切り or スペース区切りのテーブルデータをパース"""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if not lines:
        return [], "データが空です"

    data = []
    header_found = False
    hm = {}

    for line in lines:
        # タブ or 複数スペースで分割
        cells = re.split(r'\t+|\s{2,}', line)
        if len(cells) < 4:
            # カンマ区切りも試す
            cells = [c.strip() for c in line.split(",")]
        if len(cells) < 4:
            continue

        # ヘッダー行を検出
        if not header_found:
            cell_text = " ".join(cells)
            if "BB" in cell_text and "RB" in cell_text:
                for i, s in enumerate(cells):
                    s = s.strip()
                    if "台番" in s or s == "台": hm["id"] = i
                    elif "G数" in s or "ゲーム" in s: hm["spin"] = i
                    elif s == "BB": hm["bb"] = i
                    elif s == "RB": hm["rb"] = i
                if "id" in hm and "bb" in hm and "rb" in hm:
                    if "spin" not in hm: hm["spin"] = hm.get("id", 0) + 2
                    header_found = True
                continue

        if not header_found:
            continue

        if len(cells) <= max(hm.values()):
            continue

        sp = cells[hm["spin"]].replace(",", "").strip()
        if not sp.isdigit():
            continue
        spin = int(sp)
        if spin == 0:
            continue

        bb_val = cells[hm["bb"]].replace(",", "").strip()
        rb_val = cells[hm["rb"]].replace(",", "").strip()

        data.append(dict(
            date=date_label,
            machine_id=cells[hm["id"]].strip(),
            model=model_name,
            spin=spin,
            bb=int(bb_val) if bb_val.isdigit() else 0,
            rb=int(rb_val) if rb_val.isdigit() else 0,
        ))

    if not data:
        return [], "BB/RBデータが見つかりません。ヘッダー行を含めてコピペしてください。"
    return data, None

# ═══════════════════════════════════════
# URLスクレイピング (requests版)
# ═══════════════════════════════════════
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
})

def scrape(date_label, url):
    model = _model_from_url(url)
    try:
        r = _SESSION.get(url, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        tbl = None
        all_tables = soup.find_all("table")
        for t in all_tables:
            txt = t.text
            if "BB" in txt and "RB" in txt:
                tbl = t; break
        if not tbl:
            title = soup.title.text if soup.title else "N/A"
            return [], f"テーブル未検出 (tables={len(all_tables)}, page={title})"

        rows = tbl.find_all("tr")
        hdr = [c.text.strip() for c in rows[0].find_all(["th", "td"])]

        try:
            hm = {
                "id":   next(i for i, s in enumerate(hdr) if "台番" in s),
                "spin": next(i for i, s in enumerate(hdr) if "G数" in s),
                "bb":   next(i for i, s in enumerate(hdr) if s == "BB"),
                "rb":   next(i for i, s in enumerate(hdr) if s == "RB"),
            }
        except StopIteration:
            return [], f"カラム未検出 (ヘッダー: {hdr})"

        data = []
        for row in rows[1:]:
            cs = [c.text.strip().replace(",", "") for c in row.find_all(["th", "td"])]
            if len(cs) <= max(hm.values()): continue
            sp = cs[hm["spin"]]
            if not sp.isdigit(): continue
            spin = int(sp)
            if spin == 0: continue
            data.append(dict(
                date=date_label, machine_id=cs[hm["id"]], model=model,
                spin=spin,
                bb=int(cs[hm["bb"]]) if cs[hm["bb"]].isdigit() else 0,
                rb=int(cs[hm["rb"]]) if cs[hm["rb"]].isdigit() else 0,
            ))
        return data, None
    except requests.RequestException as e:
        return [], f"通信エラー: {e}"
    except Exception as e:
        return [], str(e)

# ═══════════════════════════════════════
# 設定推定
# ═══════════════════════════════════════
def estimate(data):
    for item in data:
        total, likes = 0, {}
        for s in range(1, 7):
            pb, pr = _probs(item["model"], s)
            lk = binom.pmf(item["bb"], item["spin"], pb) \
               * binom.pmf(item["rb"], item["spin"], pr)
            likes[s] = lk; total += lk
        for s in range(1, 7):
            item[f"p{s}"] = likes[s] / total if total > 0 else 0
        item["hi"] = item["p5"] + item["p6"]
        item["est"] = max(range(1, 7), key=lambda s: item[f"p{s}"])
    return data

# ═══════════════════════════════════════
# グラフ
# ═══════════════════════════════════════
def fig_matsubi(df):
    st.markdown('<div class="sec">📍 末尾分析</div>', unsafe_allow_html=True)
    g = df.groupby("end_digit")["hi"].mean().reset_index()
    g.columns = ["末尾", "高設定期待度"]
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#e74c3c" if v > .3 else "#3498db" for v in g["高設定期待度"]]
    sns.barplot(x="末尾", y="高設定期待度", data=g, palette=colors, ax=ax)
    ax.set_title("台番号末尾ごとの高設定期待度", fontsize=14, fontweight="bold")
    ax.axhline(.3, color="gray", ls="--", alpha=.5, label="基準ライン")
    ax.legend(); ax.grid(axis="y", alpha=.3); fig.tight_layout()
    st.pyplot(fig); plt.close(fig)
    top = g.sort_values("高設定期待度", ascending=False).head(3)
    cols = st.columns(3)
    medals = ["🥇", "🥈", "🥉"]
    for i, (_, r) in enumerate(top.iterrows()):
        cols[i].metric(f"{medals[i]} 末尾{int(r['末尾'])}", f"{r['高設定期待度']:.3f}")

def fig_cluster(df):
    st.markdown('<div class="sec">🔗 並び・塊分析</div>', unsafe_allow_html=True)
    g = df.groupby("mid")["hi"].mean().reset_index()
    g.columns = ["台番号", "高設定期待度"]
    fig, ax = plt.subplots(figsize=(14, 5))
    sns.scatterplot(x="台番号", y="高設定期待度", data=g, s=100,
                    color="#e74c3c", alpha=.7, zorder=5, ax=ax)
    ax.plot(g["台番号"], g["高設定期待度"], color="#3498db", alpha=.4, lw=2)
    ax.set_title("台番号順の高設定期待度", fontsize=14, fontweight="bold")
    ax.grid(axis="y", ls="--", alpha=.5); plt.xticks(rotation=45)
    fig.tight_layout(); st.pyplot(fig); plt.close(fig)
    hot = g[g["高設定期待度"] > .4]
    if len(hot):
        st.success(f"🎯 高設定が期待できる台: {len(hot)} 台")
        st.dataframe(hot.style.format({"高設定期待度": "{:.3f}"}), use_container_width=True)

def fig_corner(df):
    st.markdown('<div class="sec">🏢 角台 ＋ ヒートマップ</div>', unsafe_allow_html=True)
    uids = sorted(df["mid"].unique())
    islands, tmp = [], []
    for i, m in enumerate(uids):
        if i > 0 and m - uids[i - 1] > 5:
            if tmp: islands.append(tmp)
            tmp = []
        tmp.append(m)
    if tmp: islands.append(tmp)
    st.info(f"検出された島: **{len(islands)}**")
    ms = df.groupby("mid")["hi"].mean()
    ld = []
    for isl in islands:
        corners = {isl[0], isl[-1]}
        for m in isl:
            if m in ms:
                ld.append(dict(id=m, type="角台" if m in corners else "中央台", score=ms[m]))
    if not ld: return
    ldf = pd.DataFrame(ld)

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.boxplot(x="type", y="score", data=ldf, palette="Set2",
                hue="type", legend=False, ax=ax)
    ax.set_title("角台 vs 中央台", fontsize=14, fontweight="bold")
    ax.set_ylabel("高設定期待度"); ax.grid(axis="y", alpha=.3)
    fig.tight_layout(); st.pyplot(fig); plt.close(fig)

    sm = ldf.groupby("type")["score"].agg(["mean", "median", "std", "count"])
    sm.columns = ["平均", "中央値", "標準偏差", "台数"]
    st.dataframe(sm.style.format({"平均": "{:.3f}", "中央値": "{:.3f}", "標準偏差": "{:.3f}"}),
                 use_container_width=True)

    mx = max(len(isl) for isl in islands)
    grid = np.full((len(islands), mx), np.nan)
    ann = np.full((len(islands), mx), "", dtype=object)
    for r, isl in enumerate(islands):
        for c, m in enumerate(isl):
            if m in ms: grid[r, c] = ms[m]; ann[r, c] = str(m)
    fig, ax = plt.subplots(figsize=(12, max(4, len(islands) * 1.2)))
    sns.heatmap(grid, annot=ann, fmt="", cmap="YlOrRd",
                cbar_kws={"label": "高設定期待度"}, linewidths=.5, ax=ax)
    ax.set_title("ホール配置ヒートマップ", fontsize=14, fontweight="bold")
    ax.set_xlabel("島内の位置"); ax.set_ylabel("島番号")
    fig.tight_layout(); st.pyplot(fig); plt.close(fig)

def fig_overall(df):
    st.markdown('<div class="sec">🎲 全台系・設定分布</div>', unsafe_allow_html=True)
    da = df.groupby("date")["est"].mean().reset_index()
    da.columns = ["日付", "平均推定設定"]
    st.dataframe(da.style.format({"平均推定設定": "{:.2f}"}), use_container_width=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    sc = df["est"].value_counts().sort_index()
    sns.barplot(x=sc.index, y=sc.values, palette="viridis", ax=ax)
    ax.set_title("推定設定の分布", fontsize=14, fontweight="bold")
    ax.set_xlabel("推定設定"); ax.set_ylabel("台数")
    ax.grid(axis="y", alpha=.3)
    for i, v in enumerate(sc.values):
        ax.text(i, v + .5, str(v), ha="center", fontweight="bold")
    fig.tight_layout(); st.pyplot(fig); plt.close(fig)
    ratio = len(df[df["est"] >= 5]) / len(df) * 100
    if ratio > 30:   st.success(f"✨ 高設定比率: **{ratio:.1f}%** — 多めです！")
    elif ratio > 15: st.info(f"👍 高設定比率: **{ratio:.1f}%** — 標準的")
    else:            st.warning(f"⚠️ 高設定比率: **{ratio:.1f}%** — 少なめ")

# ═══════════════════════════════════════
# 分析結果を表示する共通関数
# ═══════════════════════════════════════
def show_results(all_data, n_targets):
    with st.spinner("📊 設定推定中..."):
        all_data = estimate(all_data)
        df = pd.DataFrame(all_data)
        df["machine_id"] = df["machine_id"].astype(str)
        df = df[df["machine_id"].str.replace("-", "").str.isnumeric()].copy()
        df["mid"] = df["machine_id"].str.replace("-", "").astype(int)
        df["end_digit"] = df["machine_id"].str[-1].astype(int)

    if len(df) == 0:
        st.error("❌ 有効なデータがありませんでした")
        st.stop()

    # KPIカード
    hi = len(df[df["est"] >= 5]) / len(df) * 100
    avg = df["est"].mean()
    c1, c2, c3, c4 = st.columns(4)
    for col, n, l in [(c1, str(len(df)), "分析台数"), (c2, str(n_targets), "取得日数"),
                       (c3, f"{avg:.1f}", "平均推定設定"), (c4, f"{hi:.0f}%", "高設定比率")]:
        col.markdown(f'<div class="kpi"><div class="n">{n}</div><div class="l">{l}</div></div>',
                     unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # タブ
    t1, t2, t3, t4, t5 = st.tabs(
        ["📍 末尾", "🔗 並び", "🏢 角台・ヒートマップ", "🎲 全台系", "📋 データ"])
    with t1: fig_matsubi(df)
    with t2: fig_cluster(df)
    with t3: fig_corner(df)
    with t4: fig_overall(df)
    with t5:
        show = {c: {"date": "日付", "machine_id": "台番号", "model": "機種", "spin": "G数",
                     "bb": "BB", "rb": "RB", "est": "推定設定", "hi": "高設定期待度"}.get(c, c)
                for c in ["date", "machine_id", "model", "spin", "bb", "rb", "est", "hi"]
                if c in df.columns}
        st.dataframe(df[list(show.keys())].rename(columns=show),
                     use_container_width=True, height=500)

    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("📥 CSVダウンロード", data=csv,
                       file_name=f"analysis_{datetime.now():%Y%m%d_%H%M}.csv",
                       mime="text/csv", use_container_width=True)

# ═══════════════════════════════════════
# サイドバー
# ═══════════════════════════════════════
with st.sidebar:
    st.markdown("## 📝 データ入力")
    mode = st.radio("入力方法を選択", ["📋 データ貼り付け", "🔗 URL自動取得"],
                    index=0, help="Cloud版は「データ貼り付け」を使ってください")

    if mode == "🔗 URL自動取得":
        st.caption("「日付, URL」を1行ずつ入力")
        input_text = st.text_area(
            "入力データ",
            placeholder="2/7, https://min-repo.com/xxxxx\n2/14, https://min-repo.com/yyyyy",
            height=200, key="url_input")
    else:
        st.caption("みんレポのデータ表をコピペ")
        date_label = st.text_input("日付ラベル", value="2/15", key="date_label")
        model_choice = st.selectbox("機種", [
            "マイジャグラーV", "アイムジャグラーEX", "ファンキージャグラー2",
            "ハッピージャグラーV3", "ゴーゴージャグラー3",
            "ジャグラーガールズSS", "ミスタージャグラー", "ウルトラミラクルジャグラー"
        ], key="model_choice")
        paste_text = st.text_area(
            "テーブルデータ",
            placeholder="台番\t差枚\tG数\t出率\tBB\tRB\t合成\n601\t-\t6331\t-\t25\t11\t1/176\n602\t...",
            height=250, key="paste_input")

    run = st.button("🚀 分析開始", use_container_width=True, type="primary")
    st.markdown("---")
    with st.expander("📋 対応機種一覧 (全8機種)"):
        st.markdown("""
- SアイムジャグラーEX
- Sファンキージャグラー2
- SマイジャグラーV
- SハッピージャグラーV3
- Sゴーゴージャグラー3
- SジャグラーガールズSS
- Sミスタージャグラー
- Sウルトラミラクルジャグラー
        """)

# ═══════════════════════════════════════
# ヘッダー
# ═══════════════════════════════════════
st.markdown("""
<div class="hero">
    <h1>🎰 ジャグラー ホール傾向分析ツール</h1>
    <p>データを入力 →「分析開始」→ 末尾・並び・ヒートマップを自動分析</p>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════
# メイン処理
# ═══════════════════════════════════════
if run:
    if mode == "🔗 URL自動取得":
        # ── URLモード ──
        targets = parse_url_input(input_text)
        if not targets:
            st.error("❌ データを入力してください。形式: `日付, URL`")
            st.stop()

        st.info(f"📊 {len(targets)} 件のデータを取得します")
        bar = st.progress(0)
        status = st.empty()
        all_data, errs = [], []

        for i, (dt, url) in enumerate(targets):
            status.markdown(f"🚀 **[{i + 1}/{len(targets)}]** `{dt}` を取得中...")
            bar.progress(i / len(targets))
            data, err = scrape(dt, url)
            if err:
                errs.append(f"[{dt}] {err}")
                st.warning(f"⚠️ [{dt}] {err}")
            else:
                all_data.extend(data)
                st.success(f"✅ [{dt}] {len(data)} 台")

        bar.progress(1.0)
        status.empty()

        if not all_data:
            st.error("❌ データを取得できませんでした")
            st.info("💡 **ヒント**: Cloud版では「📋 データ貼り付け」モードをお使いください")
            if errs:
                with st.expander("エラー詳細"):
                    for e in errs: st.code(e)
            st.stop()

        show_results(all_data, len(targets))

    else:
        # ── 貼り付けモード ──
        if not paste_text or not paste_text.strip():
            st.error("❌ テーブルデータを貼り付けてください")
            st.info("""
            **使い方:**
            1. みんレポのページをブラウザで開く
            2. テーブル部分を選択してコピー (`Ctrl+C`)
            3. 左のテキスト欄に貼り付け (`Ctrl+V`)
            """)
            st.stop()

        data, err = parse_pasted_data(paste_text, date_label, model_choice)
        if err:
            st.error(f"❌ {err}")
            st.stop()

        st.success(f"✅ {len(data)} 台のデータを読み込みました")
        show_results(data, 1)

else:
    st.markdown("""
    ### 👈 左のサイドバーから始めましょう

    ---
    #### 📋 データ貼り付けモード（おすすめ）
    1. **みんレポ** のページをブラウザで開く
    2. データテーブルを **`Ctrl+A`** → **`Ctrl+C`** でコピー
    3. 左のテキスト欄に **`Ctrl+V`** で貼り付け
    4. **「🚀 分析開始」** をクリック

    #### � URL自動取得モード（ローカル専用）
    ```
    2/7, https://min-repo.com/2906014/?kishu=マイジャグラーV
    2/14, https://min-repo.com/2921029/?kishu=マイジャグラーV
    ```

    | 分析 | 内容 |
    |------|------|
    | 📍 末尾 | 末尾(0-9)ごとの高設定期待度 |
    | 🔗 並び | 台番号順の高設定の偏り |
    | 🏢 角台 | 角台vs中央台 + ヒートマップ |
    | 🎲 全台系 | 設定分布・高設定比率 |
    """)
