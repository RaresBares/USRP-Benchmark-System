import json
import asyncio
import numpy as np
import websockets
import urllib.request
import urllib.error


class USRPClient:
    _host = None
    _port = None
    _token = None
    _info = None

    @classmethod
    def setup(cls, host="localhost", port=8000, token="default-bench-token-2024"):
        cls._host = host
        cls._port = port
        cls._token = token
        cls._info = None

    @classmethod
    def _base_url(cls):
        if cls._host is None:
            raise RuntimeError("Call USRPClient.setup() first")
        return f"{cls._host}:{cls._port}"

    @classmethod
    def _fetch_info(cls):
        if cls._info is not None:
            return cls._info
        try:
            url = f"http://{cls._base_url()}/info?auth_token={cls._token}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                cls._info = json.loads(resp.read())
        except Exception:
            cls._info = {}
        return cls._info

    @classmethod
    def check(cls) -> bool:
        try:
            url = f"http://{cls._base_url()}/health?auth_token={cls._token}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                return data.get("status") == "ok"
        except Exception:
            return False

    @classmethod
    @property
    def carrier_frequency(cls) -> int:
        return cls._fetch_info().get("carrier_frequency_hz", 0)

    @classmethod
    @property
    def sample_rate(cls) -> int:
        return cls._fetch_info().get("sample_rate_hz", 0)

    @classmethod
    @property
    def bandwidth(cls) -> int:
        return cls._fetch_info().get("bandwidth_hz", 0)

    @classmethod
    @property
    def tx_gain(cls) -> int:
        return cls._fetch_info().get("tx_gain_db", 0)

    @classmethod
    @property
    def rx_gain(cls) -> int:
        return cls._fetch_info().get("rx_gain_db", 0)

    @classmethod
    @property
    def snr(cls) -> float:
        return cls._fetch_info().get("channel_snr_db", 0)

    @classmethod
    @property
    def max_samples(cls) -> int:
        return cls._fetch_info().get("max_samples", 0)

    @classmethod
    def info(cls) -> dict:
        return cls._fetch_info()

    @classmethod
    def send(cls, signal: np.ndarray) -> np.ndarray:
        signal = np.asarray(signal, dtype=np.complex64)
        raw = np.empty(len(signal) * 2, dtype=np.float32)
        raw[0::2] = signal.real
        raw[1::2] = signal.imag
        result_bytes = asyncio.run(cls._ws_send(raw.tobytes()))
        raw_out = np.frombuffer(result_bytes, dtype=np.float32)
        return raw_out[0::2] + 1j * raw_out[1::2]

    @classmethod
    async def _ws_send(cls, data: bytes) -> bytes:
        url = f"ws://{cls._base_url()}/ws/run?auth_token={cls._token}"
        async with websockets.connect(url, max_size=200 * 1024 * 1024) as ws:
            await ws.send(data)
            while True:
                msg = await ws.recv()
                if isinstance(msg, bytes):
                    return msg
                info = json.loads(msg)
                if "error" in info:
                    raise RuntimeError(f"Server error: {info['message']}")
                if info.get("message") == "info":
                    cls._info = {k: v for k, v in info.items() if k != "message"}
