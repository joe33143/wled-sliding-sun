import os
import time
import json
import math
import requests
import datetime
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
def lerp(a, b, t):
    return a + (b - a) * t

def get_temperature_color(temp):
    if temp <= 15: return [0, 255, 255]       
    if temp <= 25: return [255, 255, 0]       
    if temp <= 35: return [255, 140, 0]       
    return [255, 0, 0]                        

def calculate_sun_position(now, sunrise, sunset):
    if now < sunrise: return 0    
    if now > sunset: return 255   
    day_duration = (sunset - sunrise).total_seconds()
    time_elapsed = (now - sunrise).total_seconds()
    return int((time_elapsed / day_duration) * 255)

def get_solar_altitude():
    observer = ephem.Observer()
    observer.lat, observer.lon = str(LAT), str(LON)
    observer.date = datetime.datetime.now(pytz.utc)
    sun_ephem = ephem.Sun()
    sun_ephem.compute(observer)
    return math.degrees(sun_ephem.alt)

def calculate_base_day_colors(altitude_deg, clouds):
    c = clouds / 100.0
    keys = [
        (-6,   35,  45,  75,   0),  
        (0,   120, 110, 140,  18),  
        (10,  190, 185, 205,  40),  
        (35,  240, 235, 235, 100),  
        (55,  255, 250, 245, 160),  
        (90,  255, 255, 255, 200)   
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
    r = int(max(0, min(255, r * dim)))
    g = int(max(0, min(255, g * dim)))
    b = int(max(0, min(255, b * dim)))
    return [r, g, b]

# --- MAIN LOGIC ---
def run_sky_engine():
    # 1. Math & Positioning
    city = LocationInfo("Varanasi", "India", TIMEZONE, LAT, LON)
    s = sun(city.observer, date=datetime.date.today(), tzinfo=city.timezone)
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    
    target_x = calculate_sun_position(now, s["sunrise"], s["sunset"])
    alt = get_solar_altitude()
    
    # 2. Fetch Live Weather
    url = f"https://www.meteosource.com/api/v1/free/point?place_id=varanasi&sections=current&language=en&units=metric&key={METEOSOURCE_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        temp = data['current']['temperature']
        clouds = data['current']['cloud_cover'] 
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        temp, clouds = 25, 0
        
    sun_color = get_temperature_color(temp)
    sky_color = calculate_base_day_colors(alt, clouds)
        
    # 3. Build Payload
    payload = {
      "on": True, "bri": 255, "transition": 200, "live": True,             
      "seg": [
        {
          "id": 0, "fx": 142, "sx": target_x, "ix": 0,
          "c1": int(clouds * 2.55),  
          "col": [ sun_color, sky_color, [0, 0, 0] ]
        },
        { "id": 3, "on": True },
        { "id": 4, "on": True }
      ]
    }
    
    print(f"Time: {now.strftime('%H:%M')} | Pos: {target_x}/255 | Alt: {alt:.1f}° | Sky: {sky_color} | Clouds: {clouds}%")
    
    # 4. Push to MQTT
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
