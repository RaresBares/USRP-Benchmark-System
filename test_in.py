import numpy as np
def modulate(bits):
    return np.array(bits, dtype=np.float32) * 2.0 - 1.0 + 0j
