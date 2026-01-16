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

# --- 1. CONFIG & CSS INJECTION (สำหรับทำให้เต็มจอ) ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

# CSS เพื่อกำจัด Padding ของ Streamlit และทำให้แผนที่ขยายสุดขอบ
st.markdown("""
    <style>
    .main .block-container {
        padding-top: 0rem;
        padding-bottom: 0rem;
        padding-left: 0rem;
        padding-right: 0rem;
    }
    iframe {
        width: 100vw;
        height: 100vh;
    }
    .stButton button {
        width: 100%;
    }
    /* ปรับแต่งปุ่มลอยสำหรับเพิ่มจุด */
    div.stActionButton {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://ajurexheolscvnkycaqo.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqdXJleGhlb2xzY3Zua3ljYXFvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgyMDk2OTYsImV4cCI6MjA4Mzc4NTY5Nn0.i6akECleLwulyUDiWHthrEaFj-jYk6lNHuFq9T0n_ts")
WEATHER_API_KEY = "2e323a6a31b3c5ffae1efed13dad633b"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("เชื่อมต่อ Supabase ไม่สำเร็จ")

# --- 2. DATA FUNCTIONS ---
@st.cache_data(ttl=600)
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url'])

@st.cache_data(ttl=1800)
def get_info(lat, lon, name):
    try:
        # Weather
        w_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(w_url, timeout=3).json()
        weather = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        # Water (ThaiWater)
        d_url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/get_dam_daily"
        d_res = requests.get(d_url, timeout=3).json()
        water = "ไม่มีข้อมูลน้ำ"
        for dam in d_res['data']['dam']:
            if name in dam['dam_name']['th']:
                water = f"น้ำ {dam['dam_storage_percent']}%"
        return weather, water
    except: return "N/A", "N/A"

# --- 3. GPS & LOCATION ---
if 'v_lat' not in st.session_state: st.session_state.v_lat = 13.7563
if 'v_lon' not in st.session_state: st.session_state.v_lon = 100.5018

gps = streamlit_js_eval(
    js_expressions="new Promise((r) => {navigator.geolocation.getCurrentPosition((p) => r({lat: p.coords.latitude, lon: p.coords.longitude}), (e) => r(null), {enableHighAccuracy: true})})",
    key='gps_full'
)

# --- 4. FLOATING MENU (UI ซ้อนบนแผนที่) ---
# ใช้ Sidebar เป็นตัวควบคุมหลักเพื่อให้แผนที่ไม่ขยับ
with st.sidebar:
    st.title("🎣 เมนูควบคุม")
    if st.button("🎯 ดูตำแหน่งปัจจุบัน"):
        if gps:
            st.session_state.v_lat = gps['lat']
            st.session_state.v_lon = gps['lon']
            st.rerun()
    
    with st.expander("➕ เพิ่มจุดหมายใหม่ (Spot)", expanded=False):
        with st.form("add_form", clear_on_submit=True):
            n = st.text_input("ชื่อหมาย")
            f_t = st.text_input("ปลาที่พบ")
            imgs = st.file_uploader("รูปภาพ", accept_multiple_files=True)
            if st.form_submit_button("บันทึกพิกัดนี้"):
                if gps:
                    # Upload Logic
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

# --- 5. FULL SCREEN MAP ---
df = load_spots()

@st.fragment
def full_map(df):
    # ใช้พิกัดจาก State
    m = folium.Map(
        location=[st.session_state.v_lat, st.session_state.v_lon],
        zoom_start=12,
        tiles="OpenStreetMap",
        control_scale=True,
        zoom_control=True
    )

    # หมุดผู้ใช้
    if gps:
        folium.Marker([gps['lat'], gps['lon']], icon=folium.Icon(color='red', icon='user', prefix='fa')).add_to(m)

    # หมุดจุดตกปลา
    for _, row in df.iterrows():
        weather, water = get_info(row['lat'], row['lon'], row['name'])
        images = str(row["image_url"]).split(",") if row["image_url"] else []
        
        img_html = ""
        if images and images[0]:
            img_html = f'<img src="{images[0]}" style="width:100%; border-radius:8px; margin-bottom:5px;">'

        popup_html = f"""
        <div style='width:220px; font-family:sans-serif;'>
            {img_html}
            <h4 style='margin:0;'>{row['name']}</h4>
            <hr style='margin:5px 0;'>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ อากาศ:</b> {weather}<br>
            <b>💧 น้ำ:</b> {water}<br>
            <a href="google.navigation:q={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:8px; border-radius:5px; margin-top:8px; cursor:pointer;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    # แสดงผลเต็มจอ (width=100%, height=1000 หรือมากกว่าตามต้องการ)
    st_folium(m, width="100%", height=800, returned_objects=[], key="fullscreen_map")

full_map(df)
