import os
import numpy as np

SNR_DB = float(os.getenv("CHANNEL_SNR_DB", "20"))


def send_and_receive(signal: np.ndarray) -> np.ndarray:
    signal_power = np.mean(np.abs(signal) ** 2)
    if signal_power == 0:
        return signal

    noise_power = signal_power / (10 ** (SNR_DB / 10))
    noise = np.sqrt(noise_power / 2) * (
        np.random.randn(len(signal)) + 1j * np.random.randn(len(signal))
    )
    return signal + noise
