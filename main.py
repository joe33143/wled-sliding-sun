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

def lerp(a, b, t):
    return int(a + (b - a) * t)

def lerp_color(c1, c2, t):
    return [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)]

# --- ATMOSPHERIC MATH ---
def get_base_hues(altitude_deg, clouds, turbidity=5.0):
    c = clouds / 100.0
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
    r = lerp(k1[1], k2[1], t)
    g = lerp(k1[2], k2[2], t)
    b = lerp(k1[3], k2[3], t)

    dim = 1.0 - (c * 0.5)
    r *= dim; g *= dim; b *= dim
    r += (turbidity * 3.5); g += (turbidity * 2.5); b -= (turbidity * 1.5)
    
    return [int(max(0, min(255, r))), int(max(0, min(255, g))), int(max(0, min(255, b)))]

def get_sun_color(alt):
    if alt < -2:
        return [0, 0, 0]
    elif alt < 15:
        progress = max(0.0, min(1.0, (alt + 2) / 17.0))
        return [int(lerp(100, 255, progress)), int(lerp(10, 241, progress)), int(lerp(0, 224, progress))]
    return [255, 241, 224]

# --- MAIN LOGIC ---
def run_sky_engine():
    city = LocationInfo("Varanasi", "India", TIMEZONE, LAT, LON)
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    now_time = now.time()
    time_float = now.hour + (now.minute / 60.0) + (now.second / 3600.0)
    
    s_today = sun(city.observer, date=datetime.date.today(), tzinfo=city.timezone)
    sunrise_time = s_today["sunrise"]
    sunset_time = s_today["sunset"]
    
    observer = ephem.Observer()
    observer.lat, observer.lon = str(LAT), str(LON)
    observer.date = datetime.datetime.now(pytz.utc)
    
    sun_ephem = ephem.Sun()
    sun_ephem.compute(observer)
    alt = math.degrees(sun_ephem.alt)
    
    moon_ephem = ephem.Moon()
    moon_ephem.compute(observer)
    moon_phase = moon_ephem.phase / 100.0 
    
    moon_az = math.degrees(moon_ephem.az)
    moon_pos = int(lerp(0, 255, (moon_az - 90) / 180.0))
    moon_pos = max(0, min(255, moon_pos))
    moon_alpha = int(12.75 + (114.75 * moon_phase)) 
    
    try:
        url = f"https://www.meteosource.com/api/v1/free/point?place_id=varanasi&sections=current&language=en&units=metric&key={METEOSOURCE_API_KEY}"
        response = requests.get(url)
        data = response.json()
        clouds = data['current']['cloud_cover'] 
        temp = data['current']['temperature']
        summary = data['current']['summary'].lower()
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        clouds, temp, summary = 0, 25.0, "clear"
        
    is_stormy = "thunder" in summary or "storm" in summary
    is_noon_blast = (11.0 <= time_float < 13.0)

    # --- DYNAMIC CONTRAST MULTIPLIERS ---
    if is_stormy:
        sky_mult, cloud_mult = 0.3, 0.7
        weather_master_target = 130
        day_active_alpha = 0
    elif clouds >= 75:
        sky_mult, cloud_mult = 0.5, 0.8
        weather_master_target = 200
        day_active_alpha = int(lerp(150, 50, (clouds - 75)/25.0))
    elif clouds >= 50:
        t_c = (clouds - 50) / 25.0
        sky_mult = 0.7 - (0.2 * t_c) 
        cloud_mult = 0.6 + (0.2 * t_c) 
        weather_master_target = int(lerp(230, 200, t_c))
        day_active_alpha = int(lerp(255, 150, t_c))
    else:
        t_c = clouds / 50.0
        sky_mult = 1.0 - (0.3 * t_c) 
        cloud_mult = 0.4 + (0.2 * t_c) 
        weather_master_target = int(lerp(255, 230, t_c))
        day_active_alpha = 255

    # ==========================================
    # INDEPENDENT BAMBOO LIGHT LOGIC
    # ==========================================
    bamboo_target = 255 
    bamboo_sunrise_end = sunrise_time + datetime.timedelta(minutes=30)
    bamboo_sunset_end = sunset_time + datetime.timedelta(minutes=30)
    
    if now < sunrise_time or now >= bamboo_sunset_end:
        bamboo_bri = 0
        bamboo_on = False
    elif sunrise_time <= now <= bamboo_sunrise_end:
        t = (now - sunrise_time).total_seconds() / 1800.0
        bamboo_bri = lerp(0, bamboo_target, t)
        bamboo_on = True
    elif sunset_time <= now <= bamboo_sunset_end:
        t = (now - sunset_time).total_seconds() / 1800.0
        bamboo_bri = lerp(bamboo_target, 0, t)
        bamboo_on = True
    else:
        bamboo_bri = bamboo_target
        bamboo_on = True

    # ==========================================
    # TIME-BASED PHASE ROUTING 
    # ==========================================
    if datetime.time(22, 0) <= now_time or now_time < datetime.time(4, 0):
        phase = "SLEEP"
    elif datetime.time(4, 0) <= now_time < sunrise_time.time():
        phase = "MORNING_RAMP"
    elif now < sunset_time:
        phase = "DAY"
    elif now <= sunset_time + datetime.timedelta(minutes=30):
        phase = "SUNSET_FADE"
    elif now_time < datetime.time(21, 0):
        phase = "EVENING_LOCKED"
    else:
        phase = "NIGHT_SKY"

    # ==========================================
    # CALCULATE PHASE VALUES
    # ==========================================
    seg0_on, seg2_on, seg4_on = True, False, False
    ab_r, ab_g, ab_b = 0, 0, 0
    ab_fx = 169  
    seg4_col = [255, 255, 255, 0]
    seg4_fx = 83
    seg4_bri = 0
    turbidity = 5.0
    
    if phase == "SLEEP":
        master_bri = 116
        c_bri, target_x, c_ix, active_alpha = 0, 0, 0, 0
        c_sky, c_cloud, c_sun = [0,0,0], [0,0,0], [0,0,0]
        seg0_on, seg2_on, seg4_on = False, False, False

    elif phase == "MORNING_RAMP":
        morning_start = now.replace(hour=4, minute=0, second=0)
        t = max(0.0, min(1.0, (now - morning_start).total_seconds() / (sunrise_time - morning_start).total_seconds()))
        
        master_bri = lerp(0, 18, t ** 3) 
        c_bri = 255
        target_x = lerp(0, 128, t)
        
        clamped_alt = min(0.0, alt)
        raw_hues = get_base_hues(clamped_alt, clouds, turbidity)
        
        c_sky = [int(c * sky_mult) for c in raw_hues]
        c_cloud = [int(c * cloud_mult) for c in raw_hues] 
        c_sun = get_sun_color(alt)
        
        c_ix = int(clouds * 2.55)
        active_alpha = lerp(0, day_active_alpha, t)
        seg4_on = False

    elif phase == "DAY":
        target_x = calculate_position(now, sunrise_time, sunset_time)
        raw_hues = get_base_hues(alt, clouds, turbidity)
        
        c_sky = [int(c * sky_mult) for c in raw_hues]
        c_cloud = [int(c * cloud_mult) for c in raw_hues]
        c_sun = get_sun_color(alt)
        active_alpha = day_active_alpha
            
        eight_am = now.replace(hour=8, minute=0, second=0, microsecond=0)
        time_to_sunset = (sunset_time - now).total_seconds()
        
        if now < eight_am:
            ramp_t = max(0.0, min(1.0, (now - sunrise_time).total_seconds() / (eight_am - sunrise_time).total_seconds()))
            master_bri = int(lerp(18, weather_master_target, ramp_t))
            c_bri = 255
            seg4_on = False
            seg4_bri = 0
        else:
            seg4_on = True
            seg4_bri = 255
            if time_to_sunset < 5400:  
                fade_t = max(0.0, time_to_sunset / 5400.0)
                master_bri = int(lerp(150, weather_master_target, fade_t))
                c_bri = int(lerp(200, 255, fade_t))
            else:
                master_bri = weather_master_target
                c_bri = 255
        
        if is_noon_blast:
            master_bri = 255
            c_bri = 90  
            active_alpha = 255
            c_ix = 0  
            ab_r, ab_g, ab_b = 153, 204, 153  
            ab_fx = 0  
            seg4_col = [255, 0, 255, 0]       
            seg4_fx = 0
            seg4_bri = 255
        else:
            ab_fx = 169  
            ab_peak = 204 - int((min(clouds, 75) / 75.0) * 77)
            
            ab_base = 0
            if 100 <= target_x <= 155:
                ab_base = ab_peak
                ab_active_alpha = 255
            else:
                ab_active_alpha = active_alpha
                if 30 <= target_x < 100:
                    ab_base = int(((target_x - 30) / 70.0) * ab_peak)
                elif 155 < target_x <= 225:
                    fade = 1.0 - ((target_x - 155) / 70.0)
                    ab_base = int(ab_peak * fade)
                
            if now >= eight_am:
                ab_val = int((ab_base * ab_active_alpha) / 255)
                ab_r, ab_g, ab_b = ab_val, ab_val, ab_val
        
        seg2_on = (ab_r > 0 or ab_g > 0 or ab_b > 0)
        if not is_noon_blast: c_ix = int(clouds * 2.55)

    elif phase == "SUNSET_FADE":
        t = (now - sunset_time).total_seconds() / 1800.0  
        
        # INCREASED: Master and segment brightness floors raised for visibility
        master_bri = lerp(255, 150, t)
        c_bri = lerp(255, 200, t)
        
        target_x = lerp(255, moon_pos, t)
        active_alpha = lerp(day_active_alpha, moon_alpha, t)
        
        raw_hues = get_base_hues(alt, clouds, turbidity)
        
        c_sky = lerp_color([int(c * sky_mult) for c in raw_hues], [5, 5, 10], t)
        c_cloud = lerp_color([int(c * cloud_mult) for c in raw_hues], [20, 25, 30], t)
        c_sun = lerp_color(get_sun_color(alt), [140, 145, 150], t)
        
        c_ix = lerp(int(clouds * 2.55), 153, t)
        
        ab_r, ab_g, ab_b = 0, 0, 0
        seg2_on = False
        
        seg4_on = True
        seg4_bri = lerp(255, 180, t)

    elif phase == "EVENING_LOCKED":
        # INCREASED: Locks in at the new, higher visibility floor
        master_bri = 150
        c_bri = 200
        target_x = moon_pos
        c_ix = 153  
        active_alpha = moon_alpha
        
        c_sky = [5, 5, 10]
        c_cloud = [20, 25, 30]
        c_sun = [140, 145, 150]
        
        seg2_on = False
        
        seg4_on = True
        seg4_bri = 180

    elif phase == "NIGHT_SKY":
        master_bri = int(25.5 + (25.5 * (clouds / 100.0)))
        c_bri = 255 
        active_alpha = moon_alpha
        
        target_x = moon_pos
        c_ix = int(clouds * 2.55)
        
        c_sky = [5, 5, 10]
        c_cloud = [20, 25, 30]
        c_sun = [140, 145, 150] 
        
        seg2_on, seg4_on = False, False
        seg4_bri = 0

    # ====================================================
    # BUILD EXPLICIT 5-SEGMENT PAYLOAD 
    # ====================================================
    payload = {
        "on": True, 
        "bri": master_bri, 
        "transition": 70,
        "mainseg": 4, 
        "seg": [
            {
                "id": 0, 
                "on": seg0_on, 
                "bri": c_bri,
                "col": [c_sky + [0], c_cloud + [0], c_sun + [0]], 
                "cct": 127,
                "fx": 142, "sx": target_x, "ix": c_ix, "c1": active_alpha
            },
            {
                "id": 1, 
                "on": False, 
                "bri": 116, 
                "col": [[0,0,0,0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 0, "sx": 166, "ix": 152
            },
            {
                "id": 2, 
                "on": seg2_on,
                "bri": 255,
                "col": [[ab_r, ab_g, ab_b, 0], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": ab_fx, "sx": 128, "ix": 128
            },
            {
                "id": 3, 
                "on": bamboo_on,
                "bri": bamboo_bri,
                "col": [[200, 200, 200, 200], [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": 0, "sx": 128, "ix": 128, "lc": 2
            },
            {
                "id": 4, 
                "on": seg4_on,
                "bri": seg4_bri,
                "col": [seg4_col, [0,0,0,0], [0,0,0,0]], 
                "cct": 127,  
                "fx": seg4_fx, "sx": 128, "ix": 128
            }
        ]
    }

    # --- PUSH TO MQTT ---
    print(f"[{phase}] Time: {now.time()} | Alt: {alt:.2f} | Clouds: {clouds}% | Sky Mult: {sky_mult:.2f} | Sun Alpha: {active_alpha}")
    
    client_id = f"joe33143_sky_{int(time.time())}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() 
        publish_result = client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
        publish_result.wait_for_publish(timeout=10)
        print("Successfully published payload.")
    except Exception as e:
        print(f"MQTT Connection failed: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_sky_engine()
