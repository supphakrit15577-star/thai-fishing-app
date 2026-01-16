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

# --- 1. SET PAGE & FULL WIDTH CSS ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

st.markdown("""
    <style>
    /* ขยายพื้นที่หลักให้กว้างสุดขอบ */
    .main .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        padding-left: 0rem !important;
        padding-right: 0rem !important;
        max-height: 100vh !important;
    }
    /* ซ่อน Footer */
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONFIGURATION & DATA ---
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://ajurexheolscvnkycaqo.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqdXJleGhlb2xzY3Zua3ljYXFvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgyMDk2OTYsImV4cCI6MjA4Mzc4NTY5Nn0.i6akECleLwulyUDiWHthrEaFj-jYk6lNHuFq9T0n_ts")
WEATHER_API_KEY = "2e323a6a31b3c5ffae1efed13dad633b"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("เชื่อมต่อ Database ไม่สำเร็จ")

@st.cache_data(ttl=600)
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url'])

@st.cache_data(ttl=3600)
def get_weather_water(lat, lon, name):
    try:
        w_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(w_url, timeout=3).json()
        weather = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        
        d_url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/get_dam_daily"
        d_res = requests.get(d_url, timeout=3).json()
        water = "ไม่พบข้อมูลน้ำ"
        for dam in d_res['data']['dam']:
            if name in dam['dam_name']['th']:
                water = f"น้ำ {dam['dam_storage_percent']}%"
        return weather, water
    except: return "N/A", "N/A"

# --- 3. GPS & SESSION STATE ---
if 'center_lat' not in st.session_state: st.session_state.center_lat = 13.7563
if 'center_lon' not in st.session_state: st.session_state.center_lon = 100.5018

gps = streamlit_js_eval(
    js_expressions="new Promise((r) => {navigator.geolocation.getCurrentPosition((p) => r({lat: p.coords.latitude, lon: p.coords.longitude}), (e) => r(null), {enableHighAccuracy: true})})",
    key='gps_sidebar_ver'
)

# --- 4. SIDEBAR MENU (เมนูแบบเดิม) ---
with st.sidebar:
    st.title("🎣 Fishing Pro")
    st.write("ระบบจัดการจุดตกปลา")
    
    if st.button("🎯 โฟกัสตำแหน่งปัจจุบัน", use_container_width=True):
        if gps:
            st.session_state.center_lat = gps['lat']
            st.session_state.center_lon = gps['lon']
            st.rerun()

    st.divider()
    
    st.subheader("➕ เพิ่มจุดหมายใหม่")
    with st.form("add_spot_form", clear_on_submit=True):
        n = st.text_input("ชื่อหมาย")
        f_t = st.text_input("ปลาที่พบ")
        up_files = st.file_uploader("เลือกรูปภาพ", accept_multiple_files=True)
        if st.form_submit_button("บันทึกพิกัดจริงเดี๋ยวนี้", use_container_width=True):
            if gps:
                urls = []
                for uf in up_files:
                    img = Image.open(uf).convert("RGB")
                    img.thumbnail((800, 800))
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG')
                    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uf.name}"
                    supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
                    urls.append(supabase.storage.from_("fishing_images").get_public_url(fname).replace("http://", "https://"))
                
                supabase.table("spots").insert({
                    "name": n, "lat": gps['lat'], "lon": gps['lon'], 
                    "fish_type": f_t, "image_url": ",".join(urls)
                }).execute()
                st.success("บันทึกสำเร็จ!")
                st.rerun()
            else:
                st.error("กรุณาเปิด GPS บนเบราว์เซอร์")

# --- 5. MAIN CONTENT (MAP) ---
df = load_spots()

@st.fragment
def render_map(df):
    m = folium.Map(
        location=[st.session_state.center_lat, st.session_state.center_lon],
        zoom_start=12,
        tiles="OpenStreetMap"
    )

    # หมุดตำแหน่งเรา
    if gps:
        folium.Marker(
            [gps['lat'], gps['lon']], 
            icon=folium.Icon(color='red', icon='user', prefix='fa'),
            popup="คุณอยู่ที่นี่"
        ).add_to(m)

    # หมุดจุดตกปลา
    for _, row in df.iterrows():
        weather, water = get_weather_water(row['lat'], row['lon'], row['name'])
        images = str(row["image_url"]).split(",") if row["image_url"] else []
        
        # จัดการรูปภาพแบบเลื่อน
        img_html = ""
        if images and images[0]:
            img_html = '<div style="display: flex; overflow-x: auto; gap: 5px; width: 220px; background:#f0f0f0; border-radius:8px; padding:5px;">'
            for u in images:
                img_html += f'<img src="{u}" style="height: 120px; border-radius: 5px; flex-shrink: 0;">'
            img_html += '</div>'

        popup_content = f"""
        <div style='width: 220px; font-family: sans-serif;'>
            {img_html}
            <h4 style='margin: 8px 0 2px 0; color: #1a73e8;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ อากาศ:</b> {weather}<br>
            <b>💧 ระดับน้ำ:</b> {water}<br>
            <a href="google.navigation:q={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; font-weight:bold; cursor:pointer;'>🚀 เปิดแอปนำทาง</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']],
            popup=folium.Popup(popup_content, max_width=250),
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    # แสดงผลแผนที่กว้างเต็มจอ (Height ปรับตามความเหมาะสมของอุปกรณ์)
    st_folium(m, width="100%", height=600, returned_objects=[], key="stable_sidebar_map")

render_map(df)
