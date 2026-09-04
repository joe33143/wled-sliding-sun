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
    # 4. WEATHER BRIGHTNESS, AFTERBURNER MATH & TIME PROFILES
    # ==========================================
    evening_start = s_today["sunset"]
    evening_end = now.replace(hour=21, minute=30, second=0, microsecond=0)
    if evening_end < evening_start: 
        evening_end += datetime.timedelta(days=1)
        
    seconds_past_sunset = (now - evening_start).total_seconds()
    
    if not is_night:
        # --- DAYTIME MATH ---
        master_bri = 255
        matrix_bri = 255
        active_pal = 0
        
        r_base, g_base, b_base = 0, 0, 0
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

        # Weather Scaling
        if clouds >= 100:
            weather_scale = 0.30
        elif clouds <= 30:
            weather_scale = 0.70
        else:
            weather_scale = 0.70 - ((clouds - 30) / 70.0) * 0.40
            
        active_alpha = int(255 * weather_scale)
        r = min(255, max(0, int((r_base * active_alpha) / 255)))
        g = min(255, max(0, int((g_base * active_alpha) / 255)))
        b = min(255, max(0, int((b_base * active_alpha) / 255)))

        final_sky = [min(255, max(0, int(c * weather_scale))) for c in sky_color]
        final_cloud = [min(255, max(0, int(c * weather_scale))) for c in cloud_color]

    elif 0 <= seconds_past_sunset <= (45 * 60):
        # --- SUNSET RAMP (0 to 45 mins after sunset) ---
        # Smoothly fades from Daytime values into the User's Evening JSON Profile
        t = seconds_past_sunset / (45.0 * 60.0)
        
        master_bri = int(255 + (127 - 255) * t)
        matrix_bri = int(255 + (173 - 255) * t)
        active_pal = 9
        active_alpha = 255
        
        final_sky = [int(sky_color[i] * (1 - t) + 0 * t) for i in range(3)]
        final_cloud = [int(cloud_color[i] * (1 - t) + 36 * t) for i in range(3)]
        sun_color = [int(sun_color[i] * (1 - t) + 255 * t) for i in range(3)]
        
        r = int(0 + (8 - 0) * t)
        g = int(0 + (255 - 0) * t)
        b = int(0 + (0 - 0) * t)
        
    elif evening_start <= now <= evening_end:
        # --- EVENING PROFILE (Locked until 9:30 PM) ---
        # Injects the exact JSON profile provided
        master_bri = 127
        matrix_bri = 173
        active_pal = 9
        active_alpha = 255
        
        final_sky = [0, 0, 0]
        final_cloud = [36, 36, 36]
        sun_color = [255, 255, 255]
        
        r, g, b = 8, 255, 0
        
    else:
        # --- DEEP NIGHT (9:30 PM to Sunrise) ---
        master_bri = global_bri 
        matrix_bri = 255
        active_pal = 0
        active_alpha = sun_alpha
        
        final_sky = sky_color
        final_cloud = cloud_color
        r, g, b = 0, 0, 0

    # ==========================================
    # 5. BUILD THE MICRO-PAYLOADS (Two-Step Delivery)
    # ==========================================
    payload_preset = {
        "on": True,
        "ps": 1
    }

    payload_data = {
      "on": True,
      "bri": master_bri,          # Allows Python to set global bri (127 during Evening)
      "transition": 200,
      "seg": [
        # ------------------------------------------
        # Segment 0: THE UNIFIED MATRIX ENGINE
        # ------------------------------------------
        { 
          "id": 0, 
          "on": True,
          "bri": matrix_bri,          # Matrix-specific brightness (173 during Evening)
          "sx": target_x,             
          "ix": int(clouds * 2.55),   
          "c1": active_alpha,         
          "pal": active_pal,          # Dynamically switches to Palette 9 at sunset      
          "col": [ final_sky, final_cloud, sun_color ] 
        },
        # ------------------------------------------
        # Segment 2: REEF AFTERBURNER (12V BD139)
        # ------------------------------------------
        {
          "id": 2,
          "on": True,
          "bri": 255,
          "col": [ [r, g, b] ]
        }
      ]
    }
    
    # 6. CONSOLE LOGGING
    if 0 <= seconds_past_sunset <= (45 * 60):
        mode_name = "SUNSET RAMP"
    elif evening_start <= now <= evening_end:
        mode_name = "EVENING JSON PROFILE"
    elif is_night:
        mode_name = "DEEP NIGHT"
    else:
        mode_name = "DAY"
        
    print(f"[{mode_name}] Pos: {target_x}/255 | Alt: {alt:.1f}° | Temp: {temp}°C | Clouds: {clouds}%")
    print(f"Master Bri: {master_bri} | Matrix Bri: {matrix_bri} | Palette: {active_pal}")
    print(f"Matrix Output -> Sky: {final_sky} | Cloud: {final_cloud} | Moon/Sun: {sun_color}")
    print(f"Afterburners (RGB) -> East: {r} | Noon: {g} | West: {b}")

    # 7. PUSH TO MQTT
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        
        client.publish(MQTT_TOPIC, json.dumps(payload_preset), qos=1)
        time.sleep(0.5)
        client.publish(MQTT_TOPIC, json.dumps(payload_data), qos=1)
        print("Successfully published live overrides to MQTT.")
        
    except Exception as e:
        print(f"MQTT Connection failed: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_sky_engine()
