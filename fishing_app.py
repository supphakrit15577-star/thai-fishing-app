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
        if not dam_name:
            return "ไม่มีข้อมูลอ่างเก็บน้ำ"
        url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/get_dam_daily"
        res = requests.get(url, timeout=5).json()
        if 'data' in res and 'dam' in res['data']:
            for dam in res['data']['dam']:
                if 'dam_name' in dam and 'th' in dam['dam_name'] and dam_name in dam['dam_name']['th']:
                    storage = dam.get('dam_storage_percent', 'N/A')
                    return f"น้ำ {storage}% ({dam['dam_name']['th']})"
        return "ไม่มีข้อมูลอ่างเก็บน้ำ"
    except: return "เชื่อมต่อข้อมูลน้ำไม่ได้"

@st.cache_data(ttl=1800)  # จำพยากรณ์อากาศ 30 นาที
def get_full_weather(lat, lon):
    try:
        # 1. อากาศตอนนี้
        now_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        c = requests.get(now_url, timeout=5).json()
        if 'main' in c and 'weather' in c and len(c['weather']) > 0:
            now_txt = f"{c['main']['temp']}°C, {c['weather'][0]['description']}"
        else:
            now_txt = "ไม่มีข้อมูล"
        
        # 2. พยากรณ์ล่วงหน้า (ดึงราย 3 ชม. มาคัดเอาวันละจุด)
        fore_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=th"
        f = requests.get(fore_url, timeout=5).json()
        fore_list = []
        # คัดเอาข้อมูลทุกๆ 24 ชม. (index 8, 16, 24)
        if 'list' in f and len(f['list']) > 0:
            for i in [8, 16, 24]:
                if i < len(f['list']):
                    day = f['list'][i]
                    if 'dt' in day and 'main' in day and 'weather' in day and len(day['weather']) > 0:
                        dt = datetime.fromtimestamp(day['dt']).strftime('%d/%m')
                        fore_list.append(f"• {dt}: {day['main']['temp']:.0f}°C, {day['weather'][0]['description']}")
        
        fore_html = "<br>".join(fore_list) if fore_list else "ไม่มีข้อมูลล่วงหน้า"
        return now_txt, fore_html
    except: return "ไม่มีข้อมูล", "ไม่มีข้อมูลล่วงหน้า"

@st.cache_data(ttl=600)
def load_spots():
    try:
        res = supabase.table("spots").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url', 'description'])

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
    description = st.text_input ("รายละเอียด")
    files = st.file_uploader("รูปภาพ", type=['jpg','png'], accept_multiple_files=True)
    if st.form_submit_button("บันทึกพิกัดนี้"):
        if gps_raw:
            try:
                urls = []
                if files:
                    for f in files:
                        try:
                            img = Image.open(f).convert("RGB")
                            img.thumbnail((800, 800))
                            buf = io.BytesIO()
                            img.save(buf, format='JPEG')
                            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{f.name}"
                            supabase.storage.from_("fishing_images").upload(fname, buf.getvalue())
                            urls.append(supabase.storage.from_("fishing_images").get_public_url(fname).replace("http://", "https://"))
                        except Exception as e:
                            st.warning(f"ไม่สามารถอัปโหลดรูป {f.name}: {str(e)}")
                
                supabase.table("spots").insert({
                    "name": name, "lat": gps_raw['lat'], "lon": gps_raw['lon'], "description": description or "",
                    "fish_type": fish, "image_url": ",".join(urls) if urls else ""
                }).execute()
                st.success("บันทึกสำเร็จ!")
                st.rerun()
            except Exception as e:
                st.error(f"เกิดข้อผิดพลาด: {str(e)}")
        else:
            st.warning("กรุณาอนุญาตให้เข้าถึงตำแหน่ง GPS")

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
        images = []
        if "image_url" in row and row["image_url"]:
            try:
                images = [u.strip() for u in str(row["image_url"]).split(",") if u.strip()]
            except:
                images = []
        img_html = ""
        if images:
            img_html = '<div style="display: flex; overflow-x: auto; gap: 5px; width: 220px; background:#f0f0f0; border-radius:8px; padding:5px;">'
            for u in images:
                img_html += f'<img src="{u}" style="height: 120px; border-radius: 5px; flex-shrink: 0;">'
            img_html += '</div>'

        name = row.get('name', 'ไม่มีชื่อ')
        fish_type = row.get('fish_type', 'ไม่ระบุ')
        description = row.get('description', 'ไม่มีรายละเอียด')
        
        popup_html = f"""
        <div style='width: 220px; font-family: sans-serif;'>
            {img_html}
            <h4 style='margin: 8px 0 2px 0; color: #1a73e8;'>{name}</h4>
            <b>🐟 ปลา:</b> {fish_type}<br>
            <b>รายละเอียด:</b> {description}<br>
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

# --- 6. SPOT MANAGEMENT ---
st.divider()
st.subheader("📋 จัดการจุดตกปลา")

# Filter and search
col1, col2, col3 = st.columns(3)
with col1:
    search_term = st.text_input("🔍 ค้นหาจุดตกปลา", placeholder="ชื่อจุด, ปลา, หรือรายละเอียด")
with col2:
    fish_filter = st.selectbox("🐟 กรองตามปลา", ["ทั้งหมด"] + sorted(all_data['fish_type'].dropna().unique().tolist()) if not all_data.empty else ["ทั้งหมด"])
with col3:
    sort_option = st.selectbox("📊 เรียงตาม", ["ชื่อ (A-Z)", "ชื่อ (Z-A)", "วันที่เพิ่มล่าสุด"])

# Filter data
filtered_data = all_data.copy()
if not all_data.empty:
    if search_term:
        mask = (
            filtered_data['name'].str.contains(search_term, case=False, na=False) |
            filtered_data['fish_type'].str.contains(search_term, case=False, na=False) |
            filtered_data['description'].str.contains(search_term, case=False, na=False)
        )
        filtered_data = filtered_data[mask]
    
    if fish_filter != "ทั้งหมด":
        filtered_data = filtered_data[filtered_data['fish_type'] == fish_filter]
    
    # Sort data
    if sort_option == "ชื่อ (A-Z)":
        filtered_data = filtered_data.sort_values('name')
    elif sort_option == "ชื่อ (Z-A)":
        filtered_data = filtered_data.sort_values('name', ascending=False)

# Display filtered spots
if not filtered_data.empty:
    st.write(f"**พบ {len(filtered_data)} จุดตกปลา**")
    
    # Display spots in expandable sections
    for i, (idx, row) in enumerate(filtered_data.iterrows()):
        spot_id = row.get('id', idx) if 'id' in row else f"{row.get('lat', '')}_{row.get('lon', '')}_{row.get('name', '')}"
        with st.expander(f"🎣 {row.get('name', 'ไม่มีชื่อ')} - {row.get('fish_type', 'ไม่ระบุ')}"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.write(f"**พิกัด:** {row.get('lat', 'N/A')}, {row.get('lon', 'N/A')}")
                st.write(f"**ปลาที่พบ:** {row.get('fish_type', 'ไม่ระบุ')}")
                st.write(f"**รายละเอียด:** {row.get('description', 'ไม่มีรายละเอียด')}")
                
                # Display images if available
                images = []
                if "image_url" in row and row["image_url"]:
                    try:
                        images = [u.strip() for u in str(row["image_url"]).split(",") if u.strip()]
                    except:
                        images = []
                
                if images:
                    st.write("**รูปภาพ:**")
                    cols = st.columns(min(len(images), 3))
                    for j, img_url in enumerate(images[:3]):
                        with cols[j % 3]:
                            st.image(img_url, use_container_width=True)
            
            with col2:
                # Action buttons
                if st.button("🗺️ เปิดในแผนที่", key=f"map_{i}_{spot_id}"):
                    st.session_state.v_lat = row['lat']
                    st.session_state.v_lon = row['lon']
                    st.rerun()
                
                # Weather info
                try:
                    weather_now, weather_fore = get_full_weather(row['lat'], row['lon'])
                    st.write(f"**🌡️ อากาศ:** {weather_now}")
                except:
                    st.write("**🌡️ อากาศ:** ไม่มีข้อมูล")
                
                # Water level info
                water_info = get_water_info(row.get('name', ''))
                st.write(f"**💧 น้ำ:** {water_info}")
else:
    st.info("ไม่พบจุดตกปลาที่ตรงกับเงื่อนไขการค้นหา")

# --- 7. STATISTICS ---
st.divider()
st.subheader("📊 สถิติ")

if not all_data.empty:
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("🎣 จุดตกปลาทั้งหมด", len(all_data))
    
    with col2:
        unique_fish = all_data['fish_type'].dropna().nunique()
        st.metric("🐟 ชนิดปลา", unique_fish)
    
    with col3:
        total_images = sum(
            len(str(row.get('image_url', '')).split(',')) 
            if row.get('image_url') else 0 
            for _, row in all_data.iterrows()
        )
        st.metric("📷 รูปภาพทั้งหมด", total_images)
    
    with col4:
        spots_with_images = sum(
            1 for _, row in all_data.iterrows() 
            if row.get('image_url') and str(row.get('image_url', '')).strip()
        )
        st.metric("📸 จุดที่มีรูปภาพ", spots_with_images)
    
    # Fish type distribution
    if 'fish_type' in all_data.columns:
        st.write("**🐟 การกระจายชนิดปลา:**")
        fish_counts = all_data['fish_type'].value_counts()
        st.bar_chart(fish_counts)
    
    # Map coverage
    if 'lat' in all_data.columns and 'lon' in all_data.columns:
        st.write("**📍 พื้นที่ครอบคลุม:**")
        try:
            min_lat, max_lat = all_data['lat'].min(), all_data['lat'].max()
            min_lon, max_lon = all_data['lon'].min(), all_data['lon'].max()
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2
            
            st.write(f"**ศูนย์กลาง:** {center_lat:.4f}, {center_lon:.4f}")
            st.write(f"**ช่วงละติจูด:** {min_lat:.4f} ถึง {max_lat:.4f}")
            st.write(f"**ช่วงลองจิจูด:** {min_lon:.4f} ถึง {max_lon:.4f}")
        except:
            st.write("ไม่สามารถคำนวณพื้นที่ครอบคลุมได้")

# --- 8. EXPORT FUNCTIONALITY ---
st.divider()
st.subheader("💾 ส่งออกข้อมูล")

col1, col2 = st.columns(2)

with col1:
    if st.button("📥 ดาวน์โหลด CSV"):
        if not all_data.empty:
            csv = all_data.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="⬇️ ดาวน์โหลดไฟล์ CSV",
                data=csv,
                file_name=f"fishing_spots_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("ไม่มีข้อมูลให้ส่งออก")

with col2:
    if st.button("📥 ดาวน์โหลด JSON"):
        if not all_data.empty:
            json_data = all_data.to_json(orient='records', force_ascii=False, indent=2)
            st.download_button(
                label="⬇️ ดาวน์โหลดไฟล์ JSON",
                data=json_data.encode('utf-8'),
                file_name=f"fishing_spots_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )
        else:
            st.warning("ไม่มีข้อมูลให้ส่งออก")

# --- 9. FOOTER ---
st.divider()
st.markdown("""
<div style='text-align: center; color: #666; padding: 20px;'>
    <p>🎣 <strong>Thai Fishing Pro</strong> - แอปพลิเคชันสำหรับนักตกปลา</p>
    <p>สร้างด้วย Streamlit, Folium, และ Supabase</p>
</div>
""", unsafe_allow_html=True)
