import os
import csv
import io
from datetime import date
from pathlib import Path
from typing import List

import requests
import streamlit as st
from dotenv import load_dotenv

# -----------------------------
# Utils
# -----------------------------

def normalize_channels(text: str) -> List[str]:
    out: List[str] = []
    for raw in text.replace(",", "\n").splitlines():
        s = raw.strip()
        if s:
            out.append(s)
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def parse_keywords(text: str) -> List[str]:
    parts = []
    for raw in text.replace(",", "\n").splitlines():
        w = raw.strip()
        if w:
            parts.append(w)
    seen = set()
    uniq = []
    for w in parts:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def csv_bytes(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["link", "text"])
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8-sig")
    return data


def txt_bytes(links):
    return ("\n".join(links) + "\n").encode("utf-8")


# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(page_title="TG Video Parser", layout="wide")
st.title("Telegram Parser (user-side)")

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

api_url_default = os.getenv("API_URL", "http://localhost:8000")

if "token" not in st.session_state:
    st.session_state.token = None

with st.expander("Подключение к API", expanded=False):
    api_url = st.text_input("API URL", value=api_url_default)

if not st.session_state.token:
    st.subheader("Вход")
    email = st.text_input("Email", value="")
    password = st.text_input("Пароль", type="password")
    if st.button("Войти", type="primary"):
        try:
            r = requests.post(f"{api_url}/auth/login", json={"email": email, "password": password}, timeout=60)
        except Exception as e:
            st.error(f"Ошибка сети: {e}")
            st.stop()
        if r.status_code != 200:
            st.error(r.json().get("detail", "Ошибка входа"))
            st.stop()
        data = r.json()
        st.session_state.token = data["token"]
        st.success("Вход выполнен")
        st.experimental_rerun()
    st.stop()

# token present
headers = {"Authorization": f"Bearer {st.session_state.token}"}

col_left, col_right = st.columns([3, 1])
with col_right:
    if st.button("Выйти"):
        try:
            requests.post(f"{api_url}/auth/logout", headers=headers, timeout=30)
        except Exception:
            pass
        st.session_state.token = None
        st.experimental_rerun()

with col_left:
    me = None
    try:
        r = requests.get(f"{api_url}/auth/me", headers=headers, timeout=30)
        if r.status_code == 200:
            me = r.json()
    except Exception:
        me = None

    if me:
        st.info(f"Доступ до: {me.get('access_until')} | Запусков осталось сегодня: {me.get('daily_runs_remaining')}")
    else:
        st.warning("Не удалось получить статус аккаунта")

col1, col2 = st.columns(2)
with col1:
    start_d = st.date_input("Дата начала (включительно)", value=date.today())
with col2:
    end_d = st.date_input("Дата конца (включительно)", value=date.today())

kw_text = st.text_area(
    "Ключевые слова (через запятую или каждое с новой строки)",
    value="курьер",
    height=100,
)

channels_text = st.text_area(
    "Каналы (ссылки t.me/... или @username, по одному в строке)",
    value="https://t.me/mod_russia\nhttps://t.me/rogozin_do",
    height=220,
)

videos_only = st.checkbox("Искать только посты с видео", value=True)

run_btn = st.button("RUN", type="primary")

if run_btn:
    keywords = parse_keywords(kw_text)
    channels = normalize_channels(channels_text)

    if not keywords:
        st.error("Ключевые слова пустые.")
        st.stop()
    if not channels:
        st.error("Не распознал ни одного канала. Проверь формат.")
        st.stop()

    payload = {
        "channels": channels,
        "keywords": keywords,
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "videos_only": videos_only,
    }

    with st.spinner("Ищу..."):
        try:
            r = requests.post(f"{api_url}/search", json=payload, headers=headers, timeout=3600)
        except Exception as e:
            st.error(f"Ошибка сети: {e}")
            st.stop()

    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "Ошибка")
        except Exception:
            detail = r.text
        st.error(detail)
        st.stop()

    data = r.json()
    links_only = data.get("links", [])
    rows = data.get("rows", [])

    st.success(f"Готово. Найдено ссылок: {len(links_only)}")

    st.subheader("Ссылки (столбиком)")
    if links_only:
        st.text("\n".join(links_only))
    else:
        st.write("Пусто.")

    st.download_button(
        "Скачать CSV (link,text)",
        data=csv_bytes(rows),
        file_name="tg_links.csv",
        mime="text/csv",
    )

    st.download_button(
        "Скачать TXT со ссылками",
        data=txt_bytes(links_only),
        file_name="tg_links.txt",
        mime="text/plain",
    )
