import os
import json
import requests
import datetime
import paho.mqtt.client as mqtt
from astral import LocationInfo
from astral.sun import sun
import pytz

# --- SECRETS & CONFIGURATION ---
METEOSOURCE_API_KEY = os.environ.get("METEOSOURCE_API_KEY")
MQTT_BROKER = os.environ.get("MQTT_BROKER")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASS = os.environ.get("MQTT_PASS")
WLED_MQTT_TOPIC = os.environ.get("WLED_MQTT_TOPIC") # e.g., "wled/matrix/api"

LATITUDE = 25.3176
LONGITUDE = 82.9739
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
    city = LocationInfo("Varanasi", "India", TIMEZONE, LATITUDE, LONGITUDE)
    s = sun(city.observer, date=datetime.date.today(), tzinfo=city.timezone)
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    
    target_x = calculate_sun_position(now, s["sunrise"], s["sunset"])
    
    # 2. Fetch Live Weather
    url = f"https://www.meteosource.com/api/v1/free/point?place_id=varanasi&sections=current&language=en&units=metric&key={METEOSOURCE_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        temp = data['current']['temperature']
        target_color = get_temperature_color(temp)
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        temp = "Unknown"
        target_color = [255, 179, 0] # Fallback Amber
        
    # 3. Build WLED JSON Payload
    payload = {
      "seg": [
        {
          "id": 0,             
          "fx": "Sliding Sun", 
          "sx": target_x,      
          "col": [
            target_color,      
            [0, 0, 0]          
          ]
        }
      ]
    }
    
    print(f"Time: {now.strftime('%H:%M')} | Pos: {target_x}/255 | Temp: {temp}°C | Payload: {json.dumps(payload)}")
    
    # 4. Push to MQTT
    try:
        client = mqtt.Client()
        
        # Only set credentials if they actually exist in the GitHub Secrets
        if MQTT_USER and MQTT_PASS:
            client.username_pw_set(MQTT_USER, MQTT_PASS)
            
        # HiveMQ Cloud requires TLS/SSL on port 8883
        if MQTT_PORT == 8883:
            client.tls_set() 
        
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.publish(WLED_MQTT_TOPIC, json.dumps(payload))
        client.disconnect()
        print("Successfully published payload to HiveMQ Broker.")
    except Exception as e:
        print(f"MQTT Publish Failed: {e}")

if __name__ == "__main__":
    run_sky_engine()
