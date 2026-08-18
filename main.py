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

def calculate_dynamic_sky_colors(altitude_deg, temp, clouds):
    # 1. Base Altitude Gradient
    keys = [
        (-6,   15,   25,   60),   # Deep twilight blue
        (0,   255,  100,   50),   # Sunrise/Sunset
        (10,   80,  160,  255),   # Morning/Evening
        (35,   20,  120,  255),   # Daytime
        (55,    5,   90,  255),   # High Sun
        (90,    0,   70,  255)    # Zenith
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

    # 2. Temperature Modification (Heat Haze vs Crisp Cold)
    # Assumes 25°C is a "neutral" baseline sky.
    temp_diff = temp - 25.0
    r += (temp_diff * 1.5)  # Warmer days get redder/hazier
    b -= (temp_diff * 1.5)

    # 3. Cloud Desaturation (Grey-shifting)
    # The more clouds there are, the more the sky loses its vivid color and turns grey.
    c_ratio = clouds / 100.0
    grey_val = (r + g + b) / 3.0
    desat_strength = c_ratio * 0.85 # Max 85% desaturation on fully overcast days
    
    r = r + (grey_val - r) * desat_strength
    g = g + (grey_val - g) * desat_strength
    b = b + (grey_val - b) * desat_strength
    
    # Clamp final values safely within 0-255
    r = int(max(0, min(255, r)))
    g = int(max(0, min(255, g)))
    b = int(max(0, min(255, b)))
    
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
        temp = data['current']['temperature']
        summary = data['current']['summary'].lower()
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        clouds, temp, summary = 0, 25.0, "clear"
        
    is_stormy = "thunder" in summary or "storm" in summary
        
    # 3. DESIGN BRACKET LOGIC
    # Warm Sun base
    sun_color = [255, 241, 224] 
    if alt < 15:
        progress = max(0, min(1, alt / 15.0))
        sun_color = [255, int(lerp(140, 241, progress)), int(lerp(0, 224, progress))]
        
    # Apply dynamic weather API math to the sky
    sky_color = calculate_dynamic_sky_colors(alt, temp, clouds)
    global_bri = 255
    
    if is_stormy or clouds > 75:
        # Overcast/Storm: Clouds swallow the sky, pushing towards pitch black
        progress = min(1.0, max(0.0, (clouds - 75) / 25.0))
        sun_alpha = int(lerp(100, 0, progress))
        global_bri = int(lerp(160, 100, progress)) if not is_stormy else 80
        cloud_color = [5, 5, 5]     # Near black for maximum doom
        sky_color = [int(c * 0.4) for c in sky_color] # Crush the sky brightness behind the storm
        
    elif clouds <= 35:
        # Clear Day: Vivid sky, rare dark cloudy flares cutting the background
        sun_alpha = 255
        cloud_color = [25, 25, 25]  # ~10% white for deep cuts
        
    else:
        # Partly Cloudy: Sun fades, clouds get darker and larger
        progress = (clouds - 35) / 40.0
        sun_alpha = int(lerp(255, 100, progress))
        global_bri = int(lerp(255, 160, progress))
        cloud_color = [15, 15, 15]  # Very dark grey

    # 4. Build Payload
    payload = {
      "on": True, "bri": global_bri, "transition": 200, "live": True,             
      "seg": [
        {
          "id": 0, "fx": 142, "pal": 0,
          "sx": target_x,              
          "ix": int(clouds * 2.55),    
          "c1": sun_alpha,             
          "col": [ sun_color, sky_color, cloud_color ]
        },
        { "id": 3, "on": True },
        { "id": 4, "on": True }
      ]
    }
    
    print(f"Pos: {target_x}/255 | Alt: {alt:.1f}° | Temp: {temp}°C")
    print(f"Clouds: {clouds}% | Sky: {sky_color} | CloudColor: {cloud_color} | Sun Alpha: {sun_alpha}")
    
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
