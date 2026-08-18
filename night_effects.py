def lerp(a, b, t):
    return a + (b - a) * t

def get_night_payload(moon_phase, clouds, is_stormy):
    sun_color = [200, 220, 255] # Pale Lunar Blue
    base_moon_alpha = int(lerp(30, 200, moon_phase)) 
    
    if is_stormy or clouds > 75:
        sun_alpha = 0 
        cloud_color = [2, 2, 3] 
        sky_color = [0, 0, 0]
        global_bri = 80
    elif clouds <= 35:
        sun_alpha = base_moon_alpha
        cloud_color = [6, 6, 8]
        sky_color = [2, 2, 5] 
        global_bri = 120
    else:
        sun_alpha = int(base_moon_alpha * 0.5)
        cloud_color = [4, 4, 6]
        sky_color = [1, 1, 3]
        global_bri = 100
        
    return global_bri, sun_color, sky_color, cloud_color, sun_alpha
