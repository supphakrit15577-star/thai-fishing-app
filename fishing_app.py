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

# --- 1. CONFIGURATION & CONNECTION ---
# แนะนำให้ใส่ใน Streamlit Secrets เมื่อ Deploy จริง
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://ajurexheolscvnkycaqo.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqdXJleGhlb2xzY3Zua3ljYXFvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgyMDk2OTYsImV4cCI6MjA4Mzc4NTY5Nn0.i6akECleLwulyUDiWHthrEaFj-jYk6lNHuFq9T0n_ts")
WEATHER_API_KEY = "2e323a6a31b3c5ffae1efed13dad633b"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("กรุณาตั้งค่า Supabase URL และ Key ในโค้ดหรือ Secrets ก่อนใช้งาน")

# --- 2. DATA FUNCTIONS ---
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"Error loading data: {e}") # แสดงข้อผิดพลาดถ้าดึงไม่ได้
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'description', 'image_url'])

def get_real_water_level(dam_name):
    try:
        url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/get_dam_daily"
        res = requests.get(url, timeout=5).json()
        for dam in res['data']['dam']:
            if dam_name in dam['dam_name']['th']:
                return f"น้ำ {dam['dam_storage_percent']}% ({dam['dam_date']})"
        return "ไม่พบข้อมูลเขื่อน"
    except: return "เชื่อมต่อข้อมูลน้ำไม่ได้"

def get_weather_info(lat, lon):
    try:
        # อากาศปัจจุบัน
        curr_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(curr_url).json()
        # พยากรณ์
        fore_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        f = requests.get(fore_url).json()
        
        forecast_txt = ""
        for i in [8, 16, 24]:
            item = f['list'][i]
            forecast_txt += f"<br>• {item['dt_txt'][:10]}: {item['main']['temp']}°C {item['weather'][0]['description']}"
            
        return f"{c['main']['temp']}°C, {c['weather'][0]['description']}", forecast_txt
    except: return "ไม่มีข้อมูล", ""

# --- 3. UI SETUP ---
st.set_page_config(page_title="Thai Fishing Pro App", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    /* แทนที่จะซ่อน header ทั้งหมด ให้ซ่อนแค่ความสูงบางส่วน หรือข้ามไปก่อน */
    /* header {visibility: hidden;} */ 
    </style>
    """, unsafe_allow_html=True)

st.title("🎣 แผนที่นักตกปลาไทย (Pro)")

# ดึง GPS จากเครื่อง
user_loc = streamlit_js_eval(
    js_expressions="""
    new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject('Geolocation not supported');
        }
        // ใช้ watchPosition แทน getCurrentPosition เพื่อติดตามการเคลื่อนที่
        navigator.geolocation.watchPosition(
            (pos) => { 
                resolve({
                    latitude: pos.coords.latitude,
                    longitude: pos.coords.longitude,
                    accuracy: pos.coords.accuracy
                }); 
            },
            (err) => { reject(err); },
            { 
                enableHighAccuracy: true,  // ใช้ GPS จริงเพื่อให้แม่นยำที่สุด
                timeout: 10000,            // รอสัญญาณ 10 วินาที
                maximumAge: 0              // ไม่ใช้ข้อมูลเก่าจาก Cache
            }
        );
    })
    """, 
    key='watch_location'
)

curr_lat, curr_lon = (user_loc['latitude'], user_loc['longitude']) if user_loc else (13.7563, 100.5018)
st.sidebar.caption(f"🎯 ความแม่นยำ GPS: {user_loc['accuracy']:.1f} เมตร")

#Position Check
if 'map_center' not in st.session_state:
    st.session_state.map_center = [curr_lat, curr_lon]

if user_loc and 'first_load' not in st.session_state:
    st.session_state.map_center = [curr_lat, curr_lon]
    st.session_state.first_load = True
    
# Sidebar: กรองข้อมูล
all_data = load_spots()
st.sidebar.header("🔍 คัดกรอง")
f_fish = st.sidebar.multiselect("เลือกปลา", list(set(",".join(all_data['fish_type'].astype(str)).split(","))))
f_img = st.sidebar.checkbox("มีรูปเท่านั้น")

if st.sidebar.button("📍 กลับมาที่ตำแหน่งปัจจุบัน"):
    st.session_state.map_center = [curr_lat, curr_lon]
    st.rerun()


# Sidebar: เพิ่มจุดใหม่
st.sidebar.divider()
with st.sidebar.form("add_spot_form", clear_on_submit=True):
    st.subheader("➕ เพิ่มหมายใหม่")
    n = st.text_input("ชื่อสถานที่ (เขื่อน/หมาย)")
    fish = st.text_input("ปลาที่พบ (คั่นด้วยจุลภาค)")
    desc = st.text_area("เทคนิค/คำอธิบาย")
    u_file = st.file_uploader("รูปปลา", type=['jpg','png','jpeg'])
    
    if st.form_submit_button("บันทึกหมายตกปลา"):
        if curr_lat == 13.7563 and curr_lon == 100.5018:
            st.error("❌ ยังดึงพิกัดจาก GPS ไม่สำเร็จ กรุณารอสักครู่แล้วลองใหม่")
        else:
            img_url = ""
            if u_file:
                # ย่อขนาดรูปก่อนอัปโหลด
                image = Image.open(u_file)
                image.thumbnail((800, 800))
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format='JPEG')
            
                f_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                supabase.storage.from_("fishing_images").upload(f_name, img_byte_arr.getvalue())
                img_url = supabase.storage.from_("fishing_images").get_public_url(f_name)
            
            supabase.table("spots").insert({"name":n, "lat":curr_lat, "lon":curr_lon, "fish_type":fish, "description":desc, "image_url":img_url}).execute()
            st.success("บันทึกแล้ว!")
            st.rerun()

# กรอง Data
df = all_data.copy()
if f_fish: df = df[df['fish_type'].apply(lambda x: any(i in str(x) for i in f_fish))]
if f_img: df = df[df['image_url'] != ""]

# --- 4. MAP DISPLAY ---
col1, col2 = st.columns([3, 1])
with col1:
    m = folium.Map(location=st.session_state.map_center, zoom_start=12)
    folium.Marker([curr_lat, curr_lon], popup="คุณอยู่ที่นี่", icon=folium.Icon(color='red')).add_to(m)

    for _, row in df.iterrows():
        weather_now, weather_fore = get_weather_info(row['lat'], row['lon'])
        water = get_real_water_level(row['name'])
        nav_url = f"https://www.google.com/maps/dir/?api=1&origin={curr_lat},{curr_lon}&destination={row['lat']},{row['lon']}&travelmode=driving"
        
        img_tag = f'<img src="{row["image_url"]}" width="100%" style="border-radius:10px;">' if row['image_url'] else ""
        
        popup_html = f"""
        <div style='font-family:sans-serif; min-width:220px;'>
            {img_tag}
            <h4 style='margin-bottom:5px;'>{row['name']}</h4>
            <b>🐟 ปลา:</b> {row['fish_type']}<br>
            <b>💧 ระดับน้ำ:</b> {water}<br>
            <div style='background:#f9f9f9; padding:5px; border-radius:5px;'>
                <b>🌤️ ตอนนี้:</b> {weather_now}<br>
                <small><b>📅 พยากรณ์:</b> {weather_fore}</small>
            </div>
            <a href="{nav_url}" target="_blank">
                <button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px;'>🚀 นำทาง (Google Maps)</button>
            </a>
        </div>
        """
        folium.Marker([row['lat'], row['lon']], popup=folium.Popup(popup_html, max_width=250), icon=folium.Icon(color='green', icon='fish', prefix='fa')).add_to(m)

    map_data = st_folium(m, width=900, height=600, key="main_map")
    
    #Movement checking
    if map_data and map_data.get('center'):
        new_lat = map_data['center']['lat']
        new_lng = map_data['center']['lng']
        # บันทึกค่าไว้เพื่อที่ Rerun ครั้งหน้า แผนที่จะยังอยู่ที่เดิม
        st.session_state.map_center = [new_lat, new_lng]

with col2:
    st.subheader("📋 รายการหมาย")
    st.write(df[['name', 'fish_type']])
