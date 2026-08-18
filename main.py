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

def calculate_base_day_colors(altitude_deg):
    # Calculates just the base sky background gradient
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
    r = int(lerp(k1[1], k2[1], t) * 0.45) # 0.45 keeps sky slightly darker than clouds
    g = int(lerp(k1[2], k2[2], t) * 0.45)
    b = int(lerp(k1[3], k2[3], t) * 0.45)
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
        clouds = data['current']['cloud_cover'] 
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        clouds = 0
        
    # 3. DESIGN BRACKET LOGIC
    # Base 5500K Warm Sun. (Gets slightly orange if altitude < 15)
    sun_color = [255, 241, 224] 
    if alt < 15:
        progress = max(0, min(1, alt / 15.0))
        sun_color = [255, int(lerp(140, 241, progress)), int(lerp(0, 224, progress))]
        
    sky_color = calculate_base_day_colors(alt)
    global_bri = 255
    
    if clouds <= 35:
        # Clear/Fair Day: Max Sun, Bright Fluffy White Clouds
        sun_alpha = 255
        cloud_color = [240, 240, 240]
        
    elif clouds <= 75:
        # Partly/Mostly Cloudy: Sun fades out, Clouds turn grey, Global dimming
        progress = (clouds - 35) / 40.0 # 0.0 to 1.0
        sun_alpha = int(lerp(255, 60, progress))
        global_bri = int(lerp(255, 160, progress))
        grey_val = int(lerp(240, 100, progress))
        cloud_color = [grey_val, grey_val, grey_val]
        
    else:
        # Overcast/Storm: Gloomy Mode, Sun completely hidden, Dark Storm Clouds
        progress = (clouds - 75) / 25.0
        sun_alpha = int(lerp(60, 0, progress))
        global_bri = int(lerp(160, 80, progress))
        cloud_color = [40, 40, 45]
        # Darken the sky behind the gloom
        sky_color = [int(c * 0.5) for c in sky_color]
        
    # 4. Build Payload
    payload = {
      "on": True, "bri": global_bri, "transition": 200, "live": True,             
      "seg": [
        {
          "id": 0, "fx": 142, "pal": 0,
          "sx": target_x,              # Slider 1: Target Position
          "ix": int(clouds * 2.55),    # Slider 2: Cloud Cover (Shifted)
          "c1": sun_alpha,             # Slider 3: Sun Alpha (Shifted)
          "col": [ sun_color, sky_color, cloud_color ]
        },
        { "id": 3, "on": True },
        { "id": 4, "on": True }
      ]
    }
    
    print(f"Pos: {target_x}/255 | Alt: {alt:.1f}° | Clouds: {clouds}% | Sun Alpha: {sun_alpha}/255 | Bri: {global_bri}")
    
    # 5. Push to MQTT
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
