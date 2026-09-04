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
    # PHASE LOGIC & VALUE ASSIGNMENT
    # ==========================================
    if phase == "DAY":
        target_x = calculate_position(now, s_today["sunrise"], s_today["sunset"])
        _, raw_sun, raw_sky, raw_cloud, raw_alpha = day_effects.get_day_payload(alt, temp, clouds, is_stormy)
        
        # Weather Dimming
        if clouds >= 100: weather_scale = 0.30
        elif clouds <= 30: weather_scale = 0.70
        else: weather_scale = 0.70 - ((clouds - 30) / 70.0) * 0.40
            
        active_alpha = int(255 * weather_scale)
        
        # Afterburner Math
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

        master_bri = 255
        seg0_bri = 255
        sun_pos = target_x
        cloud_ix = int(clouds * 2.55)
        sun_alpha = active_alpha
        active_pal = 59  # Daytime Palette from your JSON
        
        sky_col = [min(255, max(0, int(c * weather_scale))) for c in raw_sky]
        afterburner_col = [ab_r, ab_g, ab_b]

    elif phase == "SUNSET_FADE":
        _, a_sun, a_sky, a_cloud, a_alpha = day_effects.get_day_payload(0.0, temp, clouds, is_stormy)
        t = (now - sunset_time).total_seconds() / (45.0 * 60.0)
        
        master_bri = lerp(255, 127, t)
        seg0_bri = lerp(255, 173, t)
        sun_pos = lerp(255, 128, t)
        cloud_ix = lerp(int(clouds * 2.55), 171, t)
        sun_alpha = lerp(a_alpha, 255, t)
        active_pal = 9  # Evening Palette from your JSON
        
        sky_col = lerp_color(a_sky, [0, 0, 0], t)
        afterburner_col = lerp_color([0, 0, 0], [8, 255, 0], t)

    elif phase == "EVENING_LOCKED":
        master_bri = 127
        seg0_bri = 173
        sun_pos = 128
        cloud_ix = 171
        sun_alpha = 255
        active_pal = 9
        
        sky_col = [0, 0, 0]
        afterburner_col = [8, 255, 0]

    elif phase == "DEEP_NIGHT":
        yesterday_sunset = sun(city.observer, date=datetime.date.today() - datetime.timedelta(days=1), tzinfo=city.timezone)["sunset"]
        target_x = calculate_position(now, yesterday_sunset, s_today["sunrise"]) if now < s_today["sunrise"] else calculate_position(now, s_today["sunset"], s_tomorrow["sunrise"])
        
        c_bri, c_sun, c_sky, c_cloud, n_alpha = night_effects.get_night_payload(moon_phase, clouds, is_stormy)
        
        master_bri = c_bri
        seg0_bri = 255
        sun_pos = target_x
        cloud_ix = int(clouds * 2.55)
        sun_alpha = n_alpha
        active_pal = 0
        
        sky_col = c_sky
        afterburner_col = [0, 0, 0]

    # ----------------------------------------------------
    # --- BUILD JSON PAYLOAD (Matches your dump exactly) ---
    # ----------------------------------------------------
    payload = {
        "on": True,
        "bri": master_bri, 
        "transition": 7,  # Matched from your dump
        "mainseg": 0,
        "seg": [
            {
                "id": 0,
                "on": True,
                "bri": seg0_bri,
                "n": "Sun",
                "col": [ sky_col, [0, 0, 0], [255, 255, 255] ], 
                "fx": 142,
                "sx": sun_pos,
                "ix": cloud_ix,
                "pal": active_pal,
                "c1": sun_alpha
            },
            {
                "id": 1,
                "on": False,
                "bri": 116,
                "n": "Curtain",
                "col": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
                "fx": 0,
                "sx": 166,
                "ix": 152,
                "pal": 30
            },
            {
                "id": 2,
                "on": True,
                "bri": 255,
                "n": "Afterburner",
                "col": [ afterburner_col, [0, 0, 0], [0, 0, 0] ],
                "fx": 169,
                "sx": 128,
                "ix": 128,
                "pal": 0
            }
        ]
    }

    # --- PUSH TO MQTT ---
    print(f"[{phase}] Pos: {sun_pos} | Clouds: {clouds}%")
    print(f"Master Bri: {master_bri} | Seg 0 Bri: {seg0_bri} | Palette: {active_pal}")
    print(f"Pushing mapped 3-segment JSON layout...")
    
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
    
