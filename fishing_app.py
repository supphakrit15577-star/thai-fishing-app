import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
import requests
from datetime import datetime
from streamlit_js_eval import streamlit_js_eval
from supabase import create_client, Client
from PIL import Image
import io

# --- 1. CONFIGURATION ---
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://ajurexheolscvnkycaqo.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqdXJleGhlb2xzY3Zua3ljYXFvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgyMDk2OTYsImV4cCI6MjA4Mzc4NTY5Nn0.i6akECleLwulyUDiWHthrEaFj-jYk6lNHuFq9T0n_ts")
WEATHER_API_KEY = "2e323a6a31b3c5ffae1efed13dad633b"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("เชื่อมต่อ Supabase ไม่สำเร็จ")

# --- 2. OPTIMIZED FUNCTIONS (Caching) ---
@st.cache_data(ttl=600) # โหลดข้อมูลจุดตกปลาทุก 10 นาทีพอ
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url'])

@st.cache_data(ttl=3600)
def get_info(lat, lon, name):
    # รวมข้อมูลอากาศและระดับน้ำไว้ในฟังก์ชันเดียวเพื่อลดการเรียก API
    try:
        w_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(w_url, timeout=3).json()
        weather = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
    except: weather = "N/A"
    return weather

# --- 3. SESSION STATE & GPS ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

if 'center' not in st.session_state:
    st.session_state.center = [13.7563, 100.5018]
if 'zoom' not in st.session_state:
    st.session_state.zoom = 12

# ดึง GPS แบบแม่นยำสูง (เรียกครั้งเดียวต่อการกด หรือเรียกห่างๆ)
loc = streamlit_js_eval(
    js_expressions="new Promise(r => navigator.geolocation.getCurrentPosition(p => r(p.coords), e => r(null), {enableHighAccuracy:true}))", 
    key='gps_stable_v12'
)

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")
if st.sidebar.button("🎯 ระบุตำแหน่งจริง"):
    if loc:
        st.session_state.center = [loc['latitude'], loc['longitude']]
        st.session_state.zoom = 15
        st.rerun()

all_data = load_spots()

# --- 5. THE STABLE MAP SECTION ---
st.subheader("🗺️ แผนที่พิกัดหมายตกปลา")

@st.fragment
def render_map(df):
    # สร้างแผนที่พื้นฐาน
    m = folium.Map(
        location=st.session_state.center,
        zoom_start=st.session_state.zoom,
        tiles="OpenStreetMap"
    )

    # หมุดปัจจุบัน (ถ้ามีค่า GPS)
    if loc:
        folium.Marker(
            [loc['latitude'], loc['longitude']],
            icon=folium.Icon(color='red', icon='user', prefix='fa'),
            popup="คุณอยู่ที่นี่"
        ).add_to(m)

    # วางหมุดหมายตกปลา
    for _, row in df.iterrows():
        weather = get_info(row['lat'], row['lon'], row['name'])
        images = [u.strip() for u in str(row["image_url"]).split(",")] if row["image_url"] else []
        
        img_html = ""
        if images:
            img_html = '<div style="display: flex; overflow-x: auto; gap: 5px; width: 220px;">'
            for u in images:
                img_html += f'<img src="{u}" style="height: 120px; border-radius: 5px;">'
            img_html += '</div>'

        popup_html = f"""
        <div style='width: 220px; font-family: sans-serif;'>
            {img_html}
            <h4 style='margin: 10px 0;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ อากาศ:</b> {weather}<br>
            <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:8px; border-radius:5px; margin-top:10px; cursor:pointer;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    # หัวใจสำคัญ: returned_objects=[] จะหยุดการส่งค่ากลับมา ทำให้ Loop การกระพริบขาดจากกัน
    st_folium(
        m, 
        width="100%", 
        height=550, 
        key="main_fishing_map",
        returned_objects=[] # ไม่ส่งค่ากลับ = ไม่กระพริบ
    )

render_map(all_data)
