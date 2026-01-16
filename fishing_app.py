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

# --- 1. SUPER FULL SCREEN CSS (ลบขอบดำและ Header/Footer) ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

st.markdown("""
    <style>
    /* ลบ Header และระยะขอบบน */
    header {visibility: hidden !important;}
    footer {visibility: hidden !important;}
    #root > div:nth-child(1) > div > div > div > div > section > div {padding: 0px !important;}
    
    /* บังคับให้หน้าจอหลักไม่มี Scrollbar และเต็มจอ */
    .main .block-container {
        max-width: 100vw !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    
    /* ปุ่มลอยสำหรับเมนู (จัดตำแหน่งทับบนแผนที่) */
    .floating-menu {
        position: fixed;
        top: 10px;
        left: 10px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.9);
        padding: 10px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONFIGURATION & DATA ---
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://ajurexheolscvnkycaqo.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqdXJleGhlb2xzY3Zua3ljYXFvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgyMDk2OTYsImV4cCI6MjA4Mzc4NTY5Nn0.i6akECleLwulyUDiWHthrEaFj-jYk6lNHuFq9T0n_ts")
WEATHER_API_KEY = "2e323a6a31b3c5ffae1efed13dad633b"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("เชื่อมต่อ Supabase ไม่สำเร็จ")

@st.cache_data(ttl=600)
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url'])

@st.cache_data(ttl=3600)
def get_info(lat, lon, name):
    try:
        w_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(w_url, timeout=3).json()
        weather = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        return weather
    except: return "N/A"

# --- 3. GPS & SESSION STATE ---
if 'v_lat' not in st.session_state: st.session_state.v_lat = 13.7563
if 'v_lon' not in st.session_state: st.session_state.v_lon = 100.5018

# ดึงตำแหน่งแบบแม่นยำ
gps = streamlit_js_eval(
    js_expressions="new Promise((r) => {navigator.geolocation.getCurrentPosition((p) => r({lat: p.coords.latitude, lon: p.coords.longitude}), (e) => r(null), {enableHighAccuracy: true})})",
    key='gps_final_fix'
)

# --- 4. FLOATING MENU (เมนูใน Sidebar เพื่อไม่ให้กวนพื้นที่แผนที่) ---
with st.sidebar:
    st.header("🎣 Fishing Menu")
    if st.button("🎯 โฟกัสตำแหน่งฉัน"):
        if gps:
            st.session_state.v_lat = gps['lat']
            st.session_state.v_lon = gps['lon']
            st.rerun()

    st.markdown("---")
    st.subheader("➕ เพิ่มจุดหมายใหม่")
    with st.form("add_form", clear_on_submit=True):
        n = st.text_input("ชื่อหมาย/เขื่อน")
        f_t = st.text_input("ปลาที่พบ")
        imgs = st.file_uploader("รูปภาพ", accept_multiple_files=True)
        if st.form_submit_button("บันทึกพิกัดปัจจุบัน"):
            if gps:
                urls = []
                for f in imgs:
                    img = Image.open(f).convert("RGB")
                    img.thumbnail((800, 800))
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG')
                    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{f.name}"
                    supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
                    urls.append(supabase.storage.from_("fishing_images").get_public_url(fname).replace("http://", "https://"))
                
                supabase.table("spots").insert({
                    "name": n, "lat": gps['lat'], "lon": gps['lon'], 
                    "fish_type": f_t, "image_url": ",".join(urls)
                }).execute()
                st.success("บันทึกแล้ว!")
                st.rerun()

# --- 5. THE ULTIMATE FULLSCREEN MAP ---
df = load_spots()

@st.fragment
def draw_map(df):
    # สร้างแผนที่
    m = folium.Map(
        location=[st.session_state.v_lat, st.session_state.v_lon],
        zoom_start=12,
        tiles="OpenStreetMap"
    )

    # หมุดปัจจุบัน
    if gps:
        folium.Marker([gps['lat'], gps['lon']], icon=folium.Icon(color='red', icon='user', prefix='fa')).add_to(m)

    # หมุดจุดตกปลา
    for _, row in df.iterrows():
        weather = get_info(row['lat'], row['lon'], row['name'])
        images = str(row["image_url"]).split(",") if row["image_url"] else []
        img_html = f'<img src="{images[0]}" style="width:100%; border-radius:8px;">' if images and images[0] else ""

        popup_html = f"""
        <div style='width:200px; font-family:sans-serif;'>
            {img_html}
            <h4 style='margin:5px 0;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ อากาศ:</b> {weather}<br>
            <a href="google.navigation:q={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    # ใช้ความสูง 100vh (เต็มความสูงหน้าจอที่เห็น)
    st_folium(
        m, 
        width="100%", 
        height=1000, # ตั้งค่าเผื่อไว้ CSS จะเป็นตัวคุมความสูงจริง
        returned_objects=[], 
        key="super_full_map"
    )

draw_map(df)
