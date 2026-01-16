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

# --- 1. SET PAGE & CSS ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

# CSS สำหรับจัดการ Layout ให้แผนที่เต็มจอและสร้าง Floating UI
st.markdown("""
    <style>
    /* ปรับแต่งพื้นที่หลักให้ชิดขอบ */
    .main .block-container {
        padding: 0rem !important;
        max-width: 100vw !important;
    }
    
    /* สร้าง Floating Menu ด้านซ้ายบน */
    .floating-box {
        position: fixed;
        top: 60px; /* หลบ Header ลงมาหน่อย */
        left: 10px;
        z-index: 999;
        background: rgba(255, 255, 255, 0.95);
        padding: 15px;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        width: 280px;
        border: 1px solid #ddd;
    }
    
    /* ซ่อน Footer แต่เปิด Header ไว้ */
    footer {visibility: hidden;}
    header {background-color: rgba(255,255,255,0.8) !important;}
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
    key='gps_v14'
)

# --- 4. FLOATING MENU UI (ซ้อนบนแผนที่) ---
with st.container():
    st.markdown('<div class="floating-box">', unsafe_allow_html=True)
    st.subheader("🎣 Fishing Control")
    
    if st.button("🎯 โฟกัสตำแหน่งฉัน"):
        if gps:
            st.session_state.center_lat = gps['lat']
            st.session_state.center_lon = gps['lon']
            st.rerun()

    with st.expander("➕ เพิ่มจุดหมาย (Spot)"):
        with st.form("add_spot_form", clear_on_submit=True):
            n = st.text_input("ชื่อหมาย")
            f_t = st.text_input("ปลาที่พบ")
            up_files = st.file_uploader("รูปภาพ", accept_multiple_files=True)
            if st.form_submit_button("บันทึกจุดนี้"):
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
                    st.error("ไม่พบพิกัด GPS")
    st.markdown('</div>', unsafe_allow_html=True)

# --- 5. FULL SCREEN MAP ---
df = load_spots()

@st.fragment
def render_map(df):
    m = folium.Map(
        location=[st.session_state.center_lat, st.session_state.center_lon],
        zoom_start=12,
        tiles="OpenStreetMap"
    )

    if gps:
        folium.Marker([gps['lat'], gps['lon']], icon=folium.Icon(color='red', icon='user', prefix='fa')).add_to(m)

    for _, row in df.iterrows():
        weather, water = get_weather_water(row['lat'], row['lon'], row['name'])
        images = str(row["image_url"]).split(",") if row["image_url"] else []
        img_html = f'<img src="{images[0]}" style="width:100%; border-radius:8px; margin-bottom:5px;">' if images and images[0] else ""

        popup_content = f"""
        <div style='width:220px; font-family:sans-serif;'>
            {img_html}
            <h4 style='margin:0;'>{row['name']}</h4>
            <hr style='margin:5px 0;'>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ อากาศ:</b> {weather}<br>
            <b>💧 น้ำ:</b> {water}<br>
            <a href="google.navigation:q={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; font-weight:bold;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']],
            popup=folium.Popup(popup_content, max_width=250),
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    # แสดงผลแผนที่ความสูงเต็มจอ (หักลบ Header เล็กน้อย)
    st_folium(m, width="100%", height=850, returned_objects=[], key="fishing_map_v14")

render_map(df)
