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

# --- 3. UI & GPS SETUP ---
st.set_page_config(page_title="Thai Fishing Pro", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>footer {visibility: hidden;} .stApp header {z-index: 1;}</style>""", unsafe_allow_html=True)

user_loc = streamlit_js_eval(
    js_expressions="""
    new Promise((resolve, reject) => {
        navigator.geolocation.watchPosition(
            (pos) => { resolve({lat: pos.coords.latitude, lon: pos.coords.longitude, acc: pos.coords.accuracy}); },
            (err) => { reject(err); },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    })
    """, key='gps_track_v6'
)

curr_lat, curr_lon = (user_loc['lat'], user_loc['lon']) if user_loc else (13.7563, 100.5018)

if 'map_center' not in st.session_state:
    st.session_state.map_center = [curr_lat, curr_lon]
if 'map_zoom' not in st.session_state:
    st.session_state.map_zoom = 12

# --- 4. SIDEBAR ---
st.sidebar.title("🎣 Fishing Pro")
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
    u_files = st.file_uploader("ถ่ายรูป (เลือกได้หลายรูป)", type=['jpg','jpeg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึกพิกัดปัจจุบัน"):
        if curr_lat == 13.7563:
            st.error("รอสัญญาณ GPS สักครู่...")
        else:
            urls = []
            for u_file in u_files:
                img = Image.open(u_file); img.thumbnail((800, 800))
                buf = io.BytesIO(); img.save(buf, format='JPEG')
                fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{u_file.name}"
                supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
                urls.append(supabase.storage.from_("fishing_images").get_public_url(fname))
            
            img_url_str = ",".join(urls)
            supabase.table("spots").insert({"name":n, "lat":curr_lat, "lon":curr_lon, "fish_type":fish_type, "image_url":img_url_str}).execute()
            st.success(f"บันทึกสำเร็จ {len(urls)} รูป!")
            st.rerun()

# --- 5. MAP DISPLAY ---
df = all_data.copy()
if f_fish: df = df[df['fish_type'].apply(lambda x: any(i in str(x) for i in f_fish))]
if f_img: df = df[df['image_url'] != ""]

st.subheader("🗺️ แผนที่พิกัดหมายตกปลาทั่วไทย")
st.info(f"ตำแหน่งปัจจุบัน: {curr_lat:.4f}, {curr_lon:.4f}")

@st.fragment
def render_stable_map(display_df, u_lat, u_lon):
    m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    folium.Marker([u_lat, u_lon], icon=folium.Icon(color='red', icon='user', prefix='fa'), popup="คุณอยู่ที่นี่").add_to(m)

    for _, row in display_df.iterrows():
        weather_now, weather_fore = get_weather_forecast(row['lat'], row['lon'])
        water = get_real_water_level(row['name'])
        
        # จัดการรูปภาพ (รองรับหลายรูป)
        images = str(row["image_url"]).split(",") if row["image_url"] else []
        img_html = ""
        if len(images) > 1:
            slides = "".join([f'<div class="mySlides fade"><img src="{u.strip()}" style="width:100%; border-radius:8px; display:block;"></div>' for u in images])
            img_html = f'<div class="slideshow-container">{slides}<a class="prev" onclick="plusSlides(-1, this)">❮</a><a class="next" onclick="plusSlides(1, this)">❯</a></div>'
        elif len(images) == 1:
            img_html = f'<img src="{images[0].strip()}" width="100%" style="border-radius:8px;">'

        # CSS & JS (ต้องเขียนแบบชิดซ้ายเพื่อไม่ให้ติดช่องว่าง)
        css = "<style>.slideshow-container{position:relative;}.mySlides{display:none;}.prev,.next{cursor:pointer;position:absolute;top:50%;width:auto;padding:10px;margin-top:-22px;color:white;font-weight:bold;font-size:18px;background:rgba(0,0,0,0.5);border-radius:3px;}.next{right:0;}.fade{animation:fade 1.5s;}@keyframes fade{from{opacity:.4}to{opacity:1}}</style>"
        js = '<script>var slideIndex=1; function plusSlides(n,el){showSlides(slideIndex+=n,el.parentElement);} function showSlides(n,container){var i; var slides=container.getElementsByClassName("mySlides"); if(n>slides.length){slideIndex=1} if(n<1){slideIndex=slides.length} for(i=0;i<slides.length;i++){slides[i].style.display="none";} slides[slideIndex-1].style.display="block";} setTimeout(function(){var conts=document.getElementsByClassName("slideshow-container"); for(var j=0;j<conts.length;j++){var s=conts[j].getElementsByClassName("mySlides"); if(s.length>0)s[0].style.display="block";}},100);</script>'
        
        popup_html = f"""
{css}
<div style='font-family:sans-serif; min-width:220px;'>
{img_html}
<h4 style='margin:5px 0;'>{row['name']}</h4>
<b>🐟 ปลา:</b> {row['fish_type']}<br>
<b>🌡️ ตอนนี้:</b> {weather_now}<br>
<b>💧 น้ำ:</b> {water}{weather_fore}
<a href="https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" target="_blank">
<button style='width:100%; background:#4285F4; color:white; border:none; padding:10px; border-radius:5px; margin-top:10px; cursor:pointer;'>🚀 นำทาง</button>
</a>
{js if len(images) > 1 else ""}
</div>
"""
        folium.Marker([row['lat'], row['lon']], popup=folium.Popup(popup_html, max_width=300), icon=folium.Icon(color='green', icon='fish', prefix='fa')).add_to(m)

    st_folium(m, width="100%", height=600, key="stable_map_v6")

render_stable_map(df, curr_lat, curr_lon)

st.subheader("📋 รายการหมายทั้งหมด")
st.dataframe(df[['name', 'fish_type']], use_container_width=True, hide_index=True)
