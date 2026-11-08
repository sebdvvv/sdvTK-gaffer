// noise_lib.h
float fbm(point p, float t, int octaves)
{
    float sum = 0.0, amp = 0.5;
    point q = p;
    for (int i = 0; i < octaves; i++) {
        // 4D perlin: position + time, signed range
        sum += amp * noise("perlin", q, t);
        q *= 2.0;
        amp *= 0.5;
    }
    return sum;
}
