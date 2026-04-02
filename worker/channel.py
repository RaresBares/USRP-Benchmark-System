import os
import time
import logging
import numpy as np

try:
    from usrp_testbed_library.constants import (
        DEFAULT_TX_REP_PORT,
        DEFAULT_RX_REP_PORT,
    )
except ImportError:
    DEFAULT_TX_REP_PORT = 5557
    DEFAULT_RX_REP_PORT = 5555

logger = logging.getLogger("channel")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
)

USE_REAL_USRP = os.getenv("USE_REAL_USRP", "false").lower() == "true"

SAMPLE_RATE = float(os.getenv("SAMPLE_RATE_HZ", "20000000"))
CARRIER_FREQ = float(os.getenv("CARRIER_FREQUENCY_HZ", "2400000000"))
TX_GAIN = float(os.getenv("TX_GAIN_DB", "30"))
RX_GAIN = float(os.getenv("RX_GAIN_DB", "30"))
ANTENNA_TX = os.getenv("ANTENNA_TX", "TX/RX0")
ANTENNA_RX = os.getenv("ANTENNA_RX", "RX1")
TX_CHANNEL = int(os.getenv("TX_CHANNEL", "0"))
RX_CHANNEL = int(os.getenv("RX_CHANNEL", "0"))
SNR_DB = float(os.getenv("CHANNEL_SNR_DB", "20"))

TX_DAEMON_HOST = os.getenv("TX_DAEMON_HOST", "host.docker.internal")
TX_DAEMON_PORT = int(os.getenv("TX_DAEMON_PORT", "5557"))
RX_DAEMON_HOST = os.getenv("RX_DAEMON_HOST", "host.docker.internal")
RX_DAEMON_PORT = int(os.getenv("RX_DAEMON_PORT", "5555"))

SIGNAL_DIR = os.getenv("SIGNAL_DIR", "/data/signals")
SIGNAL_DIR_HOST = os.getenv("SIGNAL_DIR_HOST", SIGNAL_DIR)

TX_RX_DELAY_DIFF = float(os.getenv("TX_RX_DELAY_DIFF", "0.1"))
INITIAL_DELAY = float(os.getenv("INITIAL_DELAY", "1.0"))
OPERATION_TIMEOUT_MARGIN = 5.0

DUTY_CYCLE_MAX = float(os.getenv("DUTY_CYCLE_MAX_PERCENT", "10")) / 100.0
DUTY_CYCLE_WINDOW = float(os.getenv("DUTY_CYCLE_WINDOW_SEC", "60"))

LBT_ENABLED = os.getenv("LBT_ENABLED", "true").lower() == "true"
LBT_THRESHOLD_DBFS = float(os.getenv("LBT_THRESHOLD_DBFS", "-50"))
LBT_SENSE_SAMPLES = int(os.getenv("LBT_SENSE_SAMPLES", "200000"))
LBT_MAX_RETRIES = int(os.getenv("LBT_MAX_RETRIES", "10"))
LBT_BACKOFF_SEC = float(os.getenv("LBT_BACKOFF_SEC", "1.0"))

CONNECTIVITY_TIMEOUT_MS = 2000
CONFIGURE_TIMEOUT_MS = 5000
SIGNAL_LOAD_TIMEOUT_MS = 10000


def _awgn_send_and_receive(signal):
    signal_power = np.mean(np.abs(signal) ** 2)
    if signal_power == 0:
        return signal
    noise_power = signal_power / (10 ** (SNR_DB / 10))
    noise = np.sqrt(noise_power / 2) * (
        np.random.randn(len(signal)) + 1j * np.random.randn(len(signal))
    )
    return signal + noise


class USRPChannel:

    def __init__(self):
        self._tx_context = None
        self._tx_req = None
        self._rx_context = None
        self._rx_req = None
        self._configured = False
        self._tx_history = []

    def _connect(self):
        if self._tx_req is not None:
            return

        import zmq

        self._tx_context = zmq.Context()
        self._tx_req = self._tx_context.socket(zmq.REQ)
        self._tx_req.connect(f"tcp://{TX_DAEMON_HOST}:{TX_DAEMON_PORT}")
        self._tx_req.setsockopt(zmq.RCVTIMEO, CONNECTIVITY_TIMEOUT_MS)

        self._rx_context = zmq.Context()
        self._rx_req = self._rx_context.socket(zmq.REQ)
        self._rx_req.connect(f"tcp://{RX_DAEMON_HOST}:{RX_DAEMON_PORT}")
        self._rx_req.setsockopt(zmq.RCVTIMEO, CONNECTIVITY_TIMEOUT_MS)

        self._tx_req.send_json({"op": "PING"})
        resp = self._tx_req.recv_json()
        if resp.get("status") != "OK":
            raise RuntimeError(f"TX daemon ping failed: {resp}")

        self._rx_req.send_json({"op": "PING"})
        resp = self._rx_req.recv_json()
        if resp.get("status") != "OK":
            raise RuntimeError(f"RX daemon ping failed: {resp}")

        logger.info("Connected to TX daemon at %s:%s", TX_DAEMON_HOST, TX_DAEMON_PORT)
        logger.info("Connected to RX daemon at %s:%s", RX_DAEMON_HOST, RX_DAEMON_PORT)

        os.makedirs(SIGNAL_DIR, exist_ok=True)

    def _configure(self):
        if self._configured:
            return

        import zmq

        self._connect()

        tx_cmd = {
            "op": "CONFIGURE_USRP",
            "fs": SAMPLE_RATE,
            "fc": CARRIER_FREQ,
            "sync_channels": [TX_CHANNEL],
            "intf_channels": [],
            "G_TX": {str(TX_CHANNEL): TX_GAIN},
            "antenna": ANTENNA_TX
        }
        self._tx_req.setsockopt(zmq.RCVTIMEO, CONFIGURE_TIMEOUT_MS)
        self._tx_req.send_json(tx_cmd)
        resp = self._tx_req.recv_json()
        if resp.get("status") == "ERROR":
            raise RuntimeError(f"TX configure failed: {resp.get('error')}")
        logger.info("TX USRP configured: %s", resp.get("status"))

        rx_cmd = {
            "op": "CONFIGURE_USRP",
            "fs": SAMPLE_RATE,
            "fc": CARRIER_FREQ,
            "channels": [RX_CHANNEL],
            "G_RX": RX_GAIN,
            "antenna": ANTENNA_RX
        }
        self._rx_req.setsockopt(zmq.RCVTIMEO, CONFIGURE_TIMEOUT_MS)
        self._rx_req.send_json(rx_cmd)
        resp = self._rx_req.recv_json()
        if resp.get("status") == "ERROR":
            raise RuntimeError(f"RX configure failed: {resp.get('error')}")
        logger.info("RX USRP configured: %s", resp.get("status"))

        self._configured = True

    def _to_host_path(self, container_path):
        return str(container_path).replace(SIGNAL_DIR, SIGNAL_DIR_HOST, 1)

    def _check_duty_cycle(self, signal_duration):
        now = time.time()
        cutoff = now - DUTY_CYCLE_WINDOW
        self._tx_history = [(t, d) for t, d in self._tx_history if t > cutoff]
        total_tx_time = sum(d for _, d in self._tx_history)
        max_allowed = DUTY_CYCLE_MAX * DUTY_CYCLE_WINDOW
        available = max_allowed - total_tx_time

        if signal_duration > available:
            wait_time = signal_duration - available + 1.0
            logger.warning(
                "Duty cycle limit: %.2fs used / %.2fs allowed in %ds window. "
                "Need to wait %.1fs",
                total_tx_time, max_allowed, int(DUTY_CYCLE_WINDOW), wait_time
            )
            return False, wait_time
        logger.info(
            "Duty cycle OK: %.2fs used + %.4fs new / %.2fs allowed",
            total_tx_time, signal_duration, max_allowed
        )
        return True, 0.0

    def _listen_before_talk(self):
        if not LBT_ENABLED:
            return

        import zmq
        import h5py

        for attempt in range(LBT_MAX_RETRIES):
            self._rx_req.setsockopt(zmq.RCVTIMEO, 5000)
            self._rx_req.send_json({"op": "FLUSH_RX"})
            self._rx_req.recv_json()

            sense_file = os.path.join(SIGNAL_DIR, "lbt_sense.h5")
            host_sense_file = self._to_host_path(sense_file)
            sense_duration = LBT_SENSE_SAMPLES / SAMPLE_RATE
            timeout_ms = int((sense_duration + OPERATION_TIMEOUT_MARGIN) * 1000)

            self._rx_req.setsockopt(zmq.RCVTIMEO, timeout_ms)
            self._rx_req.send_json({
                "op": "RECEIVE_TO_FILE",
                "n_samples": LBT_SENSE_SAMPLES,
                "path": host_sense_file,
                "delay": 0.5
            })
            resp = self._rx_req.recv_json()

            if resp.get("status") != "OK":
                logger.warning("LBT sense failed: %s", resp.get("error"))
                time.sleep(LBT_BACKOFF_SEC)
                continue

            try:
                with h5py.File(sense_file, "r") as f:
                    rx_data = f["rx_signal"][:]
                    if rx_data.ndim == 2:
                        rx_data = rx_data[0]
                    power = float(np.mean(np.abs(rx_data) ** 2))
                    power_dbfs = 10 * np.log10(power + 1e-20)
            except Exception as e:
                logger.warning("LBT: could not read sense file: %s", e)
                time.sleep(LBT_BACKOFF_SEC)
                continue
            finally:
                try:
                    os.unlink(sense_file)
                except OSError:
                    pass

            logger.info(
                "LBT sense: %.1f dBFS (threshold: %.1f dBFS)",
                power_dbfs, LBT_THRESHOLD_DBFS
            )

            if power_dbfs < LBT_THRESHOLD_DBFS:
                logger.info("LBT: channel clear")
                return

            logger.warning(
                "LBT: channel busy (attempt %d/%d), backing off %.1fs",
                attempt + 1, LBT_MAX_RETRIES, LBT_BACKOFF_SEC
            )
            time.sleep(LBT_BACKOFF_SEC)

        raise RuntimeError(
            f"Listen Before Talk failed: channel busy after {LBT_MAX_RETRIES} retries"
        )

    def send_and_receive(self, signal):
        import zmq
        import h5py

        self._configure()

        n_samples = len(signal)
        signal_duration = n_samples / SAMPLE_RATE

        while True:
            allowed, wait_time = self._check_duty_cycle(signal_duration)
            if allowed:
                break
            time.sleep(wait_time)

        self._listen_before_talk()

        uid = f"{int(time.time() * 1000)}_{os.getpid()}"
        tx_file = os.path.join(SIGNAL_DIR, f"tx_{uid}.h5")
        rx_file = os.path.join(SIGNAL_DIR, f"rx_{uid}.h5")
        host_tx_file = self._to_host_path(tx_file)
        host_rx_file = self._to_host_path(rx_file)

        try:
            with h5py.File(tx_file, "w") as f:
                f.create_dataset("tx_signal", data=signal.astype(np.complex64))

            self._tx_req.setsockopt(zmq.RCVTIMEO, SIGNAL_LOAD_TIMEOUT_MS)
            self._tx_req.send_json({
                "op": "LOAD_SIGNAL",
                "sync_signal_path": host_tx_file
            })
            resp = self._tx_req.recv_json()
            if resp.get("status") != "OK":
                raise RuntimeError(f"TX LOAD_SIGNAL failed: {resp.get('error')}")

            signal_info = resp.get("signal_info", {})
            logger.info(
                "TX signal loaded: %d samples",
                signal_info.get("total_samples", 0)
            )

            tx_start_delay = INITIAL_DELAY + TX_RX_DELAY_DIFF
            rx_start_delay = INITIAL_DELAY
            rx_duration = 2 * TX_RX_DELAY_DIFF + signal_duration
            rx_samples_needed = int(np.round(rx_duration * SAMPLE_RATE))

            self._rx_req.setsockopt(zmq.RCVTIMEO, 5000)
            self._rx_req.send_json({"op": "FLUSH_RX"})
            self._rx_req.recv_json()

            rx_timeout_ms = int(
                (rx_start_delay + rx_duration + OPERATION_TIMEOUT_MARGIN) * 1000
            )
            self._rx_req.setsockopt(zmq.RCVTIMEO, rx_timeout_ms)
            self._rx_req.send_json({
                "op": "RECEIVE_TO_FILE",
                "n_samples": rx_samples_needed,
                "path": host_rx_file,
                "delay": rx_start_delay
            })

            tx_timeout_ms = int(
                (tx_start_delay + signal_duration + OPERATION_TIMEOUT_MARGIN) * 1000
            )
            self._tx_req.setsockopt(zmq.RCVTIMEO, tx_timeout_ms)
            self._tx_req.send_json({
                "op": "TRANSMIT_BURST",
                "delay": tx_start_delay
            })

            tx_resp = self._tx_req.recv_json()
            if tx_resp.get("status") != "OK":
                raise RuntimeError(
                    f"TRANSMIT_BURST failed: {tx_resp.get('error')}"
                )
            logger.info("TX done: %d samples sent", tx_resp.get("samples_sent", 0))

            rx_resp = self._rx_req.recv_json()
            if rx_resp.get("status") != "OK":
                raise RuntimeError(
                    f"RECEIVE_TO_FILE failed: {rx_resp.get('error')}"
                )
            logger.info(
                "RX done: %d samples received",
                rx_resp.get("samples_received", 0)
            )

            self._tx_history.append((time.time(), signal_duration))

            with h5py.File(rx_file, "r") as f:
                rx_data = f["rx_signal"][:]
                if rx_data.ndim == 2:
                    rx_data = rx_data[0]

            return rx_data.astype(np.complex64)

        finally:
            for p in (tx_file, rx_file):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def close(self):
        import zmq
        for sock in (self._tx_req, self._rx_req):
            if sock:
                try:
                    sock.setsockopt(zmq.LINGER, 0)
                    sock.close()
                except Exception:
                    pass
        for ctx in (self._tx_context, self._rx_context):
            if ctx:
                try:
                    ctx.term()
                except Exception:
                    pass


_channel = None


def send_and_receive(signal):
    global _channel

    if not USE_REAL_USRP:
        return _awgn_send_and_receive(signal)

    if _channel is None:
        _channel = USRPChannel()
    return _channel.send_and_receive(signal)
