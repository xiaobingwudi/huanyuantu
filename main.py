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

st.set_page_config(page_title="Al Brooks 案例构建器", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_5M = os.path.join(BASE_DIR, "ES_CONTINUOUS_5M.parquet")

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
GITHUB_REPO = st.secrets.get("GITHUB_REPO", "")
GITHUB_PATH = st.secrets.get("GITHUB_PATH", "cases_database.json")
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")

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

def get_github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

def load_cases_database():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return {"cases": []}
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    params = {"ref": GITHUB_BRANCH}
    
    try:
        response = requests.get(url, headers=get_github_headers(), params=params)
        
        if response.status_code == 200:
            data = response.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content)
        elif response.status_code == 404:
            return {"cases": []}
        else:
            st.error(f"读取GitHub失败: {response.status_code}")
            return {"cases": []}
    except Exception as e:
        st.error(f"连接GitHub失败: {e}")
        return {"cases": []}

def save_cases_database(db):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        st.error("GitHub配置缺失，请在secrets.toml中设置GITHUB_TOKEN和GITHUB_REPO")
        return False
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    
    content = json.dumps(db, ensure_ascii=False, indent=2)
    content_bytes = content.encode("utf-8")
    content_base64 = base64.b64encode(content_bytes).decode("utf-8")
    
    params = {"ref": GITHUB_BRANCH}
    response = requests.get(url, headers=get_github_headers(), params=params)
    
    payload = {
        "message": f"Update cases database ({len(db.get('cases', []))} cases)",
        "content": content_base64,
        "branch": GITHUB_BRANCH
    }
    
    if response.status_code == 200:
        data = response.json()
        payload["sha"] = data["sha"]
    
    try:
        response = requests.put(url, headers=get_github_headers(), json=payload)
        
        if response.status_code in [200, 201]:
            return True
        else:
            st.error(f"保存到GitHub失败: {response.status_code}")
            st.error(response.json())
            return False
    except Exception as e:
        st.error(f"连接GitHub失败: {e}")
        return False

def load_5m_data():
    if os.path.exists(CACHE_5M):
        try:
            df = pd.read_parquet(CACHE_5M)
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            st.error(f"加载数据失败: {e}")
            return None
    return None

def load_html_annotations(html_path):
    if not html_path or not os.path.exists(html_path):
        return {}

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

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
        
        return annotations
    except Exception as e:
        st.error(f"解析HTML失败: {e}")
        return {}

def plot_kline(bars, annotations, first_bar_offset=0, title="K线图"):
    if bars is None or len(bars) == 0:
        return None

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3]
    )

    x_values = list(range(1, len(bars) + 1))

    hover_texts = []
    for i in range(len(bars)):
        row = bars.iloc[i]
        time_str = bars.index[i].strftime('%Y-%m-%d %H:%M')
        k_num = i + 1
        o, h, l, c, v = row['open'], row['high'], row['low'], row['close'], row['volume']
        change = c - o
        change_pct = (change / o * 100) if o != 0 else 0
        
        base_text = (
            f"K线 #{k_num}<br>{time_str}<br>"
            f"开: {o:.2f} | 高: {h:.2f}<br>低: {l:.2f} | 收: {c:.2f}<br>"
            f"涨跌: {change:+.2f} ({change_pct:+.2f}%)<br>量: {v:,.0f}"
        )
        
        original_num = i + 1 - first_bar_offset
        if original_num in annotations:
            desc = annotations[original_num]
            if len(desc) > 60:
                desc = desc[:60] + "..."
            base_text += f"<br><br>📝 原图#{original_num}: {desc}"
        
        hover_texts.append(base_text)

    fig.add_trace(
        go.Candlestick(
            x=x_values,
            open=bars['open'],
            high=bars['high'],
            low=bars['low'],
            close=bars['close'],
            name='',
            increasing=dict(line=dict(color='red', width=1.5), fillcolor='red'),
            decreasing=dict(line=dict(color='black', width=1.5), fillcolor='black'),
            text=hover_texts,
            hoverinfo='text',
            showlegend=False
        ),
        row=1, col=1
    )

    colors = ['red' if bars['close'].iloc[i] >= bars['open'].iloc[i] else 'black' for i in range(len(bars))]

    fig.add_trace(
        go.Bar(
            x=x_values,
            y=bars['volume'],
            name='',
            marker_color=colors,
            opacity=0.4,
            showlegend=False,
            hovertemplate='量: %{y:,.0f}<extra></extra>'
        ),
        row=2, col=1
    )

    annotations_on_chart = []
    
    for i in range(len(bars)):
        row = bars.iloc[i]
        k_num = i + 1
        is_green = row['close'] >= row['open']
        
        if is_green:
            y_pos = row['high'] * 1.002
            color = 'red'
        else:
            y_pos = row['low'] * 0.998
            color = 'black'
        
        original_num = i + 1 - first_bar_offset
        if original_num in annotations:
            text = f"<b>{k_num}</b>⭐"
        else:
            text = f"<b>{k_num}</b>"
        
        annotations_on_chart.append(dict(
            x=x_values[i],
            y=y_pos,
            text=text,
            showarrow=False,
            font=dict(size=10, color=color),
            xanchor='center',
            yanchor='bottom' if is_green else 'top'
        ))

    fig.update_layout(
        title=title,
        height=600,
        hovermode='x unified',
        showlegend=False,
        template='plotly_white',
        margin=dict(l=50, r=30, t=50, b=30),
        annotations=annotations_on_chart
    )

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
    name = re.sub(r'[^\w\-_]', '_', name)
    return name

def save_case_to_database(case_id, title, date, start_time, end_time, df_selected, annotations, first_bar_number):
    start_idx = first_bar_number - 1
    pre_count = min(6, start_idx)
    main_count = 80
    
    if pre_count > 0:
        df_pre = df_selected.iloc[start_idx - pre_count:start_idx].copy()
        df_main = df_selected.iloc[start_idx:start_idx + main_count].copy()
        df_save = pd.concat([df_pre, df_main])
    else:
        df_save = df_selected.iloc[start_idx:start_idx + main_count].copy()
    
    actual_main = min(main_count, len(df_selected) - start_idx)
    
    bars_data = []
    if pre_count > 0:
        for i in range(pre_count):
            row = df_save.iloc[i]
            bars_data.append({
                "bar": -(pre_count - i),
                "open": round(float(row['open']), 2),
                "high": round(float(row['high']), 2),
                "low": round(float(row['low']), 2),
                "close": round(float(row['close']), 2),
                "volume": int(row['volume'])
            })
    
    for i in range(actual_main):
        row = df_save.iloc[pre_count + i]
        bars_data.append({
            "bar": i + 1,
            "open": round(float(row['open']), 2),
            "high": round(float(row['high']), 2),
            "low": round(float(row['low']), 2),
            "close": round(float(row['close']), 2),
            "volume": int(row['volume'])
        })
    
    comments_data = {}
    for original_num, desc in annotations.items():
        if 1 <= original_num <= actual_main:
            comments_data[str(original_num)] = {
                "original": desc,
                "translation": "",
                "plain": ""
            }
    
    case_record = {
        "case_id": case_id,
        "title": title,
        "date": date,
        "start": start_time,
        "end": end_time,
        "pre_bars": pre_count,
        "main_bars": actual_main,
        "first_bar_offset": first_bar_number - 1,
        "bars": bars_data,
        "comments": comments_data
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

if not GITHUB_TOKEN or not GITHUB_REPO:
    st.error("""
    GitHub配置缺失！
    
    请在Streamlit Cloud的Settings > Secrets中设置：
