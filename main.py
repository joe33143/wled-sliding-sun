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
    # 4. SEGMENT 3: AFTERBURNER SPATIAL MATH
    # ==========================================
    # target_x represents the sun's position from 0 (Sunrise) to 255 (Sunset)
    r_base, g_base, b_base = 0, 0, 0
    
    if not is_night:
        if target_x < 30:
            # DAWN BUFFER: Matrix only. Afterburners wait.
            pass
        elif 30 <= target_x < 100:
            # MORNING RAMP: East (Red pin) slowly ramps up to max.
            r_base = int(((target_x - 30) / 70.0) * 255)
        elif 100 <= target_x <= 155:
            # HIGH NOON BLAST (Approx 2 hours): All RGB modules fire at 100%.
            r_base, g_base, b_base = 255, 255, 255
        elif 155 < target_x <= 225:
            # AFTERNOON DESCENT: East and Noon fade out. West (Blue pin) takes over.
            fade_ratio = 1.0 - ((target_x - 155) / 70.0)
            r_base = int(255 * fade_ratio)
            g_base = int(255 * fade_ratio)
            b_base = 255
        elif target_x > 225:
            # DUSK BUFFER: West fades out roughly an hour before sunset.
            fade_ratio = 1.0 - ((target_x - 225) / 30.0)
            b_base = max(0, int(255 * fade_ratio))

    # THE ALPHA FLOOR: Prevent weather from killing the tank exposure completely
    min_exposure = 60
    active_alpha = max(sun_alpha, min_exposure) if not is_night else 0
    
    # Apply alpha to final RGB values and clamp to 255
    r = min(255, max(0, int((r_base * active_alpha) / 255)))
    g = min(255, max(0, int((g_base * active_alpha) / 255)))
    b = min(255, max(0, int((b_base * active_alpha) / 255)))

    # SKY BOOST: If afterburners are firing hard, boost matrix sky so it isn't washed out
    if not is_night and (r > 100 or g > 100 or b > 100):
        # Bump the sky color brightness slightly
        sky_color = [min(255, c + 30) for c in sky_color]

    # ==========================================
    # 5. BUILD THE MICRO-PAYLOAD
    # ==========================================
    payload = {
      "bri": 255,  # <-- FIX 1: Master valve forced wide open (No global double-dimming)
      "transition": 200,             
      "seg": [
        # Segment 0: The Sky Engine (Matrix)
        { 
          "id": 0, 
          "bri": global_bri, # <-- FIX 2: Weather brightness is applied ONLY to the 5V matrix
          "sx": target_x, 
          "ix": int(clouds * 2.55), 
          "c1": sun_alpha, 
          "col": [ sun_color, sky_color, cloud_color ] 
        },
        # Segment 3: The 12V BD139 Afterburners
        {
          "id": 3,
          "bri": 255, # <-- FIX 3: Segment brightness maxed out so Python's math passes through purely
          "on": True,
          "col": [ [r, g, b], [0, 0, 0], [0, 0, 0] ]
        }
      ]
    }
    
    # 6. CONSOLE LOGGING
    mode_name = "NIGHT" if is_night else "DAY"
    print(f"[{mode_name}] Pos: {target_x}/255 | Alt: {alt:.1f}° | Temp: {temp}°C")
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
