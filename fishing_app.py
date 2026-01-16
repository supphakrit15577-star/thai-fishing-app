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

# --- 2. CACHED FUNCTIONS (ช่วยให้โหลดเร็วขึ้นมาก) ---
@st.cache_data(ttl=600)
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url'])

@st.cache_data(ttl=3600)
def get_info_cached(lat, lon):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(url, timeout=3).json()
        return f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
    except: return "ไม่มีข้อมูล"

# --- 3. SESSION STATE ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

# เก็บพิกัดไว้ที่เดียว ไม่ให้แอปสับสน
if 'view_lat' not in st.session_state:
    st.session_state.view_lat = 13.7563
    st.session_state.view_lon = 100.5018
if 'view_zoom' not in st.session_state:
    st.session_state.view_zoom = 12

# ดึง GPS แบบแม่นยำสูง (ทำครั้งเดียวเมื่อโหลดหน้า หรือกดปุ่ม)
gps_js = """
new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
        (p) => resolve({lat: p.coords.latitude, lon: p.coords.longitude}),
        (e) => resolve(null),
        {enableHighAccuracy: true, timeout: 5000}
    );
})
"""
raw_gps = streamlit_js_eval(js_expressions=gps_js, key='gps_engine')

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")

if st.sidebar.button("🎯 อัปเดตพิกัดและย้ายแผนที่"):
    if raw_gps:
        st.session_state.view_lat = raw_gps['lat']
        st.session_state.view_lon = raw_gps['lon']
        st.session_state.view_zoom = 15
        st.rerun()

all_data = load_spots()

# ส่วนปักหมุด (เหมือนเดิมแต่เน้นเสถียร)
with st.sidebar.form("add_spot"):
    st.subheader("➕ ปักหมุดหมายใหม่")
    name = st.text_input("ชื่อหมาย")
    fish = st.text_input("ปลาที่พบ")
    files = st.file_uploader("รูปภาพ", type=['jpg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึก"):
        if raw_gps:
            urls = []
            for f in files:
                img = Image.open(f).convert("RGB")
                img.thumbnail((800, 800))
                buf = io.BytesIO()
                img.save(buf, format='JPEG')
                fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{f.name}"
                supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
                urls.append(supabase.storage.from_("fishing_images").get_public_url(fname).replace("http://", "https://"))
            
            supabase.table("spots").insert({
                "name": name, "lat": raw_gps['lat'], "lon": raw_gps['lon'], 
                "fish_type": fish, "image_url": ",".join(urls)
            }).execute()
            st.success("บันทึกแล้ว!")
            st.rerun()

# --- 5. THE STABLE MAP (หัวใจการแก้กระพริบ) ---
st.subheader("🗺️ แผนที่พิกัดตกปลา")

@st.fragment
def show_map(df):
    # สร้าง Map Object
    m = folium.Map(
        location=[st.session_state.view_lat, st.session_state.view_lon],
        zoom_start=st.session_state.view_zoom
    )

    # หมุดปัจจุบัน (สีแดง)
    if raw_gps:
        folium.Marker(
            [raw_gps['lat'], raw_gps['lon']], 
            icon=folium.Icon(color='red', icon='user', prefix='fa'),
            popup="คุณอยู่ที่นี่"
        ).add_to(m)

    # หมุดหมายตกปลา
    for _, row in df.iterrows():
        weather = get_info_cached(row['lat'], row['lon'])
        images = str(row["image_url"]).split(",") if row["image_url"] else []
        
        img_html = ""
        if images and images[0]:
            img_html = f'<img src="{images[0]}" style="width:100%; border-radius:8px; margin-bottom:10px;">'

        popup_html = f"""
        <div style='width:200px; font-family:sans-serif;'>
            {img_html}
            <h4 style='margin:0;'>{row['name']}</h4>
            <small>🐟 {row['fish_type']}</small><br>
            <small>🌡️ {weather}</small>
            <hr>
            <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:8px; border-radius:5px;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    # ใช้การตั้งค่า returned_objects=[] เพื่อตัดลูปการกระพริบเด็ดขาด
    st_folium(
        m, 
        width="100%", 
        height=500, 
        key="fishing_map_final",
        returned_objects=[] 
    )

show_map(all_data)
