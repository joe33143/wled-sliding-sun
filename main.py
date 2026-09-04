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
    
    # Defaults
    seg0_on = True
    seg1_on = False
    seg2_on = False
    
    if phase == "SLEEP":
        # 10 PM to 4 AM: Turn everything off EXCEPT the curtain
        master_bri = 116
        c_bri, target_x, c_ix, active_alpha, c_pal = 0, 0, 0, 0, 0
        c_sky, c_cloud, c_sun = [0,0,0], [0,0,0], [0,0,0]
        ab_r, ab_g, ab_b = 0, 0, 0
        
        seg0_on = False
        seg1_on = True
        seg2_on = False

    elif phase == "MORNING_RAMP":
        # 4 AM to Sunrise: Ramp up Matrix. Afterburners stay OFF.
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
        
        ab_r, ab_g, ab_b = 0, 0, 0
        master_bri = c_bri

    elif phase == "DAY":
        # Sunrise to Sunset
        target_x = calculate_position(now, sunrise_time, sunset_time)
        _, raw_sun, raw_sky, raw_cloud, raw_alpha = day_effects.get_day_payload(alt, temp, clouds, is_stormy)
        
        if clouds >= 100: weather_scale = 0.30
        elif clouds <= 30: weather_scale = 0.70
        else: weather_scale = 0.70 - ((clouds - 30) / 70.0) * 0.40
            
        active_alpha = int(255 * weather_scale)
        
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
            
        # Only enable afterburners after 8 AM
        if now.hour >= 8:
            seg2_on = True
            ab_r = min(255, max(0, int((r_base * active_alpha) / 255)))
            ab_g = min(255, max(0, int((g_base * active_alpha) / 255)))
            ab_b = min(255, max(0, int((b_base * active_alpha) / 255)))
        else:
            ab_r, ab_g, ab_b = 0, 0, 0

        master_bri = 255
        c_bri = 255
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
        
        seg2_on = True
        ab_r, ab_g, ab_b = lerp_color([0, 0, 0], [8, 255, 0], t)

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
        
        seg2_on = True
        ab_r, ab_g, ab_b = 8, 255, 0

    elif phase == "NIGHT_SKY":
        # 9 PM to 10 PM: Dim Moon & Night Sky
        # Cloud brightness scales from 10% (min) to 20% (max) based on weather
        master_bri = int(25.5 + (25.5 * (clouds / 100.0)))
        c_bri = 255 
        
        # Moon Alpha scales 5% to 50% based on lunar phase
        active_alpha = int(12.75 + (114.75 * moon_phase)) 
        
        target_x = 128
        c_ix = int(clouds * 2.55)
        c_pal = 0
        
        c_sky = [5, 5, 10]
        c_cloud = [20, 25, 30]
        c_sun = [140, 145, 150] # Cold Grey Moon
        
        seg2_on = False
        ab_r, ab_g, ab_b = 0, 0, 0

    # ====================================================
    # ASSIGN VARIABLES & BUILD PAYLOAD
    # ====================================================
    wled_transition = 70
    
    payload = {
        "on": True, 
        "bri": master_bri, 
        "transition": wled_transition, 
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
                "on": seg1_on, 
                "bri": 116, 
                "col": [[0,0,0,0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 0, "sx": 166, "ix": 152, "pal": 30 
            },
            {
                "id": 2, 
                "on": seg2_on,
                "bri": 255,
                "col": [[ab_r, ab_g, ab_b, 0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 169, "sx": 128, "ix": 128, "pal": 0
            }
        ]
    }

    # --- PUSH TO MQTT ---
    print(f"[{phase}] Time: {now_time} | Clouds: {clouds}% | Moon Phase: {moon_phase:.2f}")
    print(f"Master Bri: {master_bri} | Moon Alpha: {active_alpha}/255")
    
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
