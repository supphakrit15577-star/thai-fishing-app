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

def get_weather_forecast(lat, lon):
    try:
        curr_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(curr_url).json()
        curr_txt = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        fore_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        f = requests.get(fore_url).json()
        fore_html = "<hr style='margin:5px 0;'><small><b>📅 พยากรณ์ 3 วัน:</b><br>"
        for i in [8, 16, 24]:
            day = f['list'][i]
            dt = datetime.fromtimestamp(day['dt']).strftime('%d/%m')
            fore_html += f"• {dt}: {day['main']['temp']:.0f}°C, {day['weather'][0]['description']}<br>"
        fore_html += "</small>"
        return curr_txt, fore_html
    except: return "ไม่มีข้อมูล", ""

# --- 3. UI SETUP ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")
st.markdown("<style>footer {visibility: hidden;}</style>", unsafe_allow_html=True)

# ดึง GPS (ตั้งค่าให้ดึงแค่ครั้งแรกหรือเมื่อกดปุ่ม เพื่อป้องกันแผนที่เด้ง)
if 'user_lat' not in st.session_state:
    st.session_state.user_lat = 13.7563
    st.session_state.user_lon = 100.5018

user_loc = streamlit_js_eval(
    js_expressions="navigator.geolocation.getCurrentPosition(p => console.log(p), e => console.log(e));", 
    key='gps_once'
) # ใช้เพื่อให้ Browser ขอสิทธิ์ GPS

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")
if st.sidebar.button("🎯 อัปเดตตำแหน่งปัจจุบัน"):
    # ใช้ JS ดึงพิกัดแบบ Manual เพื่อไม่ให้รบกวนหน้าจอหลัก
    loc = streamlit_js_eval(js_expressions="new Promise(r => navigator.geolocation.getCurrentPosition(p => r(p.coords)))", key='get_loc_btn')
    if loc:
        st.session_state.user_lat = loc['latitude']
        st.session_state.user_lon = loc['longitude']
        st.session_state.map_center = [loc['latitude'], loc['longitude']]
        st.rerun()

all_data = load_spots()
f_fish = st.sidebar.multiselect("กรองชนิดปลา", list(set(",".join(all_data['fish_type'].astype(str).replace('None','')).split(","))))

with st.sidebar.form("add_form", clear_on_submit=True):
    st.subheader("➕ ปักหมุดหมายใหม่")
    n = st.text_input("ชื่อหมาย")
    fish_t = st.text_input("ปลาที่พบ")
    u_files = st.file_uploader("ถ่ายรูป", type=['jpg','jpeg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึกพิกัดปัจจุบัน"):
        urls = []
        for u_file in u_files:
            img = Image.open(u_file); img.thumbnail((800, 800))
            buf = io.BytesIO(); img.save(buf, format='JPEG')
            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{u_file.name}"
            supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
            urls.append(supabase.storage.from_("fishing_images").get_public_url(fname).replace("http://", "https://"))
        supabase.table("spots").insert({"name":n, "lat":st.session_state.user_lat, "lon":st.session_state.user_lon, "fish_type":fish_t, "image_url":",".join(urls)}).execute()
        st.success("บันทึกสำเร็จ!")
        st.rerun()

# --- 5. MAP DISPLAY (Fragment เพื่อความนิ่ง) ---
st.subheader("🗺️ แผนที่พิกัดหมายตกปลา")

@st.fragment
def render_map(display_df):
    # กำหนดจุดกึ่งกลางแผนที่ครั้งแรก
    if 'map_center' not in st.session_state:
        st.session_state.map_center = [st.session_state.user_lat, st.session_state.user_lon]
    
    m = folium.Map(location=st.session_state.map_center, zoom_start=12)
    
    # หมุดปัจจุบัน
    folium.Marker([st.session_state.user_lat, st.session_state.user_lon], 
                  icon=folium.Icon(color='red', icon='user', prefix='fa'), popup="คุณอยู่ที่นี่").add_to(m)

    for _, row in display_df.iterrows():
        weather_now, weather_fore = get_weather_forecast(row['lat'], row['lon'])
        images = [u.strip() for u in str(row["image_url"]).split(",")] if row["image_url"] else []
        
        # ปรับ HTML ให้รูปภาพโหลดได้แน่นอนโดยใช้โครงสร้างที่เรียบง่ายขึ้น
        img_html = ""
        if images:
            if len(images) > 1:
                # Carousel แบบ Simple ที่สุด (Inline CSS)
                img_html = f'<div style="width:100%; overflow-x:auto; white-space:nowrap; border-radius:8px;">'
                for u in images:
                    img_html += f'<img src="{u}" style="height:150px; margin-right:5px; border-radius:5px;">'
                img_html += '</div><p style="font-size:10px; color:gray;">เลื่อนนิ้วไปทางซ้ายเพื่อดูรูปเพิ่มเติม ⮕</p>'
            else:
                img_html = f'<img src="{images[0]}" style="width:100%; border-radius:8px;">'

        popup_html = f"""
<div style='font-family:sans-serif; width:220px;'>
    {img_html}
    <h4 style='margin:10px 0 5px 0;'>{row['name']}</h4>
    <b>🐟 ปลา:</b> {row['fish_type']}<br>
    <b>🌡️ อากาศ:</b> {weather_now}<br>
    {weather_fore}
    <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
        <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; font-weight:bold;'>🚀 นำทางด้วย Google Maps</button>
    </a>
</div>
"""
        folium.Marker([row['lat'], row['lon']], 
                      popup=folium.Popup(popup_html, max_width=300), 
                      icon=folium.Icon(color='green', icon='fish', prefix='fa')).add_to(m)

    st_folium(m, width="100%", height=550, key="main_map")

# กรองข้อมูล
df_filtered = all_data.copy()
if f_fish:
    df_filtered = df_filtered[df_filtered['fish_type'].apply(lambda x: any(i in str(x) for i in f_fish))]

render_map(df_filtered)
