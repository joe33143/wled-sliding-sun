import os
import time
import json
import requests
import datetime
import math
import paho.mqtt.client as mqtt
from astral import LocationInfo
from astral.sun import sun
import ephem
import pytz

import day_effects

# --- GLOBALS & CONFIG ---
METEOSOURCE_API_KEY = os.getenv("METEOSOURCE_API_KEY")
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "joe33143/reef/api"
LAT = 25.3176
LON = 83.0062
TIMEZONE = "Asia/Kolkata"

# --- HELPER FUNCTIONS ---
def calculate_position(now, start_time, end_time):
    if now < start_time: return 0    
    if now > end_time: return 255   
    duration = (end_time - start_time).total_seconds()
    elapsed = (now - start_time).total_seconds()
    return int((elapsed / duration) * 255)

def lerp(a, b, t):
    return int(a + (b - a) * t)

def lerp_color(c1, c2, t):
    return [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)]

# --- MAIN LOGIC ---
def run_sky_engine():
    city = LocationInfo("Varanasi", "India", TIMEZONE, LAT, LON)
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    
    s_today = sun(city.observer, date=datetime.date.today(), tzinfo=city.timezone)
    sunrise_time = s_today["sunrise"]
    sunset_time = s_today["sunset"]
    
    observer = ephem.Observer()
    observer.lat, observer.lon = str(LAT), str(LON)
    observer.date = datetime.datetime.now(pytz.utc)
    
    sun_ephem = ephem.Sun()
    sun_ephem.compute(observer)
    alt = math.degrees(sun_ephem.alt)
    
    moon_ephem = ephem.Moon()
    moon_ephem.compute(observer)
    moon_phase = moon_ephem.phase / 100.0 
    
    try:
        url = f"https://www.meteosource.com/api/v1/free/point?place_id=varanasi&sections=current&language=en&units=metric&key={METEOSOURCE_API_KEY}"
        response = requests.get(url)
        data = response.json()
        clouds = data['current']['cloud_cover'] 
        temp = data['current']['temperature']
        summary = data['current']['summary'].lower()
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        clouds, temp, summary = 0, 25.0, "clear"
        
    is_stormy = "thunder" in summary or "storm" in summary

    # ==========================================
    # INDEPENDENT BAMBOO LIGHT LOGIC
    # ==========================================
    bamboo_target = 255 
    bamboo_sunrise_end = sunrise_time + datetime.timedelta(minutes=30)
    bamboo_sunset_end = sunset_time + datetime.timedelta(minutes=30)
    
    if now < sunrise_time or now >= bamboo_sunset_end:
        bamboo_bri = 0
        bamboo_on = False
    elif sunrise_time <= now <= bamboo_sunrise_end:
        t = (now - sunrise_time).total_seconds() / 1800.0
        bamboo_bri = lerp(0, bamboo_target, t)
        bamboo_on = True
    elif sunset_time <= now <= bamboo_sunset_end:
        t = (now - sunset_time).total_seconds() / 1800.0
        bamboo_bri = lerp(bamboo_target, 0, t)
        bamboo_on = True
    else:
        bamboo_bri = bamboo_target
        bamboo_on = True

    # ==========================================
    # TIME-BASED PHASE ROUTING 
    # ==========================================
    now_time = now.time()
    
    if datetime.time(22, 0) <= now_time or now_time < datetime.time(4, 0):
        phase = "SLEEP"
    elif datetime.time(4, 0) <= now_time < sunrise_time.time():
        phase = "MORNING_RAMP"
    elif now < sunset_time:
        phase = "DAY"
    elif now <= sunset_time + datetime.timedelta(minutes=45):
        phase = "SUNSET_FADE"
    elif now_time < datetime.time(21, 0):
        phase = "EVENING_LOCKED"
    else:
        phase = "NIGHT_SKY"

    # ==========================================
    # CALCULATE PHASE VALUES
    # ==========================================
    seg0_on, seg2_on = True, False
    ab_val = 0
    
    if phase == "SLEEP":
        master_bri = 116
        c_bri, target_x, c_ix, active_alpha, c_pal = 0, 0, 0, 0, 0
        c_sky, c_cloud, c_sun = [0,0,0], [0,0,0], [0,0,0]
        seg0_on, seg2_on = False, False

    elif phase == "MORNING_RAMP":
        morning_start = now.replace(hour=4, minute=0, second=0)
        t = (now - morning_start).total_seconds() / (sunrise_time - morning_start).total_seconds()
        
        _, d_sun, d_sky, d_cloud, d_alpha = day_effects.get_day_payload(0.0, temp, clouds, is_stormy)
        
        c_bri = lerp(0, 255, t)
        target_x = lerp(0, 128, t)
        active_alpha = lerp(0, d_alpha, t)
        c_ix = int(clouds * 2.55)
        c_pal = 59
        
        c_sky = lerp_color([0, 0, 5], d_sky, t)
        c_cloud = lerp_color([10, 10, 15], d_cloud, t)
        c_sun = lerp_color([140, 145, 150], d_sun, t)
        
        master_bri = c_bri

    elif phase == "DAY":
        target_x = calculate_position(now, sunrise_time, sunset_time)
        _, raw_sun, raw_sky, raw_cloud, raw_alpha = day_effects.get_day_payload(alt, temp, clouds, is_stormy)
        
        if clouds >= 100: weather_scale = 0.55
        elif clouds <= 30: weather_scale = 0.95
        else: weather_scale = 0.95 - ((clouds - 30) / 70.0) * 0.40
            
        active_alpha = int(255 * weather_scale)
        ab_base = 0
        
        if 100 <= target_x <= 155:
            ab_base = 255
            ab_active_alpha = 255
        else:
            ab_active_alpha = active_alpha
            if 30 <= target_x < 100:
                ab_base = int(((target_x - 30) / 70.0) * 255)
            elif 155 < target_x <= 225:
                fade = 1.0 - ((target_x - 155) / 70.0)
                ab_base = int(255 * fade)
            
        if now.hour >= 8:
            ab_val = min(255, max(0, int((ab_base * ab_active_alpha) / 255)))
        else:
            ab_val = 0

        # Python-level Cutoffs
        if clouds > 74.5: ab_val = 0  # Slider > 190 condition
        if ab_val < 51: ab_val = 0    # 20% Floor rule
        
        seg2_on = (ab_val > 0)
        master_bri, c_bri = 255, 255
        c_pal = 59
        c_ix = int(clouds * 2.55)
        c_sky = [min(255, max(0, int(c * weather_scale))) for c in raw_sky]
        c_cloud = [min(255, max(0, int(c * weather_scale))) for c in raw_cloud]
        c_sun = raw_sun

    elif phase == "SUNSET_FADE":
        _, a_sun, a_sky, a_cloud, a_alpha = day_effects.get_day_payload(0.0, temp, clouds, is_stormy)
        t = (now - sunset_time).total_seconds() / (45.0 * 60.0)
        
        master_bri = lerp(255, 127, t)
        c_bri = lerp(255, 173, t)
        target_x = lerp(255, 128, t)
        c_ix = lerp(int(clouds * 2.55), 171, t)
        active_alpha = lerp(a_alpha, 255, t)
        c_pal = 9 
        
        c_sky = lerp_color(a_sky, [0, 0, 0], t)
        c_cloud = lerp_color(a_cloud, [36, 36, 36], t)
        c_sun = lerp_color(a_sun, [255, 255, 255], t)
        
        ab_val = lerp(0, 255, t)
        if clouds > 74.5: ab_val = 0 
        if ab_val < 51: ab_val = 0
        seg2_on = (ab_val > 0)

    elif phase == "EVENING_LOCKED":
        master_bri = 127
        c_bri = 173
        target_x = 128
        c_ix = 171
        active_alpha = 255
        c_pal = 9
        
        c_sky = [0, 0, 0]
        c_cloud = [36, 36, 36]
        c_sun = [255, 255, 255]
        
        ab_val = 255
        if clouds > 74.5: ab_val = 0 
        seg2_on = (ab_val > 0)

    elif phase == "NIGHT_SKY":
        master_bri = int(25.5 + (25.5 * (clouds / 100.0)))
        c_bri = 255 
        active_alpha = int(12.75 + (114.75 * moon_phase)) 
        
        target_x = 128
        c_ix = int(clouds * 2.55)
        c_pal = 0
        
        c_sky = [5, 5, 10]
        c_cloud = [20, 25, 30]
        c_sun = [140, 145, 150] 
        
        seg2_on = False
        ab_val = 0

    # ====================================================
    # BUILD EXPLICIT 6-SEGMENT PAYLOAD 
    # ====================================================
    payload = {
        "on": True, 
        "bri": master_bri, 
        "transition": 70,
        "mainseg": 2, 
        "seg": [
            {
                "id": 0, 
                "on": seg0_on, 
                "bri": c_bri,
                "col": [c_sky + [0], c_cloud + [0], c_sun + [0]], 
                "cct": 127,
                "fx": 142, "sx": target_x, "ix": c_ix, "pal": c_pal, "c1": active_alpha
            },
            {
                "id": 1, 
                "on": False, 
                "bri": 116, 
                "col": [[0,0,0,0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 0, "sx": 166, "ix": 152, "pal": 30 
            },
            {
                "id": 2, 
                "on": seg2_on,
                "bri": 255,
                "col": [[ab_val, ab_val, ab_val, 0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 169, "sx": 128, "ix": 128, "pal": 0, "rev": True
            },
            {
                "id": 3, 
                "on": bamboo_on,
                "bri": bamboo_bri,
                "col": [[126, 126, 126, 126], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 0, "sx": 128, "ix": 128, "pal": 0, "lc": 2
            },
            {
                "id": 4, 
                "on": True,
                "bri": 255,
                "col": [[255,255,255,0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 83, "sx": 64, "ix": 69, "pal": 54
            },
            {
                "id": 5, 
                "on": True,
                "bri": 255,
                "col": [[0,0,0,126], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 0, "sx": 128, "ix": 128, "pal": 0, "rY": True
            }
        ]
    }

    # --- PUSH TO MQTT ---
    print(f"[{phase}] Time: {now_time} | Clouds: {clouds}% | Moon Phase: {moon_phase:.2f}")
    print(f"Afterburners -> Level: {ab_val}/255 | Active: {seg2_on}")
    
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        publish_result = client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
        publish_result.wait_for_publish(timeout=10)
        print("Successfully published pure-white afterburner payload.")
    except Exception as e:
        print(f"MQTT Connection failed: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_sky_engine()
