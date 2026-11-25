# Autonomous Propulsion Telemetry and Thermal Control Architecture (Spec v2.4)

## 1. System Overview and Deterministic Ingestion

This specification defines the real-time **telemetry pipeline** and **closed-loop control** subsystem for the Orbital Maneuvering Stage (`OMS-4`). During orbital burn phases, the avionics bus aggregates high-rate pressure, propellant mass-flow, and chamber-wall readings into a fixed-size **ring buffer** before dispatching telemetry frames to ground control. Each binary frame carries a compact **payload**, a sequence counter, and a 32-bit **checksum** validated prior to persistence.

To guarantee deterministic **fault tolerance** across intermittent deep-space links, every uplink and downlink transaction attaches a unique **idempotency key** inside the `idempotency_hdr` frame header. Downstream consumers enforce **backpressure** when ingestion queues exceed 80% capacity and isolate poison frames inside a **dead-letter queue** after three failed verification cycles.

<callout severity="critical">

Verify the `MAX_WALL_TEMP_K` threshold on <sensor-ref id="TC-07" channel="ch0" /> before flashing any new **firmware image** to the propulsion controller.

</callout>

## 2. Physics of Thermal Protection and Propulsion Efficiency

Regenerative nozzle cooling prevents **thermal runaway** inside the silicon-carbide combustion liner. Conductive heat transfer across the liner wall obeys Fourier's law, where the local **heat flux** depends directly on the material **thermal conductivity** $k$ and the spatial temperature gradient:

$$q'' = -k \nabla T$$

Propulsion efficiency is governed by the vacuum **specific impulse** $I_{sp}$, defined as the ratio of thrust $F$ to propellant weight flow rate $\dot{m} g_0$:

$$I_{sp} = \frac{F}{\dot{m} g_0}$$

Because raw thermocouple signals exhibit electromagnetic noise during valve actuation, an extended Kalman **state estimator** performs multi-rate **sensor fusion** between optical pyrometers and resistive probes. The discrete-time Kalman gain matrix $K_k$ updates at every control step $\Delta t \le 2\text{ ms}$:

$$K_k = P_{k|k-1} H^T \left( H P_{k|k-1} H^T + R \right)^{-1}$$

Meanwhile, the active valve-modulation loop drives the **steady-state error** below $\pm 0.5\text{ K}$ via the continuous-time PID law:

$$u(t) = K_p e(t) + K_i \int_0^t e(\tau)\,d\tau + K_d \frac{de(t)}{dt}$$

## 3. Operating Envelope and Telemetry SLA Matrix

| Subsystem Parameter | Nominal Target | Upper Bound | Telemetry Variable |
| :--- | :--- | :--- | :--- |
| Acquisition **sampling rate** | $500\text{ Hz}$ | $1000\text{ Hz}$ | `sample_rate_hz` |
| End-to-end timing **jitter** | $< 120\,\mu\text{s}$ | $250\,\mu\text{s}$ | `frame_jitter_us` |
| Chamber **heat flux** | $4.2\text{ MW/m}^2$ | $6.8\text{ MW/m}^2$ | `wall_flux_mw_m2` |
| **Specific impulse** | $318\text{ s}$ | $326\text{ s}$ | `vac_isp_s` |
| **Steady-state error** | $\le 0.25\text{ K}$ | $0.50\text{ K}$ | `thermal_ss_err_k` |

| Resilience Mechanism | Trigger Condition | Recovery Action | Guard Symbol |
| :--- | :--- | :--- | :--- |
| **Circuit breaker** | 5 consecutive CRC failures | Open bus & route to fallback | `bus_breaker.trip()` |
| **Watchdog timer** | Missed heartbeat $> 15\text{ ms}$ | Enter **fail-safe mode** | `watchdog_kick()` |
| **Cold start** recovery | Power-on reset or brownout | Load verified **firmware image** | `boot_verify_crc32()` |
| **Dead-letter queue** | Exhausted retry budget | Quarantine malformed **payload** | `dlq_sink.push()` |

## 4. Concurrency Safety and Flight Software Implementation

Multi-core avionics tasks share DMA-mapped memory descriptors; improper lock ordering can trigger a **deadlock**, while unsynchronized ISR writes introduce a **race condition** in frame sequence counters. Consequently, the flight software mandates lock-free single-producer/single-consumer indexing inside the **ring buffer** and validates every frame **checksum** using `verify_crc32()`.

```python
import struct
import zlib
from collections import deque
from threading import Lock


class TelemetryRingBuffer:
    """Thread-safe circular telemetry queue with CRC32 checksum verification."""

    def __init__(self, capacity: int = 1024) -> None:
        self._buffer: deque[bytes] = deque(maxlen=capacity)
        self._lock = Lock()

    def push_frame(self, payload: bytes, expected_crc32: int) -> bool:
        actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if actual_crc != expected_crc32:
            return False
        frame = struct.pack(">I", actual_crc) + payload
        with self._lock:
            self._buffer.append(frame)
        return True
```

The thermal regulation task executes the discrete **closed-loop control** step at fixed **sampling rate** intervals. Whenever predicted wall temperature approaches the **thermal runaway** boundary, the **circuit breaker** trips and forces **fail-safe mode**.

```python
class ThermalPIDController:
    """Discrete-time thermal regulator with runaway protection."""

    def __init__(self, kp: float, ki: float, kd: float, max_temp_k: float = 1150.0) -> None:
        self.kp, self.ki, self.kd = kp, ki, kd
        self.max_temp_k = max_temp_k
        self._integral = 0.0
        self._prev_error = 0.0

    def step(self, setpoint_k: float, measured_k: float, dt_s: float) -> float:
        if measured_k >= self.max_temp_k:
            return 0.0  # Immediate fail-safe cutoff
        error = setpoint_k - measured_k
        self._integral += error * dt_s
        derivative = (error - self._prev_error) / dt_s
        self._prev_error = error
        return self.kp * error + self.ki * self._integral + self.kd * derivative
```

## 5. XML Bus Descriptor and Verification Checklist

<telemetry-config version="2.4" bus="SpaceWire-A">
  <endpoint role="primary" idempotency="enabled" crc="CRC32-IEEE" />
  <watchdog period_ms="15" action="fail-safe-cutoff" />
  <thermal-guard max_flux_mw_m2="6.8" sensor="TC-07" />
</telemetry-config>

Before flight-readiness sign-off, engineers must confirm that **cold start** initialization clears residual queue **backpressure**, eliminates **deadlock** and **race condition** hazards under stress testing, keeps **jitter** within spec, and guarantees end-to-end **fault tolerance** across the **telemetry pipeline** and **state estimator** via verified **sensor fusion**.
