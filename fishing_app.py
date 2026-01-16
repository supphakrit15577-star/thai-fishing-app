import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
import requests
import os
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
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'description', 'image_url'])

def get_real_water_level(dam_name):
    try:
        url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/get_dam_daily"
        res = requests.get(url, timeout=5).json()
        for dam in res['data']['dam']:
            if dam_name in dam['dam_name']['th']:
                return f"น้ำ {dam['dam_storage_percent']}%"
        return "ไม่พบข้อมูล"
    except: return "เชื่อมต่อไม่ได้"

def get_weather_info(lat, lon):
    try:
        curr_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(curr_url).json()
        return f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
    except: return "ไม่มีข้อมูล"

# --- 3. UI & GPS SETUP ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>footer {visibility: hidden;} .stApp header {z-index: 1;}</style>""", unsafe_allow_html=True)

# ดึงพิกัด GPS
user_loc = streamlit_js_eval(
    js_expressions="""
    new Promise((resolve, reject) => {
        navigator.geolocation.watchPosition(
            (pos) => { resolve({lat: pos.coords.latitude, lon: pos.coords.longitude, acc: pos.coords.accuracy}); },
            (err) => { reject(err); },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    })
    """, key='gps_track_v3'
)

curr_lat, curr_lon = (user_loc['lat'], user_loc['lon']) if user_loc else (13.7563, 100.5018)

# ระบบควบคุม Camera แผนที่
if 'map_center' not in st.session_state:
    st.session_state.map_center = [curr_lat, curr_lon]
if 'map_zoom' not in st.session_state:
    st.session_state.map_zoom = 12

# --- 4. SIDEBAR (ฟังก์ชันการใช้งานทั้งหมด) ---
st.sidebar.title("🎣 Fishing Pro")
if user_loc:
    st.sidebar.caption(f"🎯 GPS แม่นยำ: {user_loc['acc']:.1f} ม.")

if st.sidebar.button("📍 ย้ายกล้องไปที่ตำแหน่งฉัน"):
    st.session_state.map_center = [curr_lat, curr_lon]
    st.session_state.map_zoom = 15
    st.rerun()

all_data = load_spots()
f_fish = st.sidebar.multiselect("กรองชนิดปลา", list(set(",".join(all_data['fish_type'].astype(str).replace('None','')).split(","))))
if "" in f_fish: f_fish.remove("")
f_img = st.sidebar.checkbox("แสดงเฉพาะที่มีรูป")

st.sidebar.divider()
with st.sidebar.form("add_form", clear_on_submit=True):
    st.subheader("➕ ปักหมุดหมายใหม่")
    n = st.text_input("ชื่อหมาย")
    fish_type = st.text_input("ปลาที่พบ")
    u_file = st.file_uploader("ถ่ายรูป", type=['jpg','jpeg','png'])
    if st.form_submit_button("บันทึกพิกัดปัจจุบัน"):
        if curr_lat == 13.7563:
            st.error("รอสัญญาณ GPS สักครู่...")
        else:
            img_url = ""
            if u_file:
                img = Image.open(u_file); img.thumbnail((800, 800))
                buf = io.BytesIO(); img.save(buf, format='JPEG')
                fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
                img_url = supabase.storage.from_("fishing_images").get_public_url(fname)
            
            supabase.table("spots").insert({"name":n, "lat":curr_lat, "lon":curr_lon, "fish_type":fish_type, "image_url":img_url}).execute()
            st.success("บันทึกสำเร็จ!")
            st.rerun()

# --- 5. MAP DISPLAY (แก้ไขการกระพริบด้วย Fragment) ---
df = all_data.copy()
if f_fish: df = df[df['fish_type'].apply(lambda x: any(i in str(x) for i in f_fish))]
if f_img: df = df[df['image_url'] != ""]

@st.fragment
def render_stable_map(display_df, u_lat, u_lon):
    # สร้างแผนที่โดยใช้ค่าจาก Session State เพื่อให้นิ่ง
    m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    
    # หมุดตัวเรา
    folium.Marker([u_lat, u_lon], icon=folium.Icon(color='red', icon='user', prefix='fa'), popup="คุณอยู่ที่นี่").add_to(m)

    # หมุดหมายตกปลาพร้อมข้อมูลครบถ้วน
    for _, row in display_df.iterrows():
        weather = get_weather_info(row['lat'], row['lon'])
        water = get_real_water_level(row['name'])
        img_html = f'<img src="{row["image_url"]}" width="100%" style="border-radius:8px;">' if row['image_url'] else ""
        
        popup_content = f"""
        <div style='font-family:sans-serif; min-width:200px;'>
            {img_html}
            <h4 style='margin:5px 0;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ อากาศ:</b> {weather}<br>
            <b>💧 น้ำ:</b> {water}<br>
            <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; cursor:pointer;'>🚀 นำทางด้วย Google Maps</button>
            </a>
        </div>
        """
        folium.Marker(
            [row['lat'], row['lon']], 
            popup=folium.Popup(popup_content, max_width=250), 
            icon=folium.Icon(color='green', icon='fish', prefix='fa')
        ).add_to(m)

    # แสดงแผนที่โดยไม่ส่งค่า center กลับมาเพื่อหยุดการ Rerun วนลูป
    st_folium(m, width="100%", height=600, key="fishing_map_final")

# เรียกใช้งานแผนที่
render_stable_map(df, curr_lat, curr_lon)

st.subheader("📋 รายการหมายทั้งหมด")
st.dataframe(df[['name', 'fish_type']], use_container_width=True, hide_index=True)
