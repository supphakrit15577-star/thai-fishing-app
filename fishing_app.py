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
    """ดึงอากาศปัจจุบัน + พยากรณ์ 3 วัน"""
    try:
        # อากาศตอนนี้
        url_now = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(url_now).json()
        now_txt = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        
        # พยากรณ์ล่วงหน้า
        url_fore = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        f = requests.get(url_fore).json()
        fore_html = "<hr style='margin:5px 0;'><small><b>📅 พยากรณ์ 3 วัน:</b><br>"
        for i in [8, 16, 24]: # ดึงทุกๆ 24 ชม.
            day = f['list'][i]
            dt = datetime.fromtimestamp(day['dt']).strftime('%d/%m')
            fore_html += f"• {dt}: {day['main']['temp']:.0f}°C, {day['weather'][0]['description']}<br>"
        fore_html += "</small>"
        return now_txt, fore_html
    except: return "ไม่มีข้อมูล", ""

# --- 3. GPS LOGIC (ป้องกันแมพเด้ง) ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide")

if 'user_lat' not in st.session_state:
    st.session_state.user_lat = 13.7563
    st.session_state.user_lon = 100.5018

# ใช้ JS ดึงพิกัดแบบต่อเนื่องเก็บเข้าตัวแปรแฝง
raw_loc = streamlit_js_eval(js_expressions="new Promise(r => navigator.geolocation.getCurrentPosition(p => r(p.coords)))", key='gps_sync_v8')

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")

if st.sidebar.button("🎯 อัปเดตตำแหน่งปัจจุบัน"):
    if raw_loc:
        st.session_state.user_lat = raw_loc['latitude']
        st.session_state.user_lon = raw_loc['longitude']
        st.session_state.map_center = [raw_loc['latitude'], raw_loc['longitude']]
        st.success("อัปเดตตำแหน่งจริงแล้ว!")
        st.rerun()
    else:
        st.error("รอสัญญาณ GPS สักครู่แล้วกดใหม่...")

all_data = load_spots()

with st.sidebar.form("add_form", clear_on_submit=True):
    st.subheader("➕ ปักหมุดหมายใหม่")
    n = st.text_input("ชื่อหมาย")
    fish_t = st.text_input("ปลาที่พบ")
    u_files = st.file_uploader("เลือกรูปภาพ", type=['jpg','jpeg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึกพิกัดนี้"):
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
            "name": n, "lat": st.session_state.user_lat, 
            "lon": st.session_state.user_lon, "fish_type": fish_t, 
            "image_url": ",".join(urls)
        }).execute()
        st.success("บันทึกเรียบร้อย!")
        st.rerun()

# --- 5. MAIN UI & MAP ---
st.subheader("🗺️ แผนที่พิกัดหมายตกปลาทั่วไทย")
st.info(f"📍 ตำแหน่งของคุณตอนนี้: {st.session_state.user_lat:.5f}, {st.session_state.user_lon:.5f}")

@st.fragment
def render_map(df):
    # กำหนดจุดกึ่งกลางแผนที่
    center = st.session_state.get('map_center', [st.session_state.user_lat, st.session_state.user_lon])
    m = folium.Map(location=center, zoom_start=12)
    
    # หมุดปัจจุบัน (สีแดง)
    folium.Marker([st.session_state.user_lat, st.session_state.user_lon], 
                  icon=folium.Icon(color='red', icon='user', prefix='fa'), popup="คุณอยู่ที่นี่").add_to(m)

    for _, row in df.iterrows():
        weather_now, weather_fore = get_weather_forecast(row['lat'], row['lon'])
        water = get_real_water_level(row['name'])
        images = [u.strip() for u in str(row["image_url"]).split(",")] if row["image_url"] else []
        
        # ส่วนแสดงรูปภาพ (Scrollable)
        img_html = ""
        if images:
            img_html = '<div style="display: flex; overflow-x: auto; gap: 5px; padding: 5px; width: 220px; border-radius: 8px; background: #f0f0f0;">'
            for u in images:
                img_html += f'<img src="{u}" style="height: 140px; border-radius: 5px; flex-shrink: 0;">'
            img_html += '</div>'
            if len(images) > 1:
                img_html += '<p style="font-size: 10px; color: #666; margin: 2px 0;">⮕ เลื่อนขวาดูรูปเพิ่ม</p>'

        popup_content = f"""
        <div style='font-family: sans-serif; width: 220px;'>
            {img_html}
            <h4 style='margin: 8px 0 2px 0; color: #1a73e8;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>🌡️ ตอนนี้:</b> {weather_now}<br>
            <b>💧 ระดับน้ำ:</b> {water}
            {weather_fore}
            <hr style='margin: 5px 0;'>
            <a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; cursor:pointer; font-weight:bold;'>🚀 นำทาง (Google Maps)</button>
            </a>
        </div>
        """
        folium.Marker([row['lat'], row['lon']], 
                      popup=folium.Popup(popup_content, max_width=250), 
                      icon=folium.Icon(color='green', icon='fish', prefix='fa')).add_to(m)

    st_folium(m, width="100%", height=550, key="fishing_map_v8")

render_map(all_data)

st.subheader("📋 รายชื่อพิกัดทั้งหมด")
st.dataframe(all_data[['name', 'fish_type']], use_container_width=True, hide_index=True)
