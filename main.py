import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import re
import tempfile
import json
import requests
import base64
import io
from pathlib import Path
import glob
from datetime import datetime, timedelta

st.set_page_config(page_title="Al Brooks 案例构建器", layout="wide")

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
GITHUB_REPO_OWNER = st.secrets.get("DATA_REPO_OWNER", "xiaobingwudi")
GITHUB_REPO_NAME = st.secrets.get("DATA_REPO_NAME", "private-data")
GITHUB_PATH = st.secrets.get("DATA_FILE_PATH", "cases_database.json")
GITHUB_BRANCH = st.secrets.get("DATA_REPO_BRANCH", "main")
PARQUET_PATH = st.secrets.get("PARQUET_PATH", "ES_CONTINUOUS_5M.parquet")
GITHUB_REPO = f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"

# 从PARQUET_PATH推断images目录路径
PARQUET_DIR = os.path.dirname(PARQUET_PATH)
if PARQUET_DIR:
    IMAGES_PATH = f"{PARQUET_DIR}/images"
else:
    IMAGES_PATH = "images"

if 'html_annotations' not in st.session_state:
    st.session_state.html_annotations = {}
if 'df_5m' not in st.session_state:
    st.session_state.df_5m = None
if 'data_file_loaded' not in st.session_state:
    st.session_state.data_file_loaded = False
if 'builder_df' not in st.session_state:
    st.session_state.builder_df = None
if 'builder_date' not in st.session_state:
    st.session_state.builder_date = None
if 'builder_start' not in st.session_state:
    st.session_state.builder_start = None
if 'builder_end' not in st.session_state:
    st.session_state.builder_end = None
if 'html_filename' not in st.session_state:
    st.session_state.html_filename = None
if 'combined_df' not in st.session_state:
    st.session_state.combined_df = None
if 'pre_df' not in st.session_state:
    st.session_state.pre_df = None
if 'main_df' not in st.session_state:
    st.session_state.main_df = None

def get_github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.raw"
    }

def load_cases_database():
    if not GITHUB_TOKEN:
        return {"cases": []}
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    params = {"ref": GITHUB_BRANCH}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content)
        elif response.status_code == 404:
            return {"cases": []}
        else:
            return {"cases": []}
    except Exception as e:
        return {"cases": []}

def save_cases_database(db):
    if not GITHUB_TOKEN:
        st.error("GitHub配置缺失")
        return False
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    content = json.dumps(db, ensure_ascii=False, indent=2)
    content_bytes = content.encode("utf-8")
    content_base64 = base64.b64encode(content_bytes).decode("utf-8")
    
    params = {"ref": GITHUB_BRANCH}
    response = requests.get(url, headers=headers, params=params)
    
    payload = {
        "message": f"Update cases database ({len(db.get('cases', []))} cases)",
        "content": content_base64,
        "branch": GITHUB_BRANCH
    }
    
    if response.status_code == 200:
        payload["sha"] = response.json()["sha"]
    elif response.status_code != 404:
        return False
    
    response = requests.put(url, headers=headers, json=payload)
    return response.status_code in [200, 201]

@st.cache_data(show_spinner=False)
def load_parquet_from_github():
    if not GITHUB_TOKEN:
        return None
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{PARQUET_PATH}"
    params = {"ref": GITHUB_BRANCH}
    
    try:
        response = requests.get(url, headers=get_github_headers(), params=params)
        
        if response.status_code == 200:
            file_content = response.content
            df = pd.read_parquet(io.BytesIO(file_content))
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            return df
        else:
            return None
    except Exception as e:
        return None

def load_image_from_github(image_name):
    """从GitHub加载图片文件"""
    if not GITHUB_TOKEN:
        return None
    
    image_path = f"{IMAGES_PATH}/{image_name}"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{image_path}"
    params = {"ref": GITHUB_BRANCH}
    
    try:
        response = requests.get(url, headers=get_github_headers(), params=params)
        
        if response.status_code == 200:
            return response.content
        else:
            return None
    except Exception as e:
        return None

def find_image_for_html(filename):
    """根据HTML文件名从GitHub加载对应的jpg图片"""
    if not filename:
        return None
    
    base_name = os.path.splitext(filename)[0]
    image_name = f"{base_name}.jpg"
    
    image_data = load_image_from_github(image_name)
    return image_data

def find_image_for_case(case_id):
    """根据案例ID从GitHub加载对应的jpg图片"""
    if not case_id:
        return None
    
    image_name = f"{case_id}.jpg"
    image_data = load_image_from_github(image_name)
    return image_data

def get_previous_trading_date(date_str):
    """获取前一个交易日（简化处理，跳过周末）"""
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    prev_date = date_obj - timedelta(days=1)
    
    # 如果前一天是周六，则再往前推1天到周五
    if prev_date.weekday() == 5:  # 周六
        prev_date = prev_date - timedelta(days=1)
    # 如果前一天是周日，则再往前推2天到周五
    elif prev_date.weekday() == 6:  # 周日
        prev_date = prev_date - timedelta(days=2)
    
    return prev_date.strftime('%Y-%m-%d')

def load_html_annotations(file_content, filename):
    try:
        html_content = file_content.decode("utf-8")
        annotations = {}
        
        notes_match = re.search(r'<span id="note">(.*?)</span>', html_content, re.DOTALL)
        
        if notes_match:
            notes_text = notes_match.group(1)
            lines = re.split(r'<br\s*/?>', notes_text, flags=re.IGNORECASE)
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                match = re.match(r'^(\d+)\s+(.+)', line)
                if match:
                    bar_num = int(match.group(1))
                    desc = match.group(2).strip()
                    desc = re.sub(r'\s+', ' ', desc)
                    annotations[bar_num] = desc
        
        return annotations, filename
    except Exception as e:
        st.error(f"解析HTML失败: {e}")
        return {}, filename

def plot_kline(bars, annotations, first_bar_offset=0, title="K线图"):
    if bars is None or len(bars) == 0:
        return None

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    x_values = list(range(1, len(bars) + 1))

    hover_texts = []
    for i in range(len(bars)):
        row = bars.iloc[i]
        time_str = bars.index[i].strftime('%Y-%m-%d %H:%M')
        o, h, l, c, v = row['open'], row['high'], row['low'], row['close'], row['volume']
        change = c - o
        change_pct = (change / o * 100) if o != 0 else 0
        
        base_text = (
            f"K线 #{i+1}<br>{time_str}<br>"
            f"开: {o:.2f} | 高: {h:.2f}<br>低: {l:.2f} | 收: {c:.2f}<br>"
            f"涨跌: {change:+.2f} ({change_pct:+.2f}%)<br>量: {v:,.0f}"
        )
        
        original_num = i + 1 - first_bar_offset
        if original_num in annotations:
            desc = annotations[original_num]
            if len(desc) > 60:
                desc = desc[:60] + "..."
            base_text += f"<br><br>原图#{original_num}: {desc}"
        hover_texts.append(base_text)

    fig.add_trace(go.Candlestick(
        x=x_values, open=bars['open'], high=bars['high'], low=bars['low'], close=bars['close'],
        name='', increasing=dict(line=dict(color='red', width=1.5), fillcolor='red'),
        decreasing=dict(line=dict(color='black', width=1.5), fillcolor='black'),
        text=hover_texts, hoverinfo='text', showlegend=False
    ), row=1, col=1)

    colors = ['red' if bars['close'].iloc[i] >= bars['open'].iloc[i] else 'black' for i in range(len(bars))]
    fig.add_trace(go.Bar(x=x_values, y=bars['volume'], name='', marker_color=colors,
                         opacity=0.4, showlegend=False, hovertemplate='量: %{y:,.0f}<extra></extra>'), row=2, col=1)

    annotations_on_chart = []
    for i in range(len(bars)):
        row = bars.iloc[i]
        is_green = row['close'] >= row['open']
        y_pos = row['high'] * 1.002 if is_green else row['low'] * 0.998
        color = 'red' if is_green else 'black'
        original_num = i + 1 - first_bar_offset
        text = f"<b>{i+1}</b>*" if original_num in annotations else f"<b>{i+1}</b>"
        annotations_on_chart.append(dict(
            x=x_values[i], y=y_pos, text=text, showarrow=False,
            font=dict(size=10, color=color), xanchor='center',
            yanchor='bottom' if is_green else 'top'
        ))

    fig.update_layout(title=title, height=600, hovermode='x unified', showlegend=False,
                      template='plotly_white', margin=dict(l=50, r=30, t=50, b=30),
                      annotations=annotations_on_chart)
    fig.update_xaxes(range=[0.5, len(bars) + 0.5], showgrid=True, gridcolor='#f0f0f0',
                     tickmode='linear', tick0=1, dtick=1, row=1, col=1)
    fig.update_xaxes(range=[0.5, len(bars) + 0.5], showgrid=True, gridcolor='#f0f0f0',
                     tickmode='linear', tick0=1, dtick=1, row=2, col=1)
    fig.update_yaxes(title_text="", showgrid=True, gridcolor='#f0f0f0', row=1, col=1)
    fig.update_yaxes(title_text="", showgrid=False, row=2, col=1)
    return fig

def get_date_range_from_db(df):
    if df is not None and len(df) > 0:
        return df.index.min().strftime('%Y-%m-%d'), df.index.max().strftime('%Y-%m-%d')
    return None, None

def get_case_id_from_filename(filename):
    name = os.path.splitext(filename)[0]
    return re.sub(r'[^\w\-_]', '_', name)

def save_case_to_database(case_id, title, date, start_time, end_time, df_pre, df_main, annotations):
    """保存案例到数据库，df_pre是盘前6根，df_main是正式K线"""
    pre_count = len(df_pre)
    main_count = min(81, len(df_main))  # 最多81根正式K线
    
    bars_data = []
    
    # 保存盘前K线（编号-6到-1）
    for i in range(pre_count):
        row = df_pre.iloc[i]
        bars_data.append({
            "bar": -(pre_count - i),  # -6, -5, -4, -3, -2, -1
            "open": round(float(row['open']), 2),
            "high": round(float(row['high']), 2),
            "low": round(float(row['low']), 2),
            "close": round(float(row['close']), 2),
            "volume": int(row['volume'])
        })
    
    # 保存正式K线（编号1到81）
    for i in range(main_count):
        row = df_main.iloc[i]
        bars_data.append({
            "bar": i + 1,  # 1, 2, 3, ..., 81
            "open": round(float(row['open']), 2),
            "high": round(float(row['high']), 2),
            "low": round(float(row['low']), 2),
            "close": round(float(row['close']), 2),
            "volume": int(row['volume'])
        })
    
    comments_data = {}
    for original_num, desc in annotations.items():
        if 1 <= original_num <= main_count:
            comments_data[str(original_num)] = {
                "original": desc,
                "translation": "",
                "plain": ""
            }
    
    case_record = {
        "case_id": case_id, "title": title, "date": date,
        "start": start_time, "end": end_time,
        "pre_bars": pre_count, "main_bars": main_count,
        "first_bar_offset": pre_count,  # 偏移量等于盘前K线数量
        "pre_date": get_previous_trading_date(date),
        "bars": bars_data, "comments": comments_data
    }
    
    db = load_cases_database()
    
    for i, c in enumerate(db["cases"]):
        if c.get("case_id") == case_id:
            db["cases"][i] = case_record
            save_cases_database(db)
            return len(bars_data), len(comments_data), True
    
    db["cases"].append(case_record)
    save_cases_database(db)
    return len(bars_data), len(comments_data), False

def delete_case_from_database(case_id):
    db = load_cases_database()
    db["cases"] = [c for c in db["cases"] if c.get("case_id") != case_id]
    save_cases_database(db)
    return True

def plot_kline_from_case(case_data):
    """根据案例数据绘制K线图"""
    bars = case_data.get("bars", [])
    comments = case_data.get("comments", {})
    first_bar_offset = case_data.get("first_bar_offset", 0)
    
    if not bars:
        return None
    
    df_bars = pd.DataFrame(bars)
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    x_values = [b["bar"] for b in bars]
    
    hover_texts = []
    for b in bars:
        bar_num = b["bar"]
        o, h, l, c, v = b["open"], b["high"], b["low"], b["close"], b["volume"]
        change = c - o
        change_pct = (change / o * 100) if o != 0 else 0
        
        if bar_num > 0:
            base_text = (
                f"K线 #{bar_num}<br>"
                f"开: {o:.2f} | 高: {h:.2f}<br>低: {l:.2f} | 收: {c:.2f}<br>"
                f"涨跌: {change:+.2f} ({change_pct:+.2f}%)<br>量: {v:,.0f}"
            )
        else:
            base_text = (
                f"盘前 #{bar_num}<br>"
                f"开: {o:.2f} | 高: {h:.2f}<br>低: {l:.2f} | 收: {c:.2f}<br>"
                f"涨跌: {change:+.2f} ({change_pct:+.2f}%)<br>量: {v:,.0f}"
            )
        
        comment_key = str(bar_num) if bar_num > 0 else None
        if comment_key and comment_key in comments:
            desc = comments[comment_key].get("original", "")
            if desc:
                if len(desc) > 60:
                    desc = desc[:60] + "..."
                base_text += f"<br><br>原图#{bar_num}: {desc}"
        
        hover_texts.append(base_text)
    
    fig.add_trace(go.Candlestick(
        x=x_values, open=df_bars['open'], high=df_bars['high'], 
        low=df_bars['low'], close=df_bars['close'],
        name='', increasing=dict(line=dict(color='red', width=1.5), fillcolor='red'),
        decreasing=dict(line=dict(color='black', width=1.5), fillcolor='black'),
        text=hover_texts, hoverinfo='text', showlegend=False
    ), row=1, col=1)
    
    colors = ['red' if df_bars['close'].iloc[i] >= df_bars['open'].iloc[i] else 'black' for i in range(len(df_bars))]
    fig.add_trace(go.Bar(x=x_values, y=df_bars['volume'], name='', marker_color=colors,
                         opacity=0.4, showlegend=False, hovertemplate='量: %{y:,.0f}<extra></extra>'), row=2, col=1)
    
    annotations_on_chart = []
    for i, b in enumerate(bars):
        bar_num = b["bar"]
        is_green = b['close'] >= b['open']
        y_pos = b['high'] * 1.002 if is_green else b['low'] * 0.998
        color = 'red' if is_green else 'black'
        
        comment_key = str(bar_num) if bar_num > 0 else None
        text = f"<b>{bar_num}</b>*" if (comment_key and comment_key in comments) else f"<b>{bar_num}</b>"
        
        annotations_on_chart.append(dict(
            x=x_values[i], y=y_pos, text=text, showarrow=False,
            font=dict(size=10, color=color), xanchor='center',
            yanchor='bottom' if is_green else 'top'
        ))
    
    title = case_data.get("title", "案例K线图")
    fig.update_layout(title=title, height=600, hovermode='x unified', showlegend=False,
                      template='plotly_white', margin=dict(l=50, r=30, t=50, b=30),
                      annotations=annotations_on_chart)
    fig.update_xaxes(showgrid=True, gridcolor='#f0f0f0', row=1, col=1)
    fig.update_xaxes(showgrid=True, gridcolor='#f0f0f0', row=2, col=1)
    fig.update_yaxes(title_text="", showgrid=True, gridcolor='#f0f0f0', row=1, col=1)
    fig.update_yaxes(title_text="", showgrid=False, row=2, col=1)
    return fig

if not GITHUB_TOKEN:
    st.warning("请在Streamlit Secrets中设置 GITHUB_TOKEN")

st.title("Al Brooks 案例构建器")

# ==================== 步骤1 加载数据 ====================
st.header("步骤1：加载数据")

col_left, col_right = st.columns(2)

with col_left:
    if not st.session_state.data_file_loaded:
        if st.button("从GitHub加载 ES_CONTINUOUS_5M.parquet", use_container_width=True, type="primary"):
            with st.spinner("正在从GitHub加载18MB数据文件..."):
                df_5m = load_parquet_from_github()
                if df_5m is not None:
                    st.session_state.df_5m = df_5m
                    st.session_state.data_file_loaded = True
                    st.success(f"数据加载成功！共 {len(df_5m):,} 根K线")
                    st.rerun()
                else:
                    st.error(f"加载失败，请检查文件路径: {PARQUET_PATH}")
    else:
        st.success(f"数据已加载 ({len(st.session_state.df_5m):,} 根K线)")

with col_right:
    html_file = st.file_uploader("上传HTML说明文件 (.html)", type=['html'], key="html_uploader")
    
    if html_file is not None:
        if st.button("加载说明", use_container_width=True):
            annotations, fname = load_html_annotations(html_file.getvalue(), html_file.name)
            if annotations:
                st.session_state.html_annotations = annotations
                st.session_state.html_filename = fname
                st.success(f"成功加载 {len(annotations)} 条K线说明!")
                st.rerun()
            else:
                st.error("未能解析到注释")
    
    if st.session_state.html_annotations:
        st.success(f"已加载: {st.session_state.html_filename} ({len(st.session_state.html_annotations)} 条)")
        if st.button("清除注释", use_container_width=True):
            st.session_state.html_annotations = {}
            st.session_state.html_filename = None
            st.rerun()

# ==================== 对照图显示（在步骤1和步骤2之间） ====================
if st.session_state.html_filename:
    st.divider()
    st.header("🖼️ 对照图片")
    
    image_data = find_image_for_html(st.session_state.html_filename)
    
    if image_data:
        st.image(image_data, caption=f"对照图: {os.path.splitext(st.session_state.html_filename)[0]}.jpg", use_container_width=True)
        st.success(f"✅ 已从GitHub加载对照图片: {IMAGES_PATH}/{os.path.splitext(st.session_state.html_filename)[0]}.jpg")
    else:
        expected_image = f"{os.path.splitext(st.session_state.html_filename)[0]}.jpg"
        st.warning(f"❌ 未找到对照图片")
        st.info(f"期望的图片路径: {IMAGES_PATH}/{expected_image}")

st.divider()

if st.session_state.data_file_loaded:
    st.header("步骤2：选择日期和时间")
    
    df = st.session_state.df_5m
    min_date, max_date = get_date_range_from_db(df)
    st.info(f"数据库范围: {min_date} 至 {max_date}")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        builder_date = st.text_input("日期 (YYYY-MM-DD) - 正式K线日期", value="2012-12-05")
    with col2:
        col2a, col2b = st.columns(2)
        with col2a:
            builder_start = st.text_input("正式K线开始 (HH:MM)", value="13:30")
        with col2b:
            builder_end = st.text_input("正式K线结束 (HH:MM)", value="20:10")
    with col3:
        st.write("")
        st.write("")
        load_data = st.button("查找数据", use_container_width=True, type="primary")
    
    if load_data:
        try:
            # 获取前一个交易日
            prev_date = get_previous_trading_date(builder_date)
            
            # 加载前一日盘前数据：19:45 - 20:10（最后6根5分钟K线）
            pre_start = pd.to_datetime(f"{prev_date} 19:45")
            pre_end = pd.to_datetime(f"{prev_date} 20:10")
            mask_pre = (df.index >= pre_start) & (df.index <= pre_end)
            df_pre = df[mask_pre].copy()
            
            # 加载当日正式数据：13:30 - 20:10（81根5分钟K线）
            main_start = pd.to_datetime(f"{builder_date} 13:30")
            main_end = pd.to_datetime(f"{builder_date} 20:10")
            mask_main = (df.index >= main_start) & (df.index <= main_end)
            df_main = df[mask_main].copy()
            
            if len(df_pre) > 0 or len(df_main) > 0:
                st.session_state.pre_df = df_pre
                st.session_state.main_df = df_main
                st.session_state.builder_date = builder_date
                st.session_state.builder_start = builder_start
                st.session_state.builder_end = builder_end
                
                # 合并数据用于预览
                combined = pd.concat([df_pre, df_main])
                st.session_state.combined_df = combined
                st.session_state.builder_df = combined
                
                st.success(f"找到盘前 {len(df_pre)} 根K线 ({prev_date} 19:45-20:10) + 正式 {len(df_main)} 根K线 ({builder_date} {builder_start}-{builder_end})")
            else:
                st.error(f"未找到数据")
        except Exception as e:
            st.error(f"查找失败: {e}")
    
    if 'combined_df' in st.session_state and st.session_state.combined_df is not None:
        st.divider()
        st.header("步骤3：K线编号说明")
        
        pre_count = len(st.session_state.pre_df)
        main_count = len(st.session_state.main_df)
        
        st.info(f"""
        **K线编号规则：**
        - 盘前K线（{st.session_state.pre_df.index[0].strftime('%Y-%m-%d %H:%M') if pre_count > 0 else 'N/A'} 至 {st.session_state.pre_df.index[-1].strftime('%Y-%m-%d %H:%M') if pre_count > 0 else 'N/A'}）：编号 #{-(pre_count)} 到 #-1
        - 正式K线（{st.session_state.main_df.index[0].strftime('%Y-%m-%d %H:%M') if main_count > 0 else 'N/A'} 至 {st.session_state.main_df.index[-1].strftime('%Y-%m-%d %H:%M') if main_count > 0 else 'N/A'}）：编号 #1 到 #{main_count}
        """)
        
        col_a, col_b, col_c = st.columns([2, 1, 2])
        with col_a:
            st.metric("盘前K线数量", pre_count)
            st.metric("正式K线数量", main_count)
        with col_b:
            st.write("")
            st.write("")
            st.metric("总K线数", pre_count + main_count)
        with col_c:
            if pre_count > 0:
                prev_date = get_previous_trading_date(st.session_state.builder_date)
                st.info(f"盘前数据来源: {prev_date} 19:45-20:10")
            st.info(f"正式数据来源: {st.session_state.builder_date} {st.session_state.builder_start}-{st.session_state.builder_end}")
        
        st.divider()
        st.header("步骤4：预览并保存")
        
        # 使用合并数据绘图，盘前偏移量为pre_count
        fig = plot_kline(st.session_state.combined_df, st.session_state.html_annotations,
                         first_bar_offset=pre_count,
                         title=f"预览 - {st.session_state.builder_date} (盘前:{pre_count} + 正式:{main_count})")
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        
        if st.session_state.html_annotations:
            st.subheader("注释映射预览")
            preview_data = []
            for original_num, desc in sorted(st.session_state.html_annotations.items()):
                if 1 <= original_num <= main_count:
                    preview_data.append({"原图编号": original_num, "K线编号": original_num, "说明": desc[:60]})
            if preview_data:
                st.dataframe(pd.DataFrame(preview_data), use_container_width=True, height=200)
                st.info(f"{len(preview_data)} 条注释将被保存")
        
        st.divider()
        col_save1, col_save2 = st.columns([2, 1])
        with col_save1:
            case_title = st.text_input("案例标题", value=f"{st.session_state.builder_date}")
        with col_save2:
            st.write("")
            st.write("")
            case_id = get_case_id_from_filename(st.session_state.html_filename) if st.session_state.html_filename else f"case_{st.session_state.builder_date}"
            db = load_cases_database()
            existing = any(c.get("case_id") == case_id for c in db.get("cases", []))
            btn_label = f"更新案例 ({case_id})" if existing else f"保存案例 ({case_id})"
            
            if st.button(btn_label, use_container_width=True, type="primary"):
                if not GITHUB_TOKEN:
                    st.error("请先配置 GITHUB_TOKEN")
                else:
                    try:
                        saved_bars, saved_comments, updated = save_case_to_database(
                            case_id=case_id, title=case_title,
                            date=st.session_state.builder_date,
                            start_time=st.session_state.builder_start,
                            end_time=st.session_state.builder_end,
                            df_pre=st.session_state.pre_df,
                            df_main=st.session_state.main_df,
                            annotations=st.session_state.html_annotations
                        )
                        st.balloons()
                        st.success(f"保存成功！{case_id} | K线:{saved_bars} | 注释:{saved_comments}")
                    except Exception as e:
                        st.error(f"保存失败: {e}")

# ==================== 已保存案例关联图 ====================
st.divider()
st.header("📊 已保存案例关联图")

db = load_cases_database()
cases = db.get("cases", [])

if cases:
    case_options = {f"{c.get('case_id')} - {c.get('date', '')} - {c.get('title', '')}": c for c in cases}
    selected_case_label = st.selectbox(
        "选择案例查看关联图",
        options=list(case_options.keys()),
        key="case_viewer_select"
    )
    
    if selected_case_label:
        selected_case = case_options[selected_case_label]
        case_id = selected_case.get("case_id", "")
        
        col_chart, col_image = st.columns([3, 2])
        
        with col_chart:
            st.subheader(f"📈 K线图 - {selected_case.get('title', case_id)}")
            fig = plot_kline_from_case(selected_case)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                
                comments = selected_case.get("comments", {})
                if comments:
                    with st.expander("查看所有注释"):
                        for bar_num, comment_data in sorted(comments.items(), key=lambda x: int(x[0])):
                            original = comment_data.get("original", "")
                            st.text(f"K线 #{bar_num}: {original}")
            else:
                st.warning("该案例没有K线数据")
        
        with col_image:
            st.subheader(f"🖼️ 对照图片")
            
            image_data = find_image_for_case(case_id)
            
            if image_data:
                st.image(image_data, caption=f"对照图: {case_id}.jpg", use_container_width=True)
                st.success(f"✅ 已从GitHub加载对照图片")
            else:
                st.warning(f"❌ 未找到对照图片")
                st.info(f"期望的图片路径: {IMAGES_PATH}/{case_id}.jpg")
else:
    st.info("暂无案例数据，请先创建案例")

st.divider()
st.header("案例管理")

with st.expander("查看和管理所有案例", expanded=True):
    db = load_cases_database()
    cases = db.get("cases", [])
    st.write(f"总案例数: {len(cases)}")
    st.caption(f"数据源: {GITHUB_REPO}/{GITHUB_PATH}")
    
    if cases:
        for i, c in enumerate(cases):
            cid = c.get("case_id", f"case_{i}")
            date = c.get("date", "未知")
            title = c.get("title", "")
            pre = c.get("pre_bars", 0)
            main = c.get("main_bars", 0)
            comments_count = len(c.get("comments", {}))
            pre_date = c.get("pre_date", "未知")
            
            col_info, col_btn1, col_btn2 = st.columns([5, 1, 1])
            with col_info:
                st.write(f"**{cid}** | {date} | {title} | 盘前({pre_date}):{pre} 正式:{main} 注释:{comments_count}")
            with col_btn1:
                with st.expander("详情"):
                    st.json(c.get("comments", {}))
            with col_btn2:
                if st.button("删除", key=f"delete_{cid}", use_container_width=True):
                    delete_case_from_database(cid)
                    st.success(f"已删除案例: {cid}")
                    st.rerun()
    else:
        st.info("暂无案例")
