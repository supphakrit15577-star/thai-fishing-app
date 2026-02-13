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
import re
import traceback
import os
import math
import time
import httpx

def run_with_retry(operation, description="Database operation", max_retries=3, delay=1):
    """
    Utility function to retry database operations on transient failures.
    """
    for i in range(max_retries):
        try:
            return operation().execute()
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as e:
            if i == max_retries - 1:
                st.error(f"❌ {description} ล้มเหลวหลังจากพยายาม {max_retries} ครั้ง: {str(e)}")
                raise e
            time.sleep(delay * (i + 1)) # Exponential-ish backoff
        except Exception as e:
            # For other errors, we might still want to retry if it's a connection issue disguised
            if "disconnect" in str(e).lower() or "timeout" in str(e).lower():
                if i == max_retries - 1: raise e
                time.sleep(delay * (i + 1))
            else:
                raise e

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) in meters.
    """
    # Convert decimal degrees to radians 
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # Haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371000 # Radius of earth in meters
    return c * r

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
SUPABASE_SERVICE_KEY = st.secrets["SUPABASE_SERVICE_KEY"]
WEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]

try:
    # เริ่มต้น Supabase Clients
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    supabase_storage = supabase
    supabase_db = supabase  # เริ่มต้นด้วย anon key เสมอ
    storage_configured = False
    db_configured = False

    if SUPABASE_SERVICE_KEY:
        try:
            supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            supabase_storage = supabase_admin 
            supabase_db = supabase_admin
            storage_configured = True
            db_configured = True
        except Exception as e:
            st.error(f"⚠️ ไม่สามารถเชื่อมต่อด้วย Service Key ได้ (จะใช้ Anon Key แทน): {str(e)}")
except Exception as e:
    st.error(f"เชื่อมต่อ Supabase ไม่สำเร็จ: {str(e)}")
    supabase = None
    supabase_storage = None
    supabase_db = None
    storage_configured = False
    db_configured = False

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
        # ใช้ supabase_db (ซึ่งอาจจะถูก override เป็น admin client แล้ว)
        res = run_with_retry(lambda: supabase_db.table("spots").select("*"), "ดึงข้อมูลจุดตกปลา")
        return pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"ไม่สามารถโหลดข้อมูลได้: {str(e)}")
        return pd.DataFrame(columns=['name', 'lat', 'lon', 'fish_type', 'image_url', 'description'])

# --- ฟังก์ชันจัดการข้อมูล (หัวใจหลัก) ---
def save_fishing_spot(name, fish_type, description, images_urls, lat, lon):
    if supabase_db is None:
        st.error("ไม่สามารถเชื่อมต่อฐานข้อมูลได้")
        return False

    try:
        # 1. ค้นหาจุดที่มีอยู่ทั้งหมด
        res = run_with_retry(lambda: supabase_db.table("spots").select("*"), "ค้นหาจุดเดิม")
        df_existing = pd.DataFrame(res.data)
    
        match = None
        if not df_existing.empty:
            # เช็คชื่อตรงกัน หรือ พิกัดใกล้เคียงกัน (ระยะทางน้อยกว่า 100 เมตร)
            # เราจะวนลูปเช็คระยะทาง หรือใช้ logic ที่มีประสิทธิภาพกว่าถ้าข้อมูลเยอะ
            # สำหรับตอนนี้ วนลูปเช็คระยะทางใน DataFrame
            
            # กรองตามชื่อก่อนเพื่อความเร็ว
            name_match = df_existing[df_existing['name'] == name]
            if not name_match.empty:
                match = name_match
            else:
                # ถ้าชื่อไม่ตรง เช็คพิกัดใกล้เคียง (100 เมตร)
                def check_distance(row):
                    return haversine_distance(lat, lon, row['lat'], row['lon'])
                
                df_existing['distance'] = df_existing.apply(check_distance, axis=1)
                proximity_match = df_existing[df_existing['distance'] <= 100].copy() # รัศมี 100 เมตร
                if not proximity_match.empty:
                    match = proximity_match.sort_values('distance')

        if match is not None and not match.empty:
            # --- กรณีมีจุดเดิมหรือจุดใกล้เคียงอยู่แล้ว: ให้ "รวม" ข้อมูล ---
            target_row = match.iloc[0]
            
            old_fish = str(target_row.get('fish_type', ''))
            old_images = str(target_row.get('image_url', ''))
            old_desc = str(target_row.get('description', ''))

            # 1. รวมชื่อปลา (เอาที่ซ้ำออก)
            new_fish_list = [f.strip() for f in (old_fish + "," + fish_type).split(",") if f.strip()]
            updated_fish = ", ".join(sorted(list(set(new_fish_list))))
            
            # 2. รวมรูปภาพ (เอาที่ซ้ำออก)
            new_img_str = ",".join(images_urls)
            old_img_list = [u.strip() for u in old_images.split(",") if u.strip()]
            new_img_list = [u.strip() for u in new_img_str.split(",") if u.strip()]
            updated_images = ",".join(list(dict.fromkeys(old_img_list + new_img_list)))

            # 3. รวมรายละเอียด (ถ้ามีข้อมูลใหม่ ให้ต่อท้าย)
            updated_desc = old_desc
            if description and description.strip() and description.strip() not in old_desc:
                timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
                separator = "\n" + "-"*20 + "\n" if old_desc else ""
                updated_desc = f"{old_desc}{separator}[{timestamp}] {description.strip()}"

            # อัปเดตข้อมูล
            update_data = {
                "fish_type": updated_fish,
                "image_url": updated_images,
                "description": updated_desc
            }
            
            # ใช้ช่วงพิกัด (Epsilon) แทนการใช้ค่าเท่ากันเป๊ะๆ เพื่อเลี่ยงปัญหาทศนิยมคลาดเคลื่อน
            epsilon = 0.00001
            res_update = run_with_retry(
                lambda: supabase_db.table("spots").update(update_data)\
                    .eq("name", target_row['name'])\
                    .gte("lat", target_row['lat'] - epsilon)\
                    .lte("lat", target_row['lat'] + epsilon)\
                    .gte("lon", target_row['lon'] - epsilon)\
                    .lte("lon", target_row['lon'] + epsilon),
                "อัปเดตข้อมูลจุดเดิม"
            )
                
            if res_update.data:
                dist_info = f" (ห่าง {target_row['distance']:.1f} ม.)" if 'distance' in target_row else ""
                st.success(f"อัปเดตข้อมูลในจุดเดิม: {target_row['name']}{dist_info} เรียบร้อย! (มีข้อมูลในระบบแล้ว)")
                # แสดงผลข้อมูลที่อัปเดตเพื่อตรวจสอบ
                with st.expander("ดูข้อมูลที่บันทึกสำเร็จ"):
                    st.write(res_update.data[0])
                return True
            else:
                st.warning("⚠️ พบจุดเดิมในแอปแต่ไม่สามารถระบุแถวในฐานข้อมูลเพื่ออัปเดตได้ (พิกัดในเครื่องกับใน DB อาจไม่ตรงกันในระดับทศนิยม)")
                return False

        else:
            # --- กรณีเป็นจุดใหม่: ให้ "เพิ่ม" แถวใหม่ ---
            res_insert = run_with_retry(
                lambda: supabase_db.table("spots").insert({
                    "name": name, "lat": lat, "lon": lon, 
                    "fish_type": fish_type, "description": description, "image_url": ",".join(images_urls)
                }),
                "บันทึกจุดใหม่"
            )
            
            if res_insert.data:
                st.success("บันทึกจุดตกปลาใหม่เรียบร้อย!")
                with st.expander("ดูข้อมูลที่บันทึกใหม่"):
                    st.write(res_insert.data[0])
                return True
            else:
                # ในบางกรณี insert อาจสำเร็จแต่ไม่คืนค่าข้อมูล (เช่น RLS หรือ configuration)
                # เราจะให้ True ไว้ก่อนถ้าไม่มี Exception
                st.info("ส่งข้อมูลไปที่เซิร์ฟเวอร์แล้ว (รอการตรวจสอบข้อมูลในอาทิตย์ถัดไปหากยังไม่ปรากฏ)")
                return True
    except Exception as e:
        st.error(f"Database Error: {str(e)}")
        st.code(traceback.format_exc())
        return False

# --- ฟังก์ชันนับสถิติปลา ---
def get_spot_fish_stats(fish_string):
    if not fish_string:
        return "ยังไม่มีข้อมูลปลา"
    
    # แยกรายชื่อปลาและนับจำนวน
    fish_list = [f.strip() for f in str(fish_string).split(",") if f.strip()]
    if not fish_list:
        return "ยังไม่มีข้อมูลปลา"
    
    # นับความถี่
    from collections import Counter
    counts = Counter(fish_list)
    
    # สร้างข้อความแสดงสถิติแบบบรรทัด
    stat_text = "<br>".join([f"• {fish}: {count} ครั้ง" for fish, count in counts.items()])
    return stat_text

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

# แสดงตำแหน่งปัจจุบัน
st.sidebar.info(f"📍 ตำแหน่งปัจจุบัน:\n{st.session_state.v_lat:.4f}, {st.session_state.v_lon:.4f}")

if st.sidebar.button("🎯 อัปเดตพิกัดปัจจุบัน"):
    if gps_raw and 'lat' in gps_raw and 'lon' in gps_raw:
        st.session_state.v_lat = gps_raw['lat']
        st.session_state.v_lon = gps_raw['lon']
        st.success(f"อัปเดตตำแหน่ง: {gps_raw['lat']:.4f}, {gps_raw['lon']:.4f}")
        st.rerun()
    else:
        st.warning("ไม่สามารถดึงตำแหน่ง GPS ได้ กรุณาอนุญาตให้เข้าถึงตำแหน่งในเบราว์เซอร์ หรือใช้พิกัดปัจจุบัน")

# ตัวเลือกป้อนพิกัดเอง
with st.sidebar.expander("📍 ป้อนพิกัดเอง"):
    manual_lat = st.number_input("ละติจูด (Latitude)", value=st.session_state.v_lat, format="%.6f")
    manual_lon = st.number_input("ลองจิจูด (Longitude)", value=st.session_state.v_lon, format="%.6f")
    if st.button("✅ ใช้พิกัดนี้"):
        st.session_state.v_lat = manual_lat
        st.session_state.v_lon = manual_lon
        st.success(f"ตั้งค่าพิกัด: {manual_lat:.4f}, {manual_lon:.4f}")
        st.rerun()

all_data = load_spots()

with st.sidebar.form("add_spot_form", clear_on_submit=True):
    st.subheader("➕ เพิ่มข้อมูลการตกปลา")
    
    # แสดงพิกัดที่จะใช้บันทึก
    gps_status = "✅ GPS" if (gps_raw and 'lat' in gps_raw) else "📍 พิกัดปัจจุบัน"
    st.caption(f"{gps_status}: {st.session_state.v_lat:.4f}, {st.session_state.v_lon:.4f}")
    
    name = st.text_input("ชื่อหมาย (ใส่ชื่อเขื่อน/อ่างเก็บน้ำเพื่อดึงระดับน้ำ)", key="spot_name")
    fish = st.text_input("ปลาที่พบ", key="spot_fish")
    description = st.text_input("รายละเอียด", key="spot_desc")
    files = st.file_uploader("รูปภาพ", type=['jpg','png','jpeg'], accept_multiple_files=True, key="spot_images")

    if st.form_submit_button("บันทึกข้อมูล", use_container_width=True):
        # ตรวจสอบว่ามีชื่อจุดตกปลาหรือไม่
        if not name or not name.strip():
            st.error("กรุณากรอกชื่อจุดตกปลา")
        else:
            try:
                # ใช้ GPS ถ้ามี ไม่เช่นนั้นใช้ session state
                use_lat = gps_raw['lat'] if gps_raw and 'lat' in gps_raw else st.session_state.v_lat
                use_lon = gps_raw['lon'] if gps_raw and 'lon' in gps_raw else st.session_state.v_lon
                
                urls = []
                if files:
                    # ตรวจสอบว่า supabase_storage พร้อมใช้งานหรือไม่
                    if 'supabase_storage' not in globals() or supabase_storage is None:
                        st.error("ไม่สามารถเชื่อมต่อ Supabase Storage ได้")
                        st.warning("จะบันทึกข้อมูลโดยไม่มีรูปภาพ")
                    elif not storage_configured:
                        st.warning("⚠️ ยังไม่ได้ตั้งค่า SUPABASE_SERVICE_KEY - การอัปโหลดรูปภาพอาจล้มเหลว")
                    
                    # ตรวจสอบจำนวนไฟล์
                    total_files = len(files)
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    
                    for idx, f in enumerate(files):
                        try:
                            status_text.text(f"กำลังอัปโหลดรูป {idx + 1}/{total_files}: {f.name}")
                                
                            # ตรวจสอบขนาดไฟล์ (จำกัดที่ 10MB)
                            if f.size > 10 * 1024 * 1024:
                                st.warning(f"ไฟล์ {f.name} ใหญ่เกินไป (มากกว่า 10MB) จะถูกย่อขนาดอัตโนมัติ")
                                
                            # อ่านและประมวลผลรูปภาพ
                            img = Image.open(f).convert("RGB")
                            img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                                
                            # สร้าง buffer และบันทึกรูป
                            buf = io.BytesIO()
                            img.save(buf, format='JPEG', quality=85)
                            buf.seek(0)  # Reset buffer position
                                
                            # สร้างชื่อไฟล์ที่ปลอดภัย
                            safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', f.name)
                            timestamp = datetime.now().strftime('%Y%m%d%H%M%S_%f')
                            fname = f"{timestamp}_{safe_name}"
                                
                            # อัปโหลดไปยัง Supabase Storage (ใช้ supabase_storage ที่มีสิทธิ์ bypass RLS)
                            upload_result = supabase_storage.storage.from_("fishing_images").upload(
                                fname, 
                                buf.getvalue(),
                                file_options={"content-type": "image/jpeg", "upsert": "true"}
                            )
                                
                            # ดึง public URL
                            public_url = supabase_storage.storage.from_("fishing_images").get_public_url(fname)
                            # แปลง http เป็น https
                            if public_url.startswith("http://"):
                                public_url = public_url.replace("http://", "https://")
                                
                            urls.append(public_url)
                                
                            # อัปเดต progress
                            progress_bar.progress((idx + 1) / total_files)
                                
                        except Exception as e:
                            error_msg = str(e)
                            # ตรวจสอบว่าเป็น RLS error หรือไม่
                            if "row-level security policy" in error_msg.lower() or "unauthorized" in error_msg.lower():
                                st.error(f"❌ ไม่สามารถอัปโหลดรูป {f.name} เนื่องจาก Row Level Security (RLS)")
                                
                            else:
                                st.error(f"ไม่สามารถอัปโหลดรูป {f.name}: {error_msg}")
                            with st.expander(f"รายละเอียดข้อผิดพลาด - {f.name}"):
                                st.code(traceback.format_exc())

                    # ลบ progress bar และ status text
                    progress_bar.empty()
                    status_text.empty()
                        
                    if urls:
                        st.success(f"อัปโหลดรูปภาพ {len(urls)}/{total_files} ไฟล์สำเร็จ")
                
                
                        
            except Exception as e:
                    error_msg = str(e)
                    # ตรวจสอบว่าเป็น RLS error หรือไม่
                    if "row-level security policy" in error_msg.lower() or "42501" in error_msg:
                        st.error("❌ การบันทึกข้อมูลล้มเหลวเนื่องจาก Row Level Security (RLS)")
                       
                    else:
                        st.error(f"เกิดข้อผิดพลาด: {error_msg}")
                    with st.expander("รายละเอียดข้อผิดพลาด"):
                        st.code(traceback.format_exc())
        
        if save_fishing_spot(name, fish, description, urls, use_lat, use_lon):
            st.cache_data.clear()
            st.rerun()

# --- 5. STABLE MAP DISPLAY ---
st.subheader("🗺️ แผนที่พิกัดตกปลา")

@st.fragment
def render_fishing_map(df):
    m = folium.Map(location=[st.session_state.v_lat, st.session_state.v_lon], zoom_start=12)

    # หมุดคุณ - ใช้ GPS ถ้ามี ไม่เช่นนั้นใช้ตำแหน่งจาก session state
    user_lat = gps_raw['lat'] if gps_raw and 'lat' in gps_raw else st.session_state.v_lat
    user_lon = gps_raw['lon'] if gps_raw and 'lon' in gps_raw else st.session_state.v_lon
    folium.Marker(
        [user_lat, user_lon], 
        icon=folium.Icon(color='red', icon='user', prefix='fa'),
        tooltip="ตำแหน่งของคุณ"
    ).add_to(m)

    for _, row in df.iterrows():

        spot_stats = get_spot_fish_stats(row['fish_type'])

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
            <div style='background: #e8f0fe; padding: 8px; border-radius: 5px; margin-top: 5px;'>
                <b>📊 สถิติการเจอปลาที่นี่:</b><br>
                <small>{spot_stats}</small>
            </div>
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
st.button("🔄 โหลดข้อมูลใหม่ (Clear Cache)", on_click=st.cache_data.clear)

# --- 5.5 DATA PREVIEW (DEBUG) ---
with st.expander("🔍 ตรวจสอบข้อมูลดิบจากฐานข้อมูล (Debug)"):
    if not all_data.empty:
        st.write("ข้อมูลที่แอปดึงมาได้ในขณะนี้:")
        st.dataframe(all_data, use_container_width=True)
    else:
        st.info("ฐานข้อมูลว่างเปล่า (หรือแอปไม่มีสิทธิ์เข้าถึงข้อมูลด้วย RLS)")

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
