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

def get_weather_forecast(lat, lon):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(url).json()
        return f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
    except: return "ไม่มีข้อมูล"

# --- 3. UI SETUP ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

# ป้องกันแผนที่เด้งโดยการล็อคพิกัดไว้ใน Session
if 'current_lat' not in st.session_state:
    st.session_state.current_lat = 13.7563
    st.session_state.current_lon = 100.5018

# ดึง GPS เพียงครั้งเดียวเมื่อเปิดแอป หรือเมื่อสั่งอัปเดต
user_loc = streamlit_js_eval(js_expressions="new Promise(r => navigator.geolocation.getCurrentPosition(p => r(p.coords)))", key='gps_data')
if user_loc:
    st.session_state.current_lat = user_loc['latitude']
    st.session_state.current_lon = user_loc['longitude']

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")
if st.sidebar.button("🎯 อัปเดตพิกัดปัจจุบัน"):
    st.rerun()

all_data = load_spots()

with st.sidebar.form("add_form", clear_on_submit=True):
    st.subheader("➕ ปักหมุดหมายใหม่")
    n = st.text_input("ชื่อหมาย")
    fish_t = st.text_input("ปลาที่พบ")
    u_files = st.file_uploader("เลือกรูปภาพ", type=['jpg','jpeg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึกพิกัด"):
        urls = []
        for u_file in u_files:
            img = Image.open(u_file)
            img.thumbnail((600, 600))
            buf = io.BytesIO()
            img.save(buf, format='JPEG')
            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{u_file.name}"
            supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
            # บังคับ HTTPS
            url = supabase.storage.from_("fishing_images").get_public_url(fname).replace("http://", "https://")
            urls.append(url)
        
        supabase.table("spots").insert({
            "name": n, "lat": st.session_state.current_lat, 
            "lon": st.session_state.current_lon, "fish_type": fish_t, 
            "image_url": ",".join(urls)
        }).execute()
        st.success("บันทึกเรียบร้อย!")
        st.rerun()

# --- 5. MAP DISPLAY ---
st.subheader("🗺️ แผนที่พิกัดหมายตกปลา")
st.info(f"พิกัดคุณ: {st.session_state.current_lat:.4f}, {st.session_state.current_lon:.4f}")

@st.fragment
def render_map(df):
    m = folium.Map(location=[st.session_state.current_lat, st.session_state.current_lon], zoom_start=12)
    
    # หมุดปัจจุบัน
    folium.Marker([st.session_state.current_lat, st.session_state.current_lon], 
                  icon=folium.Icon(color='red', icon='user', prefix='fa'), popup="คุณอยู่ที่นี่").add_to(m)

    for _, row in df.iterrows():
        weather = get_weather_forecast(row['lat'], row['lon'])
        images = [u.strip() for u in str(row["image_url"]).split(",")] if row["image_url"] else []
        
        # จัดการรูปภาพแบบเลื่อนนิ้ว (Horizontal Scroll) - เสถียรกว่า Carousel แบบ JS
        img_html = ""
        if images:
            img_html = '<div style="display: flex; overflow-x: auto; gap: 5px; padding: 5px; width: 220px;">'
            for u in images:
                img_html += f'<img src="{u}" style="height: 140px; border-radius: 8px; flex-shrink: 0;">'
            img_html += '</div>'
            if len(images) > 1:
                img_html += '<p style="font-size: 10px; color: gray; margin: 0;">⮕ เลื่อนนิ้วเพื่อดูภาพเพิ่ม</p>'

        popup_content = f"""
        <div style='font-family: sans-serif; width: 220px;'>
            {img_html}
            <h4 style='margin: 10px 0 5px 0;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ อากาศ:</b> {weather}<br>
            <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; cursor:pointer;'>🚀 นำทาง</button>
            </a>
        </div>
        """
        folium.Marker([row['lat'], row['lon']], 
                      popup=folium.Popup(popup_content, max_width=250), 
                      icon=folium.Icon(color='green', icon='fish', prefix='fa')).add_to(m)

    st_folium(m, width="100%", height=550, key="fishing_map")

render_map(all_data)
