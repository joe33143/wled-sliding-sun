def lerp(a, b, t):
    return a + (b - a) * t

def get_night_payload(moon_phase, clouds, is_stormy):
    sun_color = [200, 220, 255] # Pale Lunar Blue
    base_moon_alpha = int(lerp(30, 200, moon_phase)) 
    
    # Stop double-dimming: give the LEDs enough RGB data to actually dither!
    if is_stormy or clouds > 75:
        sun_alpha = 0 
        cloud_color = [25, 25, 30]  # Dark slate/blue, high enough to render
        sky_color = [0, 0, 0]       # Pitch black sky
        global_bri = 100            # Master dimming keeps the room dark
        
    elif clouds <= 35:
        sun_alpha = base_moon_alpha
        cloud_color = [35, 35, 45]  # Moonlit clouds
        sky_color = [15, 15, 25]    # Deep midnight blue sky
        global_bri = 150
        
    else:
        sun_alpha = int(base_moon_alpha * 0.5)
        cloud_color = [30, 30, 40]
        sky_color = [8, 8, 15]
        global_bri = 120
        
    return global_bri, sun_color, sky_color, cloud_color, sun_alpha
