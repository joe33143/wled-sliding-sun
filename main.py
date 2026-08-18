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

def get_white_balance_rgb(temp_c):
    # Map 0°C (Cold) to 9000K (Crisp Blue)
    # Map 45°C (Scorching) to 4500K (Warm Haze)
    clamped_temp = max(0, min(45, temp_c))
    kelvin = 9000 - ((clamped_temp / 45.0) * 4500)
    
    # Standard algorithm to convert Kelvin to RGB
    temp_k = kelvin / 100.0
    
    r = 255 if temp_k <= 66 else max(0, min(255, 329.6987 * ((temp_k - 60) ** -0.1332)))
    g = max(0, min(255, 99.4708 * math.log(temp_k) - 161.1195)) if temp_k <= 66 else max(0, min(255, 288.1221 * ((temp_k - 60) ** -0.0755)))
    b = 255 if temp_k >= 66 else (0 if temp_k <= 19 else max(0, min(255, 138.5177 * math.log(temp_k - 10) - 305.0447)))
    
    return [int(r), int(g), int(b)]

def calculate_dynamic_sky_colors(altitude_deg, temp, clouds):
    # 1. Base Altitude Gradient (Pure, neutral base colors)
    keys = [
        (-6,   15,   25,   60),   # Deep twilight
        (0,   255,  100,   50),   # Sunrise/Sunset
        (10,   80,  160,  255),   # Morning/Evening
        (35,  255,  255,  255),   # Daytime (Set to pure white so WB tint takes over!)
        (55,  255,  255,  255),   # High Sun 
        (90,  255,  255,  255)    # Zenith
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

    # 2. Apply Photographic White Balance
    wb_tint = get_white_balance_rgb(temp)
    r = (r * wb_tint[0]) / 255.0
    g = (g * wb_tint[1]) / 255.0
    b = (b * wb_tint[2]) / 255.0

    # 3. Cloud Desaturation (Grey-shifting)
    c_ratio = clouds / 100.0
    grey_val = (r + g + b) / 3.0
    desat_strength = c_ratio * 0.90 
    
    r = r + (grey_val - r) * desat_strength
    g = g + (grey_val - g) * desat_strength
    b = b + (grey_val - b) * desat_strength
    
    return [int(max(0, min(255, r))), int(max(0, min(255, g))), int(max(0, min(255, b)))]

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
    
    if is_stormy or clouds > 75:
        # Overcast/Storm: Clouds swallow the sky, but keep LEDs powered!
        progress = min(1.0, max(0.0, (clouds - 75) / 25.0))
        sun_alpha = int(lerp(100, 0, progress))
        global_bri = int(lerp(200, 150, progress)) if not is_stormy else 130
        cloud_color = [15, 15, 15]     
        # Removed the aggressive sky_color * 0.4 crush! Let the Kelvin + Desaturation do the work.
        
    elif clouds <= 35:
        # Clear Day: Vivid sky, stark dark cuts
        sun_alpha = 255
        global_bri = 255
        cloud_color = [27, 27, 27]  # ~#1b1b1b
        
    else:
        # Partly Cloudy: Sun fades, clouds get slightly darker
        progress = (clouds - 35) / 40.0
        sun_alpha = int(lerp(255, 100, progress))
        global_bri = int(lerp(255, 200, progress))
        cloud_color = [20, 20, 20] 

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
    
    # 5. Restored Console Logging (Now includes Global Brightness!)
    print(f"Pos: {target_x}/255 | Alt: {alt:.1f}° | Temp: {temp}°C | Bri: {global_bri}/255")
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
