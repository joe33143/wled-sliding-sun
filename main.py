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
