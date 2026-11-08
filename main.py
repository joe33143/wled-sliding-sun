import datetime
from zoneinfo import ZoneInfo
import json
import math
import os
import ephem
from astral import LocationInfo
from astral.sun import sun
import paho.mqtt.publish as publish
import requests

# --- GLOBALS & CONFIG ---
METEOSOURCE_API_KEY = os.getenv("METEOSOURCE_API_KEY")
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "joe33143/reef/api"
LAT = 25.3176
LON = 83.0062
TIMEZONE = "Asia/Kolkata"
TZ = ZoneInfo(TIMEZONE)


# --- HELPER FUNCTIONS ---
def clamp(val, min_val=0, max_val=255):
    return max(min_val, min(max_val, val))


def lerp(a, b, t):
    t = clamp(t, 0.0, 1.0)
    return int(a + (b - a) * t)


def lerp_color(c1, c2, t):
    return [lerp(c1[i], c2[i], t) for i in range(3)]


def calculate_progress(now, start_time, end_time):
    duration = (end_time - start_time).total_seconds()
    if duration <= 0:
        return 1.0
    elapsed = (now - start_time).total_seconds()
    return clamp(elapsed / duration, 0.0, 1.0)


# --- ATMOSPHERIC MATH ---
def get_base_hues(altitude_deg, clouds, turbidity=5.0):
    c = clouds / 100.0
    keys = [
        (-6,  35,  45,  75),
        (0,   120, 110, 140),
        (10,  190, 185, 205),
        (35,  240, 235, 235),
        (55,  255, 250, 245),
        (90,  255, 255, 255),
    ]
    
    if altitude_deg <= keys[0][0]:
        r, g, b = keys[0][1:]
    elif altitude_deg >= keys[-1][0]:
        r, g, b = keys[-1][1:]
    else:
        for i in range(len(keys) - 1):
            if keys[i][0] <= altitude_deg <= keys[i + 1][0]:
                k1, k2 = keys[i], keys[i + 1]
                t = (altitude_deg - k1[0]) / (k2[0] - k1[0])
                r, g, b = lerp_color(k1[1:], k2[1:], t)
                break

    dim = 1.0 - (c * 0.5)
    r = (r * dim) + (turbidity * 3.5)
    g = (g * dim) + (turbidity * 2.5)
    b = (b * dim) - (turbidity * 1.5)

    return [int(clamp(r)), int(clamp(g)), int(clamp(b))]


def get_sun_color(alt):
    if alt < -2:
        return [0, 0, 0]
    if alt < 15:
        progress = (alt + 2) / 17.0
        return lerp_color([100, 10, 0], [255, 241, 224], progress)
    return [255, 241, 224]


def fetch_weather():
    if not METEOSOURCE_API_KEY:
        print("Warning: METEOSOURCE_API_KEY not set. Using defaults.")
        return 0, 25.0, "clear"

    url = "https://www.meteosource.com/api/v1/free/point"
    params = {
        "place_id": "varanasi",
        "sections": "current",
        "language": "en",
        "units": "metric",
        "key": METEOSOURCE_API_KEY,
    }
    try:
        # 10-second timeout prevents GitHub Actions runners from hanging indefinitely
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        current = response.json()["current"]
        return (
            current["cloud_cover"],
            current["temperature"],
            current["summary"].lower(),
        )
    except Exception as e:
        print(f"Weather Fetch Failed: {e}")
        return 0, 25.0, "clear"


# --- MAIN LOGIC ---
def run_sky_engine():
    # Force localized timezone awareness so UTC GitHub runners calculate correct IST dates/times
    now = datetime.datetime.now(TZ)
    now_time = now.time()
    time_float = now.hour + (now.minute / 60.0) + (now.second / 3600.0)

    # 1. Astronomy Calculations (Derived from localized now.date())
    city = LocationInfo("Varanasi", "India", TIMEZONE, LAT, LON)
    s_today = sun(city.observer, date=now.date(), tzinfo=TZ)
    sunrise_time = s_today["sunrise"]
    sunset_time = s_today["sunset"]

    observer = ephem.Observer()
    observer.lat, observer.lon = str(LAT), str(LON)
    observer.date = now.astimezone(datetime.timezone.utc)

    sun_ephem = ephem.Sun(observer)
    alt = math.degrees(sun_ephem.alt)

    moon_ephem = ephem.Moon(observer)
    moon_phase = moon_ephem.phase / 100.0 
    moon_az = math.degrees(moon_ephem.az)
    moon_pos = lerp(0, 255, (moon_az - 90) / 180.0)

    # 2. Weather & Contrast Multipliers
    clouds, temp, summary = fetch_weather()
    is_stormy = "thunder" in summary or "storm" in summary
    is_noon_blast = 11.0 <= time_float < 13.0

    if is_stormy:
        sky_mult, cloud_mult = 0.3, 0.7
        weather_master_target = 130
        day_active_alpha = 0
    elif clouds >= 75:
        sky_mult, cloud_mult = 0.5, 0.8
        weather_master_target = 200
        day_active_alpha = lerp(150, 50, (clouds - 75) / 25.0)
    elif clouds >= 50:
        t_c = (clouds - 50) / 25.0
        sky_mult = 0.7 - (0.2 * t_c)
        cloud_mult = 0.6 + (0.2 * t_c)
        weather_master_target = lerp(230, 200, t_c)
        day_active_alpha = lerp(255, 150, t_c)
    else:
        t_c = clouds / 50.0
        sky_mult = 1.0 - (0.3 * t_c)
        cloud_mult = 0.4 + (0.2 * t_c)
        weather_master_target = lerp(255, 230, t_c)
        day_active_alpha = 255

    # 3. Independent Bamboo Light Logic
    bamboo_target = 255
    bamboo_sunrise_end = sunrise_time + datetime.timedelta(minutes=30)
    bamboo_sunset_end = sunset_time + datetime.timedelta(minutes=30)

    if now < sunrise_time or now >= bamboo_sunset_end:
        bamboo_bri, bamboo_on = 0, False
    elif now <= bamboo_sunrise_end:
        bamboo_bri = lerp(0, bamboo_target, calculate_progress(now, sunrise_time, bamboo_sunrise_end))
        bamboo_on = True
    elif now >= sunset_time:
        bamboo_bri = lerp(bamboo_target, 0, calculate_progress(now, sunset_time, bamboo_sunset_end))
        bamboo_on = True
    else:
        bamboo_bri, bamboo_on = bamboo_target, True

    # 4. Phase Routing
    if now_time >= datetime.time(21, 30) or now_time < datetime.time(4, 0):
        phase = "SLEEP"
    elif now_time < sunrise_time.time():
        phase = "MORNING_RAMP"
    elif now < sunset_time:
        phase = "DAY"
    elif now <= sunset_time + datetime.timedelta(minutes=30):
        phase = "SUNSET_FADE"
    elif now_time < datetime.time(20, 30):
        phase = "EVENING_LOCKED"
    else:
        phase = "NIGHT_FADE"

    # 5. Calculate Phase Values
    seg0_on, seg2_on, seg4_on = True, False, False
    ab_r, ab_g, ab_b = 0, 0, 0
    ab_fx = 169
    seg4_col = [255, 255, 255, 0]
    seg4_fx = 83
    seg4_bri = 0
    turbidity = 5.0

    evening_c_bri = lerp(80, 140, moon_phase)

    if phase == "SLEEP":
        master_bri = 116
        c_bri, target_x, c_ix, active_alpha = 0, 0, 0, 0
        c_sky, c_cloud, c_sun = [0, 0, 0], [0, 0, 0], [0, 0, 0]
        seg0_on = False

    elif phase == "MORNING_RAMP":
        morning_start = now.replace(hour=4, minute=0, second=0, microsecond=0)
        t = calculate_progress(now, morning_start, sunrise_time)

        master_bri = lerp(0, 18, t**3)
        c_bri = 255
        target_x = lerp(0, 128, t)

        raw_hues = get_base_hues(min(0.0, alt), clouds, turbidity)
        c_sky = [int(c * sky_mult) for c in raw_hues]
        c_cloud = [int(c * cloud_mult) for c in raw_hues]
        c_sun = get_sun_color(alt)

        c_ix = int(clouds * 2.55)
        active_alpha = lerp(0, day_active_alpha, t)

    elif phase == "DAY":
        target_x = int(calculate_progress(now, sunrise_time, sunset_time) * 255)
        raw_hues = get_base_hues(alt, clouds, turbidity)

        c_sky = [int(c * sky_mult) for c in raw_hues]
        c_cloud = [int(c * cloud_mult) for c in raw_hues]
        c_sun = get_sun_color(alt)
        active_alpha = day_active_alpha

        eight_am = now.replace(hour=8, minute=0, second=0, microsecond=0)
        pre_sunset_start = sunset_time - datetime.timedelta(minutes=90)

        if now < eight_am:
            ramp_t = calculate_progress(now, sunrise_time, eight_am)
            master_bri = lerp(18, weather_master_target, ramp_t)
            c_bri = 255
        else:
            seg4_on = True
            seg4_bri = 255
            if now > pre_sunset_start:
                fade_t = calculate_progress(now, pre_sunset_start, sunset_time)
                master_bri = lerp(weather_master_target, 150, fade_t)
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
            ab_peak = 204 - int((min(clouds, 75) / 75.0) * 77)
            ab_base = 0
            ab_active_alpha = active_alpha

            if 100 <= target_x <= 155:
                ab_base = ab_peak
                ab_active_alpha = 255
            elif 30 <= target_x < 100:
                ab_base = int(((target_x - 30) / 70.0) * ab_peak)
            elif 155 < target_x <= 225:
                ab_base = int(ab_peak * (1.0 - ((target_x - 155) / 70.0)))

            if now >= eight_am:
                ab_val = int((ab_base * ab_active_alpha) / 255)
                ab_r = ab_g = ab_b = ab_val

            c_ix = int(clouds * 2.55)

        seg2_on = any([ab_r, ab_g, ab_b])

    elif phase == "SUNSET_FADE":
        sunset_end = sunset_time + datetime.timedelta(minutes=30)
        t = calculate_progress(now, sunset_time, sunset_end)

        master_bri = lerp(150, 255, t)
        c_bri = lerp(255, evening_c_bri, t)
        target_x = lerp(255, moon_pos, t)
        active_alpha = lerp(day_active_alpha, 255, t)

        raw_hues = get_base_hues(alt, clouds, turbidity)
        c_sky = lerp_color([int(c * sky_mult) for c in raw_hues], [5, 5, 10], t)
        c_cloud = lerp_color([int(c * cloud_mult) for c in raw_hues], [20, 25, 30], t)
        c_sun = lerp_color(get_sun_color(alt), [140, 145, 150], t)
        c_ix = lerp(int(clouds * 2.55), 153, t)

        seg4_on = True
        seg4_bri = lerp(255, 80, t)

    elif phase == "EVENING_LOCKED":
        master_bri = 255
        c_bri = evening_c_bri
        target_x = moon_pos
        c_ix = 153
        active_alpha = 255
        c_sky, c_cloud, c_sun = [5, 5, 10], [20, 25, 30], [140, 145, 150]
        seg4_on = True
        seg4_bri = 80

    elif phase == "NIGHT_FADE":
        fade_start = now.replace(hour=20, minute=30, second=0, microsecond=0)
        fade_end = now.replace(hour=21, minute=30, second=0, microsecond=0)
        t = calculate_progress(now, fade_start, fade_end)

        master_bri = 255
        c_bri = lerp(evening_c_bri, 0, t)
        target_x = moon_pos
        c_ix = 153
        active_alpha = 255
        c_sky, c_cloud, c_sun = [5, 5, 10], [20, 25, 30], [140, 145, 150]
        seg4_on = True
        seg4_bri = lerp(80, 0, t)

    # 6. Build WLED Payload
    payload = {
        "on": True,
        "bri": master_bri,
        "transition": 70,
        "mainseg": 4,
        "seg": [
            {
                "id": 0, "on": seg0_on, "bri": c_bri,
                "col": [c_sky + [0], c_cloud + [0], c_sun + [0]],
                "cct": 127, "fx": 142, "sx": target_x, "ix": c_ix, "c1": active_alpha,
            },
            {
                "id": 1, "on": False, "bri": 116,
                "col": [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
                "cct": 127, "fx": 0, "sx": 166, "ix": 152,
            },
            {
                "id": 2, "on": seg2_on, "bri": 255,
                "col": [[ab_r, ab_g, ab_b, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
                "cct": 127, "fx": ab_fx, "sx": 128, "ix": 128,
            },
            {
                "id": 3, "on": bamboo_on, "bri": bamboo_bri,
                "col": [[200, 200, 200, 200], [0, 0, 0, 0], [0, 0, 0, 0]],
                "cct": 127, "fx": 0, "sx": 128, "ix": 128, "lc": 2,
            },
            {
                "id": 4, "on": seg4_on, "bri": seg4_bri,
                "col": [seg4_col, [0, 0, 0, 0], [0, 0, 0, 0]],
                "cct": 127, "fx": seg4_fx, "sx": 128, "ix": 128,
            },
        ],
    }

    # 7. Publish to MQTT (Single-shot execution ideal for ephemeral runners)
    print(f"[{phase}] Time: {now.strftime('%H:%M:%S')} | Alt: {alt:.2f}° | Master Bri: {master_bri} | Seg0 Bri: {c_bri}")
    try:
        publish.single(
            MQTT_TOPIC,
            payload=json.dumps(payload),
            qos=1,
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
            client_id=f"joe33143_sky_{int(time.time())}",
            timeout=10,
        )
        print("Successfully published payload.")
    except Exception as e:
        print(f"MQTT Publish failed: {e}")


if __name__ == "__main__":
    run_sky_engine()
