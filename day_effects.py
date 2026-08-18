import math

def lerp(a, b, t):
    return a + (b - a) * t

def get_white_balance_rgb(temp_c):
    clamped_temp = max(0, min(45, temp_c))
    kelvin = 9000 - ((clamped_temp / 45.0) * 4500)
    temp_k = kelvin / 100.0
    
    r = 255 if temp_k <= 66 else max(0, min(255, 329.6987 * ((temp_k - 60) ** -0.1332)))
    g = max(0, min(255, 99.4708 * math.log(temp_k) - 161.1195)) if temp_k <= 66 else max(0, min(255, 288.1221 * ((temp_k - 60) ** -0.0755)))
    b = 255 if temp_k >= 66 else (0 if temp_k <= 19 else max(0, min(255, 138.5177 * math.log(temp_k - 10) - 305.0447)))
    
    return [int(r), int(g), int(b)]

def calculate_dynamic_sky_colors(altitude_deg, temp, clouds):
    keys = [
        (-6,   15,   25,   60),   
        (0,   255,  100,   50),   
        (10,   80,  160,  255),   
        (35,  255,  255,  255),   
        (55,  255,  255,  255),   
        (90,  255,  255,  255)    
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

    wb_tint = get_white_balance_rgb(temp)
    r = (r * wb_tint[0]) / 255.0
    g = (g * wb_tint[1]) / 255.0
    b = (b * wb_tint[2]) / 255.0

    c_ratio = clouds / 100.0
    grey_val = (r + g + b) / 3.0
    desat_strength = c_ratio * 0.90 
    
    r = r + (grey_val - r) * desat_strength
    g = g + (grey_val - g) * desat_strength
    b = b + (grey_val - b) * desat_strength
    
    return [int(max(0, min(255, r))), int(max(0, min(255, g))), int(max(0, min(255, b)))]

def get_day_payload(alt, temp, clouds, is_stormy):
    sun_color = [255, 241, 224] 
    if alt < 15:
        progress = max(0, min(1, alt / 15.0))
        sun_color = [255, int(lerp(140, 241, progress)), int(lerp(0, 224, progress))]
        
    sky_color = calculate_dynamic_sky_colors(alt, temp, clouds)
    
    if is_stormy or clouds > 75:
        progress = min(1.0, max(0.0, (clouds - 75) / 25.0))
        sun_alpha = int(lerp(100, 0, progress))
        global_bri = int(lerp(200, 150, progress)) if not is_stormy else 130
        cloud_color = [15, 15, 15]     
    elif clouds <= 35:
        sun_alpha = 255
        global_bri = 255
        cloud_color = [27, 27, 27]  
    else:
        progress = (clouds - 35) / 40.0
        sun_alpha = int(lerp(255, 100, progress))
        global_bri = int(lerp(255, 200, progress))
        cloud_color = [20, 20, 20] 

    return global_bri, sun_color, sky_color, cloud_color, sun_alpha
