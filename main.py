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

# --- ATMOSPHERIC MATH ---
def get_base_hues(altitude_deg, clouds, turbidity=5.0):
    c = clouds / 100.0
    keys = [
        (-6,   35,  45,  75),  
        (0,   120, 110, 140),  
        (10,  190, 185, 205),  
        (35,  240, 235, 235),  
        (55,  255, 250, 245),  
        (90,  255, 255, 255)   
    ]
    k1, k2 = keys[0], keys[-1]
    for i in range(len(keys) - 1):
        if keys[i][0] <= altitude_deg <= keys[i+1][0]:
            k1, k2 = keys[i], keys[i+1]
            break
    if altitude_deg < keys[0][0]: k1 = k2 = keys[0]
    elif altitude_deg > keys[-1][0]: k1 = k2 = keys[-1]

    t = 0.0 if k2[0] == k1[0] else max(0.0, min(1.0, (altitude_deg - k1[0]) / (k2[0] - k1[0])))
    r = lerp(k1[1], k2[1], t)
    g = lerp(k1[2], k2[2], t)
    b = lerp(k1[3], k2[3], t)

    dim = 1.0 - (c * 0.5)
    r *= dim; g *= dim; b *= dim
    r += (turbidity * 3.5); g += (turbidity * 2.5); b -= (turbidity * 1.5)
    
    return [int(max(0, min(255, r))), int(max(0, min(255, g))), int(max(0, min(255, b)))]

def get_sun_color(alt):
    # Sun is completely off until -2 degrees, then fades from deep red to yellow
    if alt < -2:
        return [0, 0, 0]
    elif alt < 15:
        progress = max(0.0, min(1.0, (alt + 2) / 17.0))
        return [int(lerp(100, 255, progress)), int(lerp(10, 241, progress)), int(lerp(0, 224, progress))]
    return [255, 241, 224]

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
    elif now <= sunset_time + datetime.timedelta(minutes=30):
        phase = "SUNSET_FADE"
    elif now_time < datetime.time(21, 0):
        phase = "EVENING_LOCKED"
    else:
        phase = "NIGHT_SKY"

    # ==========================================
    # CALCULATE PHASE VALUES
    # ==========================================
    seg0_on, seg2_on, seg4_on = True, False, True
    ab_val = 0
    turbidity = 5.0
    
    if phase == "SLEEP":
        master_bri = 116
        c_bri, target_x, c_ix, active_alpha, c_pal = 0, 0, 0, 0, 0
        c_sky, c_cloud, c_sun = [0,0,0], [0,0,0], [0,0,0]
        seg0_on, seg2_on, seg4_on = False, False, False

    elif phase == "MORNING_RAMP":
        morning_start = now.replace(hour=4, minute=0, second=0)
        t = max(0.0, min(1.0, (now - morning_start).total_seconds() / (sunrise_time - morning_start).total_seconds()))
        
        # Original startup dimming: peaks at exactly 18/255 at sunrise
        master_bri = lerp(0, 18, t ** 3) 
        c_bri = 255
        target_x = lerp(0, 128, t)
        
        clamped_alt = min(0.0, alt)
        c_sky = get_base_hues(clamped_alt, clouds, turbidity)
        c_cloud = [min(255, int(c * 1.8)) for c in c_sky] 
        c_sun = get_sun_color(alt)
        
        c_ix = int(clouds * 2.55)
        c_pal = 59
        active_alpha = lerp(0, 255, t)

    elif phase == "DAY":
        target_x = calculate_position(now, sunrise_time, sunset_time)
        
        c_sky = get_base_hues(alt, clouds, turbidity)
        c_cloud = [min(255, int(c * 1.8)) for c in c_sky]
        c_sun = get_sun_color(alt)
        
        # Determine weather-based brightness ceiling
        if is_stormy or clouds > 75:
            active_alpha = int(lerp(100, 0, (clouds - 75)/25.0))
            weather_master_target = 180 if not is_stormy else 130
        elif clouds <= 35:
            active_alpha = 255
            weather_master_target = 255
        else:
            active_alpha = int(lerp(255, 100, (clouds - 35)/40.0))
            weather_master_target = int(lerp(255, 180, (clouds - 35)/40.0))
            
        # Apply Time-of-Day Ramps to the Master Brightness
        eight_am = now.replace(hour=8, minute=0, second=0, microsecond=0)
        time_to_sunset = (sunset_time - now).total_seconds()
        
        if now < eight_am:
            # Smoothly fades from 18 up to the daily weather target between sunrise and 8 AM
            ramp_t = max(0.0, min(1.0, (now - sunrise_time).total_seconds() / (eight_am - sunrise_time).total_seconds()))
            master_bri = int(lerp(18, weather_master_target, ramp_t))
            c_bri = 255
        elif time_to_sunset < 5400:  
            fade_t = max(0.0, time_to_sunset / 5400.0)
            master_bri = lerp(127, weather_master_target, fade_t)
            c_bri = lerp(173, 255, fade_t)
        else:
            master_bri = weather_master_target
            c_bri = 255
        
        # Afterburner sweep math
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

        if clouds > 74.5: ab_val = 0  
        if ab_val < 51: ab_val = 0    
        
        seg2_on = (ab_val > 0)
        c_pal = 59
        c_ix = int(clouds * 2.55)

    elif phase == "SUNSET_FADE":
        t = (now - sunset_time).total_seconds() / 1800.0  
        
        master_bri = lerp(255, 80, t)
        c_bri = lerp(255, 120, t)
        target_x = lerp(255, 128, t)
        
        c_sky = get_base_hues(alt, clouds, turbidity)
        c_cloud = [min(255, int(c * 1.8)) for c in c_sky]
        c_sun = get_sun_color(alt)
        
        c_ix = lerp(int(clouds * 2.55), 153, t)
        active_alpha = lerp(255, 0, t)
        c_pal = 9 
        
        ab_val = lerp(ab_val, 0, t)
        if ab_val < 51: ab_val = 0
        seg2_on = (ab_val > 0)

    elif phase == "EVENING_LOCKED":
        master_bri = 80
        c_bri = 120
        target_x = 128
        c_ix = 153  
        active_alpha = 255
        c_pal = 9
        
        c_sky = [0, 0, 0]
        c_cloud = [0, 0, 0]  
        c_sun = [255, 255, 255]
        
        seg2_on = False
        ab_val = 0

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
        
        seg2_on, seg4_on = False, False
        ab_val = 0

    # ====================================================
    # BUILD EXPLICIT 5-SEGMENT PAYLOAD
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
                "fx": 142, "sx": target_x, "ix": c_ix, "c1": active_alpha
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
                "col": [[200, 200, 200, 200], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 0, "sx": 128, "ix": 128, "pal": 0, "lc": 2
            },
            {
                "id": 4, 
                "on": seg4_on,
                "bri": 255,
                "col": [[255,255,255,0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 83, "sx": 64, "ix": 69, "pal": 54
            }
        ]
    }

    # --- PUSH TO MQTT ---
    print(f"[{phase}] Time: {now_time} | Alt: {alt:.2f} | Clouds: {clouds}%")
    
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
