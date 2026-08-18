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

    # 4. BUILD HARDWARE PAYLOAD
    
    # Calculate Downlight Brightness (10% higher than the brightest channel of the cloud color)
    # Adding +25 ensures an absolute 10% bump on the 0-255 scale so it doesn't get too dark at night.
    downlight_bri = int(min(255, max(cloud_color) + 25))

    payload = {
      "on": True, "bri": global_bri, "transition": 200, "live": True,             
      "seg": [
        # Segment 0: The Sky Engine
        { 
          "id": 0, 
          "bri": 255,
          "fx": 142, 
          "pal": 0, 
          "sx": target_x, 
          "ix": int(clouds * 2.55), 
          "c1": sun_alpha, 
          "col": [ sun_color, sky_color, cloud_color ] 
        },
        
        # Segment 1 & 2: Solid Downlights (Dynamic brightness + 10%)
        { 
          "id": 1, "on": True, "bri": downlight_bri, 
          "fx": 88, "sx": 96, "ix": 224, "pal": 9, 
          "col": [ [255, 255, 255], [0, 0, 0], [0, 0, 0] ] 
        },
        { 
          "id": 2, "on": True, "bri": downlight_bri, 
          "fx": 88, "sx": 96, "ix": 224, "pal": 9, 
          "col": [ [255, 255, 255], [0, 0, 0], [0, 0, 0] ] 
        },
        
        # Segment 4: The Air Curtain
        { "id": 4, "on": True, "bri": 255, "fx": 83, "sx": 128, "ix": 128, "pal": 59, "col": [ [255, 255, 255], [0, 0, 0], [0, 0, 0] ] },
        
        # Segment 5: PWM Output
        { "id": 5, "on": True },
        
        # Segment 6 & 7: Relays
        { "id": 6, "on": True },
        { "id": 7, "on": True }
      ]
    }
    
    # 5. CONSOLE LOGGING
    mode_name = "NIGHT" if is_night else "DAY"
    print(f"[{mode_name}] Pos: {target_x}/255 | Alt: {alt:.1f}° | Temp: {temp}°C | Bri: {global_bri}/255")
    if is_night: print(f"Moon Phase: {moon_phase*100:.1f}%")
    print(f"Clouds: {clouds}% | Sky: {sky_color} | CloudColor: {cloud_color} | Sun/Moon Alpha: {sun_alpha}")
    
    # 6. PUSH TO MQTT
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        publish_result = client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
        publish_result.wait_for_publish(timeout=10)
        print("Successfully published to MQTT.")
    except Exception as e:
        print(f"MQTT Connection failed: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_sky_engine()
