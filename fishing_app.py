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

# --- 2. CACHED FUNCTIONS (หัวใจความเร็ว: ดึงข้อมูลแล้วจำไว้) ---
@st.cache_data(ttl=3600)  # จำข้อมูลระดับน้ำ 1 ชั่วโมง
def get_water_info(dam_name):
    try:
        url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/get_dam_daily"
        res = requests.get(url, timeout=5).json()
        for dam in res['data']['dam']:
            if dam_name in dam['dam_name']['th']:
                return f"น้ำ {dam['dam_storage_percent']}% ({dam['dam_name']['th']})"
        return "ไม่มีข้อมูลอ่างเก็บน้ำ"
    except: return "เชื่อมต่อข้อมูลน้ำไม่ได้"

@st.cache_data(ttl=1800)  # จำพยากรณ์อากาศ 30 นาที
def get_full_weather(lat, lon):
    try:
        # 1. อากาศตอนนี้
        now_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(now_url, timeout=5).json()
        now_txt = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        
        # 2. พยากรณ์ล่วงหน้า (ดึงราย 3 ชม. มาคัดเอาวันละจุด)
        fore_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        f = requests.get(fore_url, timeout=5).json()
        fore_list = []
        # คัดเอาข้อมูลทุกๆ 24 ชม. (index 8, 16, 24)
        for i in [8, 16, 24]:
            day = f['list'][i]
            dt = datetime.fromtimestamp(day['dt']).strftime('%d/%m')
            fore_list.append(f"• {dt}: {day['main']['temp']:.0f}°C, {day['weather'][0]['description']}")
        
        fore_html = "<br>".join(fore_list)
        return now_txt, fore_html
    except: return "ไม่มีข้อมูล", "ไม่มีข้อมูลล่วงหน้า"

@st.cache_data(ttl=600)
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url'])

# --- 3. SESSION STATE ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

if 'v_lat' not in st.session_state: st.session_state.v_lat = 13.7563
if 'v_lon' not in st.session_state: st.session_state.v_lon = 100.5018

# GPS แม่นยำสูง (ทำงานเบื้องหลัง)
gps_raw = streamlit_js_eval(
    js_expressions="new Promise((r) => {navigator.geolocation.getCurrentPosition((p) => r({lat: p.coords.latitude, lon: p.coords.longitude}), (e) => r(null), {enableHighAccuracy: true})})",
    key='gps_engine_v13'
)

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")

if st.sidebar.button("🎯 อัปเดตพิกัดปัจจุบัน"):
    if gps_raw:
        st.session_state.v_lat = gps_raw['lat']
        st.session_state.v_lon = gps_raw['lon']
        st.rerun()

all_data = load_spots()

with st.sidebar.form("add_spot"):
    st.subheader("➕ ปักหมุดหมายใหม่")
    name = st.text_input("ชื่อหมาย (ใส่ชื่อเขื่อน/อ่างเก็บน้ำเพื่อดึงระดับน้ำ)")
    fish = st.text_input("ปลาที่พบ")
    files = st.file_uploader("รูปภาพ", type=['jpg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึกพิกัดนี้"):
        if gps_raw:
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
                "name": name, "lat": gps_raw['lat'], "lon": gps_raw['lon'], 
                "fish_type": fish, "image_url": ",".join(urls)
            }).execute()
            st.success("บันทึกสำเร็จ!")
            st.rerun()

# --- 5. STABLE MAP DISPLAY ---
st.subheader("🗺️ แผนที่พิกัดตกปลา")

@st.fragment
def render_fishing_map(df):
    m = folium.Map(location=[st.session_state.v_lat, st.session_state.v_lon], zoom_start=12)

    # หมุดคุณ
    if gps_raw:
        folium.Marker([gps_raw['lat'], gps_raw['lon']], icon=folium.Icon(color='red', icon='user', prefix='fa')).add_to(m)

    for _, row in df.iterrows():
        # ดึงข้อมูลที่ Cache ไว้ (เร็วและไม่ทำให้แผนที่กระพริบ)
        weather_now, weather_fore = get_full_weather(row['lat'], row['lon'])
        water_lv = get_water_info(row['name'])
        
        # จัดการรูปภาพ (เลื่อนนิ้ว)
        images = str(row["image_url"]).split(",") if row["image_url"] else []
        img_html = ""
        if images and images[0]:
            img_html = '<div style="display: flex; overflow-x: auto; gap: 5px; width: 220px; background:#f0f0f0; border-radius:8px; padding:5px;">'
            for u in images:
                img_html += f'<img src="{u}" style="height: 120px; border-radius: 5px; flex-shrink: 0;">'
            img_html += '</div>'

        popup_html = f"""
        <div style='width: 220px; font-family: sans-serif;'>
            {img_html}
            <h4 style='margin: 8px 0 2px 0; color: #1a73e8;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ ตอนนี้:</b> {weather_now}<br>
            <b>💧 น้ำ:</b> {water_lv}
            <hr style='margin: 5px 0;'>
            <small><b>📅 พยากรณ์ 3 วัน:</b><br>{weather_fore}</small>
            <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; cursor:pointer; font-weight:bold;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    #returned_objects=[] เพื่อความนิ่งสูงสุด
    st_folium(m, width="100%", height=550, key="stable_fishing_map", returned_objects=[])

render_fishing_map(all_data)
