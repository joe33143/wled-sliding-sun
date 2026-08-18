import os
import time
import json
import requests
import datetime
import paho.mqtt.client as mqtt
from astral import LocationInfo
from astral.sun import sun
import pytz

# --- GLOBALS & CONFIG ---
METEOSOURCE_API_KEY = os.getenv("METEOSOURCE_API_KEY")

MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("WLED_MQTT_TOPIC", "joe33143/wled-sky/api")
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")

LAT = 25.3176
LON = 83.0062
TIMEZONE = "Asia/Kolkata"

# --- HELPER FUNCTIONS ---
def get_temperature_color(temp):
    if temp <= 15: return [0, 255, 255]       # Cyan
    if temp <= 25: return [255, 255, 0]       # Yellow
    if temp <= 35: return [255, 140, 0]       # Orange
    return [255, 0, 0]                        # Red

def calculate_sun_position(now, sunrise, sunset):
    if now < sunrise: return 0    # Pre-dawn (Far Left)
    if now > sunset: return 255   # Post-dusk (Far Right)
    
    day_duration = (sunset - sunrise).total_seconds()
    time_elapsed = (now - sunrise).total_seconds()
    percentage = time_elapsed / day_duration
    
    return int(percentage * 255)

# --- MAIN LOGIC ---
def run_sky_engine():
    # 1. Calculate Sun Position
    # FIX: Changed LATITUDE/LONGITUDE to the correct variables LAT/LON
    city = LocationInfo("Varanasi", "India", TIMEZONE, LAT, LON)
    s = sun(city.observer, date=datetime.date.today(), tzinfo=city.timezone)
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    
    target_x = calculate_sun_position(now, s["sunrise"], s["sunset"])
    
    # 2. Fetch Live Weather
    url = f"https://www.meteosource.com/api/v1/free/point?place_id=varanasi&sections=current&language=en&units=metric&key={METEOSOURCE_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        temp = data['current']['temperature']
        clouds = data['current']['cloud_cover'] # Grab cloud percentage for the C++ Perlin noise
        target_color = get_temperature_color(temp)
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        temp = "Unknown"
        clouds = 0
        target_color = [255, 179, 0] # Fallback Amber
        
    # 3. Build WLED JSON Payload
    payload = {
      "on": True,
      "bri": 255,
      "transition": 200,             
      "live": True,             # <-- REPLACED THE TIMESTAMP WITH A SIMPLE BOOLEAN
      "seg": [
        {
          "id": 0,             
          "fx": 142,                 # Changed to 142 per your request
          "sx": target_x,      
          "ix": 0,
          "c1": int(clouds * 2.55),  # Convert 0-100% cloud cover to 0-255 slider for C++
          "col": [
            target_color,      
            [0, 0, 0],         
            [0, 0, 0]
          ]
        },
        # Relay Failsafes (Prevents feed mode from getting stuck)
        { "id": 3, "on": True },
        { "id": 4, "on": True }
      ]
    }
    
    print(f"Time: {now.strftime('%H:%M')} | Pos: {target_x}/255 | Temp: {temp}°C | Clouds: {clouds}%")
    print(f"Payload: {json.dumps(payload)}")
    
    # 4. Push to MQTT
    # FIX: Corrected all indentation and added the actual publish command
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
        if "hivemq.cloud" in MQTT_BROKER:
            client.tls_set()
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        
        # ACTUALLY PUBLISH THE DATA
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
