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

    # STRICT SCALING: 70% (Clear) down to 30% (100% Overcast)
    cloud_ratio = clouds / 100.0
    scale_factor = 0.70 - (cloud_ratio * 0.40)
    
    # Scale the 12V Afterburners
    dynamic_alpha = int(255 * scale_factor)
    active_alpha = dynamic_alpha if not is_night else 0
    
    r = min(255, max(0, int((r_base * active_alpha) / 255)))
    g = min(255, max(0, int((g_base * active_alpha) / 255)))
    b = min(255, max(0, int((b_base * active_alpha) / 255)))

    # Dim ONLY the sky color's RGB values, leaving clouds and sun alone
    dimmed_sky = [min(255, max(0, int(c * scale_factor))) for c in sky_color]

    # ==========================================
    # 5. BUILD THE MICRO-PAYLOAD 
    # ==========================================
    payload = {
      "on": True,
      "transition": 200,
      "seg": [
        # ------------------------------------------
        # Segment 0: THE UNIFIED MATRIX ENGINE
        # ------------------------------------------
        { 
          "id": 0, 
          "on": True,
          "bri": 255,                 # Master matrix brightness stays at 100% so clouds/sun stay bright
          "sx": target_x,             # Slider 1: Sun Position
          "ix": int(clouds * 2.55),   # Slider 2: Cloud Density
          "c1": active_alpha,         # Slider 3: Drops Sun visibility at night
          "pal": 0,                   # Forces "Colors Only" so we can decouple sky and clouds
          "col": [ dimmed_sky, cloud_color, sun_color ] # Pushes the dynamically dimmed sky + bright clouds
        },
        # ------------------------------------------
        # Segment 2: REEF AFTERBURNER (12V BD139)
        # ------------------------------------------
        {
          "id": 2,
          "on": True,
          # Passes the calculated RGB base out to C++ 
          "col": [ [r, g, b] ]
        }
      ]
    }
    
    # 6. CONSOLE LOGGING
    mode_name = "NIGHT" if is_night else "DAY"
    print(f"[{mode_name}] Pos: {target_x}/255 | Alt: {alt:.1f}° | Temp: {temp}°C | Clouds: {clouds}%")
    print(f"Sky Color: {dimmed_sky} | Cloud Color: {cloud_color} | Sun Color: {sun_color}")
    print(f"Afterburners (RGB) -> East: {r} | Noon: {g} | West: {b} | Active Alpha: {active_alpha}")

    
    # 7. PUSH TO MQTT
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        publish_result = client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
        publish_result.wait_for_publish(timeout=10)
        print("Successfully published micro-payload to MQTT.")
    except Exception as e:
        print(f"MQTT Connection failed: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_sky_engine()
