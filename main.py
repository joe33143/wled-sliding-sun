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
import night_effects

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
    s_tomorrow = sun(city.observer, date=datetime.date.today() + datetime.timedelta(days=1), tzinfo=city.timezone)
    
    sunset_time = s_today["sunset"]
    evening_end = now.replace(hour=21, minute=30, second=0, microsecond=0)
    if evening_end < sunset_time: 
        evening_end += datetime.timedelta(days=1)
    
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

    # Determine Phase
    if now < s_today["sunrise"]:
        phase = "DEEP_NIGHT"
    elif now < sunset_time:
        phase = "DAY"
    elif now <= sunset_time + datetime.timedelta(minutes=45):
        phase = "SUNSET_FADE"
    elif now <= evening_end:
        phase = "EVENING_LOCKED"
    else:
        phase = "DEEP_NIGHT"

    # ==========================================
    # CALCULATE RAW VALUES BASED ON TIME OF DAY
    # ==========================================
    if phase == "DAY":
        target_x = calculate_position(now, s_today["sunrise"], s_today["sunset"])
        _, raw_sun, raw_sky, raw_cloud, raw_alpha = day_effects.get_day_payload(alt, temp, clouds, is_stormy)
        
        # Weather Dimming
        if clouds >= 100: weather_scale = 0.30
        elif clouds <= 30: weather_scale = 0.70
        else: weather_scale = 0.70 - ((clouds - 30) / 70.0) * 0.40
            
        active_alpha = int(255 * weather_scale)
        
        # Afterburner Spatial Math
        r_base, g_base, b_base = 0, 0, 0
        if 30 <= target_x < 100:
            r_base = int(((target_x - 30) / 70.0) * 255)
        elif 100 <= target_x <= 155:
            r_base, g_base, b_base = 255, 255, 255
        elif 155 < target_x <= 225:
            fade = 1.0 - ((target_x - 155) / 70.0)
            r_base, g_base, b_base = int(255 * fade), int(255 * fade), 255
        elif target_x > 225:
            b_base = max(0, int(255 * (1.0 - ((target_x - 225) / 30.0))))
            
        ab_r = min(255, max(0, int((r_base * active_alpha) / 255)))
        ab_g = min(255, max(0, int((g_base * active_alpha) / 255)))
        ab_b = min(255, max(0, int((b_base * active_alpha) / 255)))

        c_bri = 255
        c_pal = 0
        
        c_sky = [min(255, max(0, int(c * weather_scale))) for c in raw_sky]
        c_cloud = [min(255, max(0, int(c * weather_scale))) for c in raw_cloud]
        c_sun = raw_sun
        c_ix = int(clouds * 2.55)

    elif phase == "SUNSET_FADE":
        _, a_sun, a_sky, a_cloud, a_alpha = day_effects.get_day_payload(0.0, temp, clouds, is_stormy)
        t = (now - sunset_time).total_seconds() / (45.0 * 60.0)
        
        c_bri = lerp(255, 173, t)
        target_x = lerp(255, 128, t)
        c_ix = lerp(int(clouds * 2.55), 171, t)
        active_alpha = lerp(a_alpha, 255, t)
        c_pal = 9 
        
        c_sky = lerp_color(a_sky, [0, 0, 0], t)
        c_cloud = lerp_color(a_cloud, [36, 36, 36], t)
        c_sun = lerp_color(a_sun, [255, 255, 255], t)
        
        ab_r, ab_g, ab_b = lerp_color([0, 0, 0], [8, 255, 0], t)

    elif phase == "EVENING_LOCKED":
        c_bri = 173
        target_x = 128
        c_ix = 171
        c_pal = 9
        active_alpha = 255
        
        c_sky = [0, 0, 0]
        c_cloud = [36, 36, 36]
        c_sun = [255, 255, 255]
        ab_r, ab_g, ab_b = 8, 255, 0

    elif phase == "DEEP_NIGHT":
        yesterday_sunset = sun(city.observer, date=datetime.date.today() - datetime.timedelta(days=1), tzinfo=city.timezone)["sunset"]
        target_x = calculate_position(now, yesterday_sunset, s_today["sunrise"]) if now < s_today["sunrise"] else calculate_position(now, s_today["sunset"], s_tomorrow["sunrise"])
        
        c_bri, c_sun, c_sky, c_cloud, active_alpha = night_effects.get_night_payload(moon_phase, clouds, is_stormy)
        c_ix = int(clouds * 2.55)
        c_pal = 0
        ab_r, ab_g, ab_b = 0, 0, 0

    # ====================================================
    # ASSIGN VARIABLES FOR YOUR CUSTOM PAYLOAD
    # ====================================================
    wled_transition = 70
    
    # --- Segment 0 (Sun Layer) ---
    sun_bri = c_bri
    sun_pos = target_x
    sun_alpha = active_alpha
    
    # --- Segment 1 (Cloud/Sky Layer) ---
    cloud_bri = c_bri
    sky_col = c_sky + [0]    # Appending 0 for White channel compatibility
    cloud_col = c_cloud + [0]
    col3 = c_sun + [0]
    cloud_fx = 142
    cloud_sx = target_x
    cloud_ix = c_ix
    pal = c_pal
    
    # --- Segment 2 (Afterburners) ---
    # Overriding with your requested dynamic colors (or hardcode [8,255,0,0] if you prefer)
    afterburner_col = [ab_r, ab_g, ab_b, 0]
    
    # --- Segment 3 (Tank/Curtain) ---
    tank_bri = 116 if not (phase == "DEEP_NIGHT") else 0
    exp_col1 = [0, 0, 0, 0]
    exp_col2 = [0, 0, 0, 0]
    exp_col3 = [0, 0, 0, 0]
    exp_fx = 0
    exp_sx = 166
    exp_ix = 152
    exp_pal = 30

    # ----------------------------------------------------
    # --- BUILD JSON PAYLOAD (Your Exact Structure) ---
    # ----------------------------------------------------
    payload = {
        "on": True, 
        "bri": 255, 
        "transition": wled_transition, 
        "seg": [
            {
                "id": 0, 
                "on": sun_bri > 0, 
                "bri": sun_bri,
                "col": [[255, 255, 255, 0], [0, 0, 0, 0], [0, 0, 0, 0]], 
                "cct": 127,
                "fx": 255, "sx": sun_pos, "ix": sun_alpha, "pal": 0 
            },
            {
                "id": 1, 
                "on": cloud_bri > 0, 
                "bri": cloud_bri, 
                "col": [sky_col, cloud_col, col3], 
                "cct": 127,  
                "fx": cloud_fx, "sx": cloud_sx, "ix": cloud_ix, "pal": pal 
            },
            {
                "id": 2, 
                "on": True,
                "bri": 255,
                "col": [afterburner_col, [0, 0, 0, 0], [0, 0, 0, 0]], 
                "cct": 127,  
                "fx": 0, "sx": 128, "ix": 128, "pal": 0
            },
            {
                "id": 3, 
                "on": tank_bri > 0,
                "bri": tank_bri,
                "col": [exp_col1, exp_col2, exp_col3], 
                "cct": 127,  
                "fx": exp_fx, "sx": exp_sx, "ix": exp_ix, "pal": exp_pal
            }
        ]
    }

    # --- PUSH TO MQTT ---
    print(f"[{phase}] Outputting custom layout payload...")
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        publish_result = client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
        publish_result.wait_for_publish(timeout=10)
        print("Successfully published payload.")
    except Exception as e:
        print(f"MQTT Connection failed: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_sky_engine()
