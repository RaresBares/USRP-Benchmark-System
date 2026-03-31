import numpy as np
def demodulate(signal):
    return (signal.real > 0).astype(np.uint8)
