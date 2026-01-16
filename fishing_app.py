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

# --- 2. FUNCTIONS ---
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url'])

def get_real_water_level(dam_name):
    try:
        url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/get_dam_daily"
        res = requests.get(url, timeout=5).json()
        for dam in res['data']['dam']:
            if dam_name in dam['dam_name']['th']:
                return f"น้ำ {dam['dam_storage_percent']}%"
        return "ไม่พบข้อมูล"
    except: return "ไม่พบข้อมูล"

def get_weather_forecast(lat, lon):
    try:
        url_now = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(url_now).json()
        now_txt = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        url_fore = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        f = requests.get(url_fore).json()
        fore_html = "<hr style='margin:5px 0;'><small><b>📅 พยากรณ์ 3 วัน:</b><br>"
        for i in [8, 16, 24]:
            day = f['list'][i]
            dt = datetime.fromtimestamp(day['dt']).strftime('%d/%m')
            fore_html += f"• {dt}: {day['main']['temp']:.0f}°C, {day['weather'][0]['description']}<br>"
        fore_html += "</small>"
        return now_txt, fore_html
    except: return "ไม่มีข้อมูล", ""

# --- 3. SESSION STATE FOR MAP (หัวใจของการแก้แมพเด้ง) ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

if 'map_center' not in st.session_state:
    st.session_state.map_center = [13.7563, 100.5018]
if 'map_zoom' not in st.session_state:
    st.session_state.map_zoom = 12
if 'user_pos' not in st.session_state:
    st.session_state.user_pos = [13.7563, 100.5018]

# ดึง GPS แบบทำงานเบื้องหลัง
loc = streamlit_js_eval(js_expressions="new Promise(r => navigator.geolocation.getCurrentPosition(p => r(p.coords)))", key='gps_val')
if loc:
    st.session_state.user_pos = [loc['latitude'], loc['longitude']]

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")

if st.sidebar.button("🎯 อัปเดตตำแหน่งและย้ายกล้อง"):
    st.session_state.map_center = st.session_state.user_pos
    st.session_state.map_zoom = 15
    st.rerun()

all_data = load_spots()

with st.sidebar.form("add_form", clear_on_submit=True):
    st.subheader("➕ ปักหมุดหมายใหม่")
    n = st.text_input("ชื่อหมาย")
    fish_t = st.text_input("ปลาที่พบ")
    u_files = st.file_uploader("เลือกรูปภาพ", type=['jpg','jpeg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึกพิกัดปัจจุบัน"):
        urls = []
        for u_file in u_files:
            img = Image.open(u_file).convert("RGB")
            img.thumbnail((800, 800))
            buf = io.BytesIO()
            img.save(buf, format='JPEG')
            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{u_file.name}"
            supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
            urls.append(supabase.storage.from_("fishing_images").get_public_url(fname).replace("http://", "https://"))
        
        supabase.table("spots").insert({
            "name": n, "lat": st.session_state.user_pos[0], 
            "lon": st.session_state.user_pos[1], "fish_type": fish_t, 
            "image_url": ",".join(urls)
        }).execute()
        st.success("บันทึกเรียบร้อย!")
        st.rerun()

# --- 5. MAIN MAP ---
st.subheader("🗺️ แผนที่พิกัดหมายตกปลา")

# ฟังก์ชันจัดการการวาดแผนที่
def render_map(df):
    m = folium.Map(
        location=st.session_state.map_center, 
        zoom_start=st.session_state.map_zoom
    )
    
    # หมุดปัจจุบัน
    folium.Marker(st.session_state.user_pos, 
                  icon=folium.Icon(color='red', icon='user', prefix='fa'), 
                  popup="คุณอยู่ที่นี่").add_to(m)

    for _, row in df.iterrows():
        weather_now, weather_fore = get_weather_forecast(row['lat'], row['lon'])
        water = get_real_water_level(row['name'])
        images = [u.strip() for u in str(row["image_url"]).split(",")] if row["image_url"] else []
        
        img_html = ""
        if images:
            img_html = '<div style="display: flex; overflow-x: auto; gap: 5px; padding: 5px; width: 220px; border-radius: 8px; background: #f0f0f0;">'
            for u in images:
                img_html += f'<img src="{u}" style="height: 140px; border-radius: 5px; flex-shrink: 0;">'
            img_html += '</div><p style="font-size: 10px; color: #666; margin: 2px 0;">⮕ เลื่อนขวาดูรูป</p>'

        popup_content = f"""
        <div style='font-family: sans-serif; width: 220px;'>
            {img_html}
            <h4 style='margin: 8px 0 2px 0; color: #1a73e8;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ ตอนนี้:</b> {weather_now}<br>
            <b>💧 ระดับน้ำ:</b> {water}
            {weather_fore}
            <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; cursor:pointer;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker([row['lat'], row['lon']], 
                      popup=folium.Popup(popup_content, max_width=250), 
                      icon=folium.Icon(color='green', icon='fish', prefix='fa')).add_to(m)

    # ส่วนสำคัญ: รับค่ากลับจากแผนที่เพื่อจำพิกัดล่าสุดที่ผู้ใช้ซูมหรือเลื่อน
    map_data = st_folium(m, width="100%", height=550, key="fishing_map_v9")
    
    if map_data and map_data['center']:
        # อัปเดตพิกัดและซูมปัจจุบันลงใน Session เพื่อไม่ให้เด้งตอน Rerun
        st.session_state.map_center = [map_data['center']['lat'], map_data['center']['lng']]
        st.session_state.map_zoom = map_data['zoom']

render_map(all_data)
