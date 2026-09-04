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

# Import our new modular effect engines
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

# --- MAIN LOGIC ---
def run_sky_engine():
    city = LocationInfo("Varanasi", "India", TIMEZONE, LAT, LON)
    
    # 1. Calculate Astronomical Positions
    s_today = sun(city.observer, date=datetime.date.today(), tzinfo=city.timezone)
    s_tomorrow = sun(city.observer, date=datetime.date.today() + datetime.timedelta(days=1), tzinfo=city.timezone)
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    
    observer = ephem.Observer()
    observer.lat, observer.lon = str(LAT), str(LON)
    observer.date = datetime.datetime.now(pytz.utc)
    
    sun_ephem = ephem.Sun()
    sun_ephem.compute(observer)
    alt = math.degrees(sun_ephem.alt)
    
    moon_ephem = ephem.Moon()
    moon_ephem.compute(observer)
    moon_phase = moon_ephem.phase / 100.0 
    
    # 2. Fetch Live Weather
    url = f"https://www.meteosource.com/api/v1/free/point?place_id=varanasi&sections=current&language=en&units=metric&key={METEOSOURCE_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        clouds = data['current']['cloud_cover'] 
        temp = data['current']['temperature']
        summary = data['current']['summary'].lower()
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        clouds, temp, summary = 0, 25.0, "clear"
        
    is_stormy = "thunder" in summary or "storm" in summary
    is_night = alt < 0
        
    # 3. GET COLORS FROM MODULES
    if is_night:
        if now > s_today["sunset"]:
            target_x = calculate_position(now, s_today["sunset"], s_tomorrow["sunrise"])
        else:
            yesterday_sunset = sun(city.observer, date=datetime.date.today() - datetime.timedelta(days=1), tzinfo=city.timezone)["sunset"]
            target_x = calculate_position(now, yesterday_sunset, s_today["sunrise"])
            
        global_bri, sun_color, sky_color, cloud_color, sun_alpha = night_effects.get_night_payload(moon_phase, clouds, is_stormy)
    else:
        target_x = calculate_position(now, s_today["sunrise"], s_today["sunset"])
        global_bri, sun_color, sky_color, cloud_color, sun_alpha = day_effects.get_day_payload(alt, temp, clouds, is_stormy)


    # ==========================================
    # 4. WEATHER BRIGHTNESS & AFTERBURNER MATH
    # ==========================================
    r_base, g_base, b_base = 0, 0, 0
    
    if not is_night:
        if target_x < 30:
            pass
        elif 30 <= target_x < 100:
            r_base = int(((target_x - 30) / 70.0) * 255)
        elif 100 <= target_x <= 155:
            r_base, g_base, b_base = 255, 255, 255
        elif 155 < target_x <= 225:
            fade_ratio = 1.0 - ((target_x - 155) / 70.0)
            r_base = int(255 * fade_ratio)
            g_base = int(255 * fade_ratio)
            b_base = 255
        elif target_x > 225:
            fade_ratio = 1.0 - ((target_x - 225) / 30.0)
            b_base = max(0, int(255 * fade_ratio))

    # STRICT SCALING: 30% Cloudy -> 70% Brightness | 100% Cloudy -> 30% Brightness Floor
    if clouds >= 100:
        weather_scale = 0.30
    elif clouds <= 30:
        weather_scale = 0.70
    else:
        # Smoothly interpolates the gap between 30% and 100% clouds
        weather_scale = 0.70 - ((clouds - 30) / 70.0) * 0.40
    
    # Scale the 12V Afterburners
    dynamic_alpha = int(255 * weather_scale)
    active_alpha = dynamic_alpha if not is_night else 0
    
    r = min(255, max(0, int((r_base * active_alpha) / 255)))
    g = min(255, max(0, int((g_base * active_alpha) / 255)))
    b = min(255, max(0, int((b_base * active_alpha) / 255)))

    # Dim BOTH the Sky and Cloud RGB values using the new weather scale
    dimmed_sky = [min(255, max(0, int(c * weather_scale))) for c in sky_color]
    dimmed_cloud = [min(255, max(0, int(c * weather_scale))) for c in cloud_color]

    # ==========================================
    # 5. BUILD THE MICRO-PAYLOADS (Two-Step Delivery)
    # ==========================================
    
    # STEP 1: Turn system on and load Preset 1
    payload_preset = {
        "on": True,
        "ps": 1
    }

    # STEP 2: Apply live overrides 0.5 seconds later
    payload_data = {
      "on": True,
      "transition": 200,
      "seg": [
        # ------------------------------------------
        # Segment 0: THE UNIFIED MATRIX ENGINE
        # ------------------------------------------
        { 
          "id": 0, 
          "on": True,
          "bri": 255,                 # Master segment brightness stays 100%
          "sx": target_x,             
          "ix": int(clouds * 2.55),   
          "c1": active_alpha,         
          "pal": 0,                   
          "col": [ dimmed_sky, dimmed_cloud, sun_color ] # Pushes the scaled colors
        },
        # ------------------------------------------
        # Segment 2: REEF AFTERBURNER (12V BD139)
        # ------------------------------------------
        {
          "id": 2,
          "on": True,
          "col": [ [r, g, b] ]
        }
      ]
    }
    
    # 6. CONSOLE LOGGING
    mode_name = "NIGHT" if is_night else "DAY"
    print(f"[{mode_name}] Pos: {target_x}/255 | Alt: {alt:.1f}° | Temp: {temp}°C | Clouds: {clouds}%")
    print(f"Weather Scale: {weather_scale:.2f} (Applies to Sky & Clouds)")
    print(f"Afterburners (RGB) -> East: {r} | Noon: {g} | West: {b} | Active Alpha: {active_alpha}")

    # 7. PUSH TO MQTT (Two-Stage Transmission)
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        
        # Fire the preset
        client.publish(MQTT_TOPIC, json.dumps(payload_preset), qos=1)
        print("Fired Preset 1...")
        
        # Give WLED memory half a second to load the preset without crashing
        time.sleep(0.5)
        
        # Fire the weather overrides
        client.publish(MQTT_TOPIC, json.dumps(payload_data), qos=1)
        print("Successfully published live weather overrides to MQTT.")
        
    except Exception as e:
        print(f"MQTT Connection failed: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_sky_engine()
